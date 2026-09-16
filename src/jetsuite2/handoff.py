"""L3 solver hand-off: export watertight, meshable geometry with boundary
conditions, and ingest solver results back into the design state.

``export_cfd(design, component)`` writes ``<design>/handoff/<component>_cfd/``:

    case.json           operating point, boundary conditions (Pt, Tt, mass flow, outlet
                        static pressure, rotation, turbulence intensity), gas properties,
                        expected results (L1/L2 values) and the fields to ingest back
    hub.curve / shroud.curve / blade_<k>.curve   TurboGrid-style meridional and blade
                        section point files (mm); blade sections as suction+pressure
                        loops at several spans
    flowpath.step       revolved fluid channel (hub-to-shroud, full annulus) as a solid
    <component>.step    the solid part (from the CAD cache when present)

``export_fea(design, component)`` writes ``<design>/handoff/<component>_fea/`` with the
solid STEP, the material card (E, nu, rho, alpha, yield vs T), rotation, thermal boundary
temperatures, constraint faces (bore / stub) and the expected L1 stresses.

``ingest_template(component)`` returns the JSON the user fills with solver results;
``jet ingest`` maps it onto the stage outputs as L3 overrides (see api.Design.ingest).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .library import materials
from .state.store import get_path

INGEST_FIELDS = {
    "compressor": {"eta_tt_est": "stage total-total isentropic efficiency at the design point",
                   "PR_cfd": "stage total pressure ratio at the design point (informational)",
                   "choke_margin": "flow to choke / design flow - 1",
                   "alpha3_L2_deg": "vaneless-space exit flow angle [deg from radial]"},
    "turbine": {"eta_tt_est": "stage total-total efficiency", "M3": "rotor exit absolute Mach", "alpha3_deg": "exit swirl [deg]"},
    "mechanical": {"impeller.sigma_peak_Pa": "peak von Mises in the impeller at MCS [Pa]",
                   "turbine.sigma_peak_Pa": "peak von Mises in the turbine disc at MCS [Pa]",
                   "turbine.sigma_avg_Pa": "average tangential stress in the turbine disc [Pa]"},
    "combustor1d": {"pattern_factor": "measured/CFD pattern factor", "liner_wall_T_K": "peak liner wall temperature [K]",
                    "eta_b_model": "combustion efficiency"},
    "rotor": {"bending_critical_rpm": "first forward bending critical speed [rpm] (FE rotordynamics)"},
}


def _write_curve(path: Path, pts_mm, comment: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {comment}\n# x[mm] y[mm] z[mm]\n")
        for p in pts_mm:
            f.write(" ".join(f"{float(v):.5f}" for v in p) + "\n")


def export_cfd(design, component: str = "compressor") -> dict:
    o = design.outputs()
    cy, sheet = o["cycle"], o["geometry"]["sheet"]
    hdir = Path(design.dir) / "handoff" / f"{component}_cfd"
    hdir.mkdir(parents=True, exist_ok=True)
    files = {}
    if component == "compressor":
        c = o["compressor"]; imp = sheet["impeller"]
        from .cad.impeller import camber_grids, hub_curve_from_profile
        sh = dict(imp); sh["splitter_start"] = 1.0 - imp["splitter_length_frac"]
        hub = hub_curve_from_profile(imp["hub_profile"], imp["r1h"], imp["r2"])
        _write_curve(hdir / "hub.curve", [(x, r, 0.0) for x, r in hub], "impeller hub meridional curve (x, r)")
        _write_curve(hdir / "shroud.curve", [(x, r, 0.0) for x, r in imp["shroud_curve"]], "shroud meridional curve incl. the exit width offset")
        for k, splitter in ((0, False), (1, True)):
            if splitter and imp["n_splitter"] == 0:
                continue
            ss, ps, th = camber_grids(sh, n_span=5, n_chord=41, embed=0.0, splitter=splitter)
            with open(hdir / f"blade_{'splitter' if splitter else 'main'}.curve", "w", encoding="utf-8") as f:
                f.write(f"# {'splitter' if splitter else 'main'} blade sections, {ss.shape[0]} spans; each section = suction side LE->TE then pressure side TE->LE (closed loop), mm\n")
                for i in range(ss.shape[0]):
                    f.write(f"# section {i} span {i/(ss.shape[0]-1):.2f}\n")
                    loop = np.vstack([ss[i], ps[i][::-1]])
                    for p in loop:
                        f.write(" ".join(f"{float(v):.5f}" for v in p) + "\n")
            files[f"blade_{'splitter' if splitter else 'main'}"] = True
        # fluid channel solid (full annulus)
        try:
            from .cad import cadlib
            import cadquery as cq
            prof = [(x, r) for x, r in hub] + [(x, r) for x, r in imp["shroud_curve"][::-1]]
            ch = cadlib.revolve(prof)
            cq.exporters.export(cq.Workplane().add(ch), str(hdir / "flowpath.step"))
            files["flowpath.step"] = True
        except Exception as ex:  # noqa: BLE001
            files["flowpath.step"] = f"failed: {ex}"
        case = dict(component="compressor", design=design.doc["name"], version=design.store.version,
                    rotation_rpm=o["speed"]["rpm"], rotation_axis="+x", blade_counts=dict(main=imp["n_main"], splitter=imp["n_splitter"]),
                    inlet=dict(Pt_Pa=cy["Pt2_Pa"], Tt_K=cy["Tt2_K"], flow_direction="axial", turbulence_intensity=0.05, viscosity_ratio=10),
                    outlet=dict(mass_flow_kg_s=cy["W_kg_s"], static_pressure_Pa_estimate=c["P4_Pa"], location="diffuser exit r4"),
                    walls=dict(tip_clearance_mm=imp["tip_clearance"], shroud="stationary", hub="rotating", roughness_um=1.6),
                    gas=dict(model="ideal gas, cp(T) polynomial (Walsh & Fletcher)", R=287.05),
                    diffuser=dict(type=c["diffuser_type"], r3_mm=c["r3_m"] * 1e3, r4_mm=c["r4_m"] * 1e3, n_vanes=c["n_vanes"],
                                  vane_le_angle_deg=c["vane_le_angle_deg"], vane_te_angle_deg=c["vane_te_angle_deg"],
                                  throat_width_mm=(c["vane_throat_width_m"] or 0) * 1e3),
                    expected=dict(PR_tt_L1=cy["OPR"], eta_tt_L1=c["eta_tt_est"], PR_tt_L2=o.get("maps", {}).get("design_point", {}).get("PR"),
                                  eta_tt_L2=o.get("maps", {}).get("design_point", {}).get("eta")),
                    ingest_fields=INGEST_FIELDS["compressor"], ingest_stage="compressor")
    elif component == "turbine":
        t = o["turbine"]
        case = dict(component="turbine", design=design.doc["name"], version=design.store.version, rotation_rpm=o["speed"]["rpm"],
                    inlet=dict(Pt_Pa=cy["Pt4_Pa"], Tt_K=cy["T04_K"], far=cy["far"], turbulence_intensity=0.10),
                    outlet=dict(static_pressure_Pa_estimate=t["P3_Pa"], mass_flow_kg_s=cy["W4_kg_s"]),
                    geometry=dict(r_mean_mm=t["r_mean_m"] * 1e3, h_ngv_mm=t["h_ngv_m"] * 1e3, h_rotor_mm=t["h_rotor_m"] * 1e3,
                                  n_ngv=t["n_ngv"], n_rotor=t["n_rotor"], alpha2_deg=t["alpha2_deg"], beta2_deg=t["beta2_deg"],
                                  beta3_deg=t["beta3_deg"], chord_ngv_mm=t["chord_ngv_m"] * 1e3, chord_rotor_mm=t["chord_rotor_m"] * 1e3,
                                  tip_clearance_mm=t["tip_clearance_m"] * 1e3),
                    expected=dict(eta_tt_L1=t["eta_tt_est"], PR_tt=cy["turbine_PR_tt"]),
                    ingest_fields=INGEST_FIELDS["turbine"], ingest_stage="turbine")
        for part in ("ngv_ring", "turbine_wheel"):
            src = Path(design.dir) / "cad" / "parts" / f"{part}.step"
            if src.exists():
                (hdir / f"{part}.step").write_bytes(src.read_bytes()); files[f"{part}.step"] = True
    else:
        raise ValueError("component must be compressor or turbine")
    src = Path(design.dir) / "cad" / "parts" / ("impeller.step" if component == "compressor" else "turbine_wheel.step")
    if src.exists():
        (hdir / src.name).write_bytes(src.read_bytes()); files[src.name] = True
    (hdir / "case.json").write_text(json.dumps(case, indent=1, default=float), encoding="utf-8")
    (hdir / "ingest_template.json").write_text(json.dumps(ingest_template(case["ingest_stage"]), indent=1), encoding="utf-8")
    files["case.json"] = True
    return dict(dir=str(hdir), files=files)


def export_fea(design, component: str = "impeller") -> dict:
    o = design.outputs()
    hdir = Path(design.dir) / "handoff" / f"{component}_fea"
    hdir.mkdir(parents=True, exist_ok=True)
    me = o["mechanical"]
    if component == "impeller":
        mat = o["compressor"]["material"]; T_ref = me["impeller"]["T_disc_K"]
        bc = dict(rotation_rpm=o["speed"]["rpm_mcs"], constraint="bore cylindrical (radial free, axial+tangential fixed at the rear face)",
                  temperature_field=dict(eye_K=o["cycle"]["Tt2_K"] + 20, exit_K=o["compressor"]["T02_K"], law="linear in radius"),
                  pressure_load="impeller blade pressure from the CFD case (optional)",
                  expected=dict(sigma_peak_L1_Pa=me["impeller"]["sigma_peak_Pa"], sigma_avg_L1_Pa=me["impeller"]["sigma_avg_Pa"],
                                exducer_root_L1_Pa=o["compressor"]["sigma_root_mcs_Pa"]),
                  ingest_stage="mechanical", ingest_fields={"impeller.sigma_peak_Pa": INGEST_FIELDS["mechanical"]["impeller.sigma_peak_Pa"]})
        part = "impeller.step"
    elif component == "turbine":
        mat = o["turbine"]["material"]; T_ref = me["turbine"]["T_rim_K"]
        bc = dict(rotation_rpm=o["speed"]["rpm_mcs"], constraint="stub / bore fixed at the shaft interface",
                  temperature_field=dict(rim_K=me["turbine"]["T_rim_K"], bore_K=me["turbine"]["T_bore_K"], blade_K=o["turbine"]["T_metal_K"]),
                  expected=dict(sigma_peak_L1_Pa=me["turbine"]["sigma_peak_Pa"], sigma_avg_L1_Pa=me["turbine"]["sigma_avg_Pa"],
                                blade_root_L1_Pa=o["turbine"]["sigma_root_mcs_Pa"]),
                  ingest_stage="mechanical", ingest_fields={k: INGEST_FIELDS["mechanical"][k] for k in ("turbine.sigma_peak_Pa", "turbine.sigma_avg_Pa")})
        part = "turbine_wheel.step"
    else:
        raise ValueError("component must be impeller or turbine")
    m = materials.get(mat)
    card = dict(name=mat, E_Pa=m["E"], nu=m["nu"], rho=m["rho"], alpha_per_K=m["alpha"], k_W_mK=m["k"],
                yield_vs_T=[dict(T_K=T, Fty_MPa=s) for T, s in m["yield_table"]], uts_vs_T=[dict(T_K=T, Ftu_MPa=s) for T, s in m["uts_table"]],
                creep_vs_T=[dict(T_K=T, allowable_MPa=s) for T, s in m.get("creep_table", [])], T_max_K=m["T_max"],
                allowable_at_T_ref_Pa=materials.allowable_at(mat, T_ref))
    src = Path(design.dir) / "cad" / "parts" / part
    files = {}
    if src.exists():
        (hdir / part).write_bytes(src.read_bytes()); files[part] = True
    (hdir / "material.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    (hdir / "case.json").write_text(json.dumps(dict(component=component, design=design.doc["name"], version=design.store.version, **bc), indent=1, default=float), encoding="utf-8")
    (hdir / "ingest_template.json").write_text(json.dumps(ingest_template("mechanical", list(bc["ingest_fields"])), indent=1), encoding="utf-8")
    files.update({"material.json": True, "case.json": True})
    return dict(dir=str(hdir), files=files)


def ingest_template(stage: str, fields: list[str] | None = None) -> dict:
    fields = fields or list(INGEST_FIELDS.get(stage, {}))
    return {"stage": stage, "tier": "L3", "source": "<solver name, run id, date>",
            "fields": {f: None for f in fields}, "_doc": {f: INGEST_FIELDS.get(stage, {}).get(f, "") for f in fields}}
