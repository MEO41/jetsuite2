"""Validation cases and the runner behind ``jet validate``.

Sources (all data files live in ``validation/data``):

* ``boomsonic_v0_maps.json`` — TurboFlow 0.1.18 (Oh loss set, Wiesner slip; Benner
  turbine losses) design point and full maps of the boomsonic_v0 impeller and
  turbine, plus the JetCat P400-PRO-LN datasheet design point run through the
  same code.  Independent implementation of the same class of method: tests
  the *implementation* and the correlation choices, not the physics.
* ``microturbojet_database.csv`` — manufacturer datasheets (JetCat, AMT, KingTech,
  ...): thrust, mass flow, pressure ratio, rpm, EGT, fuel consumption, mass,
  size.  Measured engine-level data: tests the cycle + sizing chain.
* ``literature`` (in-code) — classical rig cases with published design-point
  values, transcribed from the open literature:
    - Eckardt impeller "O" (Eckardt 1976/1980, radial exit, 14 000 rpm, 400 mm)
    - NASA CC3 (Skoch et al. 1997, 4.54 kg/s, 21 789 rpm, PR 4.0, eta_tt ~0.84)
    - NASA HECC (Medic et al. 2014, 4 kg/s class, PR 4.0, measured surge margin 8.4 %
      at the design point with a vaned diffuser)
  Values are the commonly quoted design-point numbers and carry the stated
  tolerance; the original reports should be consulted before any of them is
  used as a formal acceptance criterion.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from .. import gas
from ..perf import closs, tloss

DATA = Path(__file__).with_name("data")


def load_maps() -> dict:
    return json.loads((DATA / "boomsonic_v0_maps.json").read_text(encoding="utf-8"))


def load_fleet() -> list[dict]:
    rows = []
    with open(DATA / "microturbojet_database.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            def num(k):
                try:
                    return float(r[k])
                except (ValueError, KeyError):
                    return None
            rows.append(dict(manufacturer=r["manufacturer"], model=r["model"], thrust_N=num("max_thrust_N"),
                             mass_kg=num("engine_mass_kg"), diameter_mm=num("diameter_mm"), length_mm=num("length_mm"),
                             rpm=num("max_rpm"), idle_rpm=num("idle_rpm"), PR=num("pressure_ratio"), W=num("mass_flow_kgps"),
                             EGT_C=num("EGT_max_C"), fuel=r.get("fuel_consumption_at_max", ""), source=r.get("source_url", "")))
    return rows


LITERATURE = {
    "eckardt_O": dict(description="Eckardt impeller O, radial blades, 20 blades, D2 400 mm, 14 000 rpm (Eckardt 1976)",
                      r1h=0.045, r1s=0.140, r2=0.200, b2=0.026, beta1b_rms=48.0, beta2b=0.0, n_main=20, n_split=0,
                      W=5.31, rpm=14000, T01=288.15, P01=101325.0, PR_meas=2.10, eta_meas=0.88, tol_PR=0.06, tol_eta=0.04,
                      vaneless=True, r4_r2=1.7),
    "nasa_cc3": dict(description="NASA CC3 centrifugal stage, 4.54 kg/s, 21 789 rpm, vaned diffuser (Skoch 1997)",
                     r1h=0.041, r1s=0.105, r2=0.2155, b2=0.017, beta1b_rms=55.0, beta2b=50.0, n_main=15, n_split=15,
                     W=4.54, rpm=21789, T01=288.15, P01=101325.0, PR_meas=4.0, eta_meas=0.84, tol_PR=0.08, tol_eta=0.05,
                     vaneless=False, r4_r2=1.45, n_vanes=24),
}


def _geom_from_lit(c: dict) -> closs.CompressorGeometry:
    r3 = 1.07 * c["r2"]
    n_v = 0 if c["vaneless"] else c["n_vanes"]
    g = closs.CompressorGeometry(r1h=c["r1h"], r1s=c["r1s"], r2=c["r2"], b2=c["b2"], beta1b_rms=c["beta1b_rms"],
                                 beta2b=c["beta2b"], n_main=c["n_main"], n_split=c["n_split"], split_frac=0.6,
                                 t_le=0.6e-3, t_te=1.2e-3, clearance=0.4e-3, L_ax=0.32 * 2 * c["r2"], r3=r3,
                                 r4=c["r4_r2"] * c["r2"], b3=c["b2"], n_vanes=n_v, vane_le_angle=0.0, vane_te_angle=35.0,
                                 vane_throat=0.0)
    if n_v:
        # set the vane LE angle and throat from the impeller-exit swirl of the loss model (design incidence -2 deg,
        # throat Mach 0.7), the same rule the compressor stage applies
        g0 = closs.CompressorGeometry(**{**g.__dict__, "n_vanes": 0})
        dp = closs.evaluate(g0, c["W"], c["rpm"] * 2 * math.pi / 60, c["T01"], c["P01"])
        g.vane_le_angle = (dp.alpha3 if dp.ok else 70.0) - 2.0
        A_th = c["W"] / gas.mass_flow_function(dp.T02 if dp.ok else 450.0, (dp.P02 if dp.ok else 3e5) * 0.985, 0.70, 1.0)
        g.vane_throat = A_th / (n_v * c["b2"])
    return g


def validate_compressor_model() -> list[dict]:
    """Design-point and speed-line comparison against TurboFlow and the literature cases."""
    V = load_maps()
    res = []
    dp = V["design_point_tool"]["compressor"]
    gi, vd, vl = dp["geometry"]["impeller"], dp["geometry"]["vaned_diffuser"], dp["geometry"]["vaneless_diffuser"]
    inp = dp["input"]
    A_th = inp["mdot"] / gas.mass_flow_function(496.0, inp["P01"] * 4.35, 0.70, 1.0)
    g = closs.CompressorGeometry(r1h=gi["radius_hub_in"], r1s=gi["radius_tip_in"], r2=gi["radius_out"], b2=gi["width_out"],
                                 beta1b_rms=gi["leading_edge_angle"], beta2b=15.0, n_main=12, n_split=12, split_frac=0.5,
                                 t_le=0.4e-3, t_te=0.8e-3, clearance=gi["tip_clearance"], L_ax=gi["length_axial"],
                                 r3=vl["radius_out"], r4=vd["radius_out"], b3=vd["width_out"], n_vanes=vd["number_of_vanes"],
                                 vane_le_angle=vd["leading_edge_angle"], vane_te_angle=vd["trailing_edge_angle"],
                                 vane_throat=A_th / (vd["number_of_vanes"] * vd["width_out"]))
    omega = inp["rpm"] * 2 * math.pi / 60
    r = closs.evaluate(g, inp["mdot"], omega, inp["T01"], inp["P01"])
    tf = dp["turboflow"]
    res.append(dict(case="boomsonic_v0 impeller design point vs TurboFlow", quantity="PR_tt", model=r.PR_tt, reference=tf["PR"],
                    error=(r.PR_tt - tf["PR"]) / tf["PR"], tolerance=0.06, source="TurboFlow 0.1.18 (Oh loss set)"))
    res.append(dict(case="boomsonic_v0 impeller design point vs TurboFlow", quantity="eta_tt", model=r.eta_tt, reference=tf["eta"],
                    error=r.eta_tt - tf["eta"], tolerance=0.04, source="TurboFlow 0.1.18"))
    td = V["design_point_tool"].get("td_check") or {}
    if isinstance(td, dict) and td.get("PR"):
        res.append(dict(case="boomsonic_v0 impeller design point vs NASA turbo-design", quantity="eta_tt", model=r.eta_tt,
                        reference=td.get("eta", 0.803), error=r.eta_tt - td.get("eta", 0.803), tolerance=0.04, source="turbo-design (Oh/Wiesner)"))
    # speed lines: RMS error of PR and eta on TurboFlow's points within the model's valid range
    for Nf in ("1.0", "0.8", "0.6"):
        pts = V["cc_b15"]["speedlines"][Nf]
        errs_pr, errs_eta, n = [], [], 0
        for w, pr, eta, ch in pts:
            rr = closs.evaluate(g, w, float(Nf) * omega, inp["T01"], inp["P01"])
            if rr.ok and not rr.stall:
                errs_pr.append((rr.PR_tt - pr) / pr); errs_eta.append(rr.eta_tt - eta); n += 1
        if n:
            res.append(dict(case=f"boomsonic_v0 speed line N={Nf} vs TurboFlow ({n} pts)", quantity="PR_tt rms rel. error",
                            model=float(np.sqrt(np.mean(np.square(errs_pr)))), reference=0.0,
                            error=float(np.sqrt(np.mean(np.square(errs_pr)))), tolerance=0.05, source="TurboFlow map"))
            res.append(dict(case=f"boomsonic_v0 speed line N={Nf} vs TurboFlow ({n} pts)", quantity="eta_tt rms error",
                            model=float(np.sqrt(np.mean(np.square(errs_eta)))), reference=0.0,
                            error=float(np.sqrt(np.mean(np.square(errs_eta)))), tolerance=0.04, source="TurboFlow map"))
    # P400 datasheet design point (TurboFlow-sized geometry not stored; use the fleet datasheet vs the design chain instead)
    for name, c in LITERATURE.items():
        gl = _geom_from_lit(c)
        rr = closs.evaluate(gl, c["W"], c["rpm"] * 2 * math.pi / 60, c["T01"], c["P01"])
        if rr.ok:
            res.append(dict(case=f"literature {name}: {c['description']}", quantity="PR_tt", model=rr.PR_tt, reference=c["PR_meas"],
                            error=(rr.PR_tt - c["PR_meas"]) / c["PR_meas"], tolerance=c["tol_PR"], source="literature (approximate geometry)"))
            res.append(dict(case=f"literature {name}", quantity="eta_tt", model=rr.eta_tt, reference=c["eta_meas"],
                            error=rr.eta_tt - c["eta_meas"], tolerance=c["tol_eta"], source="literature (approximate geometry)"))
        else:
            res.append(dict(case=f"literature {name}", quantity="evaluation", model=None, reference=None, error=None,
                            tolerance=None, source=rr.reason))
    return res


def validate_turbine_model() -> list[dict]:
    V = load_maps()
    tp = V["design_point_tool"]["turbine"]
    ge, des = tp["geometry"], V["turb_b15"]["design"]
    g = tloss.TurbineGeometry(r_mean=ge["radius_mean_in"][0], h_ngv=ge["height"][0], h_rot=ge["height"][1],
                              alpha2_b=abs(ge["gauging_angle"][0]), beta3_b=abs(ge["gauging_angle"][1]), beta2_b=ge["leading_edge_angle"][1],
                              n_ngv=int(round(2 * math.pi * ge["radius_mean_in"][0] / ge["pitch"][0])),
                              n_rot=int(round(2 * math.pi * ge["radius_mean_in"][1] / ge["pitch"][1])),
                              c_ngv=ge["chord"][0], c_rot=ge["chord"][1], cx_ngv=ge["axial_chord"][0], cx_rot=ge["axial_chord"][1],
                              te_ngv=ge["trailing_edge_thickness"][0], te_rot=ge["trailing_edge_thickness"][1],
                              tmax_c_ngv=ge["maximum_thickness_chord_ratio"][0], tmax_c_rot=ge["maximum_thickness_chord_ratio"][1],
                              clearance=ge["tip_clearance"][1], far=0.017)
    r = tloss.evaluate(g, des["omega"], des["T0"], des["p0"], des["p_out"])
    res = [dict(case="boomsonic_v0 turbine design point vs TurboFlow", quantity="mass flow", model=r.W, reference=des["opt_mdot"],
                error=(r.W - des["opt_mdot"]) / des["opt_mdot"], tolerance=0.06, source="TurboFlow (Benner losses)"),
           dict(case="boomsonic_v0 turbine design point vs TurboFlow", quantity="PR_tt", model=r.PR_tt, reference=des["opt_PR_tt"],
                error=(r.PR_tt - des["opt_PR_tt"]) / des["opt_PR_tt"], tolerance=0.03, source="TurboFlow"),
           dict(case="boomsonic_v0 turbine design point vs TurboFlow", quantity="eta_tt", model=r.eta_tt, reference=des["opt_eta_tt"],
                error=r.eta_tt - des["opt_eta_tt"], tolerance=0.06, source="TurboFlow; AMDC/KO is known ~3-6 pts pessimistic vs Benner")]
    for Nf in ("1.0", "0.8", "0.6"):
        pts = V["turb_b15"]["speedlines"][Nf]
        ew, ee = [], []
        for PR_tt, mdot, eta_tt, PR_ts, eta_ts in pts:
            if PR_ts < 1.3:
                continue
            rr = tloss.evaluate(g, float(Nf) * des["omega"], des["T0"], des["p0"], des["p0"] / PR_ts)
            if rr.ok:
                ew.append((rr.W - mdot) / mdot); ee.append(rr.eta_tt - eta_tt)
        if ew:
            res.append(dict(case=f"boomsonic_v0 turbine speed line N={Nf} ({len(ew)} pts)", quantity="mass flow rms rel. error",
                            model=float(np.sqrt(np.mean(np.square(ew)))), reference=0.0, error=float(np.sqrt(np.mean(np.square(ew)))),
                            tolerance=0.08, source="TurboFlow map"))
            res.append(dict(case=f"boomsonic_v0 turbine speed line N={Nf} ({len(ee)} pts)", quantity="eta_tt rms error",
                            model=float(np.sqrt(np.mean(np.square(ee)))), reference=0.0, error=float(np.sqrt(np.mean(np.square(ee)))),
                            tolerance=0.12, source="TurboFlow map"))
    return res


def validate_design_chain(design_factory) -> list[dict]:
    """Run the sizing chain on fleet datasheets that give thrust + rpm + PR + mass flow and compare."""
    res = []
    for e in load_fleet():
        if not (e["thrust_N"] and e["PR"] and e["W"] and e["rpm"]):
            continue
        try:
            d = design_factory(e)
            o = d.outputs()
            res.append(dict(case=f"fleet {e['manufacturer']} {e['model']} ({e['thrust_N']:.0f} N)", quantity="airflow", model=o["cycle"]["W_kg_s"],
                            reference=e["W"], error=(o["cycle"]["W_kg_s"] - e["W"]) / e["W"], tolerance=0.15, source=e["source"]))
            if e["diameter_mm"]:
                res.append(dict(case=f"fleet {e['manufacturer']} {e['model']}", quantity="diameter mm", model=o["geometry"]["envelope_OD_mm"],
                                reference=e["diameter_mm"], error=(o["geometry"]["envelope_OD_mm"] - e["diameter_mm"]) / e["diameter_mm"],
                                tolerance=0.25, source=e["source"]))
            if e["mass_kg"]:
                res.append(dict(case=f"fleet {e['manufacturer']} {e['model']}", quantity="mass kg", model=o["geometry"]["mass_total_kg"],
                                reference=e["mass_kg"], error=(o["geometry"]["mass_total_kg"] - e["mass_kg"]) / e["mass_kg"],
                                tolerance=0.5, source=e["source"]))
        except Exception as ex:  # noqa: BLE001
            res.append(dict(case=f"fleet {e['manufacturer']} {e['model']}", quantity="chain", model=None, reference=None,
                            error=None, tolerance=None, source=f"failed: {type(ex).__name__}: {ex}"))
    return res


def format_results(rows: list[dict]) -> str:
    out = []
    for r in rows:
        if r["error"] is None:
            out.append(f"  ?     {r['case'][:58]:<58} {r['quantity']:<26} {r['source']}")
            continue
        ok = abs(r["error"]) <= r["tolerance"]
        out.append(f"  {'ok  ' if ok else 'OUT '}  {r['case'][:58]:<58} {r['quantity']:<26} model {r['model']:.4g}  ref {r['reference']:.4g}  "
                   f"err {100*r['error']:+.1f} %  tol {100*r['tolerance']:.0f} %")
    return "\n".join(out)
