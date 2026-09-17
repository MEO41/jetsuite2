"""v3: fidelity tiers, ingest, loss-model validation, maps/matching, studies."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jetsuite2 import gas, gas_fast  # noqa: E402
from jetsuite2.api import Design  # noqa: E402
from jetsuite2.validation import cases  # noqa: E402
from jetsuite2 import studies  # noqa: E402


def test_gas_fast_matches_exact_polynomials():
    for T in (300.0, 700.0, 1150.0, 1600.0):
        for far in (0.0, 0.017, 0.035):
            assert abs(gas_fast.h(T, far) - float(gas.h(T, far))) < 200.0        # J/kg (0.02 %)
            assert abs(gas_fast.cp(T, far) - float(gas.cp(T, far))) < 0.5
    assert abs(gas_fast.T_from_h(float(gas.h(900.0, 0.02)), 0.02) - 900.0) < 0.05
    assert abs(gas_fast.isentropic_T(300.0, 4.0) - gas.isentropic_T(300.0, 4.0)) < 0.1
    assert abs(gas_fast.far_for_T04(500.0, 1150.0, 0.97) - gas.far_for_T04(500.0, 1150.0, 0.97)) < 2e-4


def test_compressor_loss_model_validation_within_tolerance():
    rows = cases.validate_compressor_model()
    bad = [r for r in rows if r["error"] is not None and abs(r["error"]) > r["tolerance"] and "TurboFlow" in r["source"]]
    assert not bad, bad


def test_turbine_loss_model_validation_within_tolerance():
    rows = cases.validate_turbine_model()
    bad = [r for r in rows if r["error"] is not None and abs(r["error"]) > r["tolerance"]]
    assert not bad, bad


@pytest.fixture(scope="module")
def design(tmp_path_factory):
    d = Design.create(tmp_path_factory.mktemp("v3") / "d", "v3", {"requirements.thrust_N": 400.0})
    rep = d.run()
    assert not rep.failed
    return d


def test_status_reports_tiers_and_core_flags(design):
    rows = {r["stage"]: r for r in design.status()}
    assert rows["cycle"]["tier"] == "L1" and rows["cycle"]["core"]
    assert rows["rotor"]["tier"] == "L2"
    assert "maps" in rows and not rows["maps"]["core"] and not rows["maps"]["ran"]


def test_ingest_overrides_value_and_invalidates_downstream(design):
    base_mass = design.outputs("geometry")["mass_total_kg"]
    res = design.ingest("compressor", {"eta_tt_est": 0.85}, tier="L3", source="test")
    assert "compressor" in res["stale"]
    rep = design.run()
    assert "compressor" in rep.ran
    out = design.outputs("compressor")
    assert out["eta_tt_est"] == 0.85 and out["_provenance"]["eta_tt_est"]["tier"] == "L3"
    assert design.store.stamps["compressor"]["overridden"] == ["eta_tt_est"]
    rules = {r["id"]: r for r in design.rules("compressor")}
    assert rules["COMP-12"]["tier"] == "L1"
    design.clear_overrides("compressor")
    design.run()
    assert "_provenance" in design.outputs("compressor") and not design.outputs("compressor")["_provenance"]
    assert abs(design.outputs("geometry")["mass_total_kg"] - base_mass) < 1e-9


def test_maps_and_offdesign_close(design):
    rep = design.analyze(["maps", "offdesign"], verbose=None)
    assert not rep.failed, rep.failed
    mp = design.outputs("maps")
    assert len(mp["compressor_map"]["lines"]) >= 6 and len(mp["turbine_map"]["lines"]) >= 6
    dp = mp["design_point"]
    assert dp["ok"] and 0.7 < dp["eta"] < 0.9
    cy = design.outputs("cycle")
    assert abs(dp["PR"] - cy["OPR"]) / cy["OPR"] < 0.12
    od = design.outputs("offdesign")
    conv = [p for p in od["running_line"] if p["converged"]]
    assert len(conv) >= 8
    # thrust rises monotonically with speed on the converged part above 60 %
    hi = [p for p in conv if p["N_frac"] >= 0.6]
    assert all(b["Fn"] > a["Fn"] for a, b in zip(hi, hi[1:]))
    assert 0.85 < od["max_point"]["Fn"] / 400.0 < 1.25
    # value-hash invalidation reaches the analysis stages
    design.set({"cycle.T04_K": 1120.0})
    assert "maps" in design.stale() and "offdesign" in design.stale()
    design.set({"cycle.T04_K": 1150.0})
    design.run()
    assert "maps" not in design.stale()


def test_control_schedules_move_the_running_line_and_plots_render(design):
    """Roadmap 1b / 4: bleed + nozzle schedules flow through matching; the unscheduled line is ghosted; the map renders."""
    from jetsuite2 import plots
    ctl = design.outputs("control")
    assert ctl["bleed_enabled"] is False and ctl["igv_settings"] == [0.0]
    design.set({"control.bleed_enabled": True, "control.nozzle_variable": True})
    rep = design.run()
    assert "control" in rep.ran and "maps" not in design.stale()          # bleed / nozzle do not change the map
    assert "offdesign" in design.stale()                                     # but they change the matching
    rep = design.analyze(["offdesign"], verbose=None)
    assert not rep.failed, rep.failed
    od = design.outputs("offdesign")
    assert od["schedules_enabled"] == {"bleed": True, "nozzle": True, "igv": False}
    low = [p for p in od["running_line"] if p["converged"] and p["N_frac"] <= 0.6]
    assert low and all(p["bleed"] > 0 for p in low)
    ghost = {round(p["N_frac"], 2): p for p in od["unscheduled_line"] if p["converged"]}
    assert ghost
    # bleed + open nozzle lower the running line: more surge margin at the lowest converged speed
    p0 = min(low, key=lambda p: p["N_frac"])
    g0 = ghost.get(round(p0["N_frac"], 2))
    assert g0 is not None and p0["SM"] > g0["SM"]
    w = plots.plot_all(design)
    for f in ("png", "svg", "html"):
        assert Path(w["compressor"][f]).exists()
    html = Path(w["compressor"]["html"]).read_text(encoding="utf-8")
    assert 'data-layer="ghost"' in html and 'data-layer="surge"' in html
    assert plots.plots_stale(design) == []
    design.set({"control.bleed_enabled": False, "control.nozzle_variable": False})
    design.run()
    assert "offdesign" in plots.plots_stale(design) or "offdesign" in design.stale()


def test_hot_start_T04_limiter_holds_at_low_speed(design):
    """Work package A: a rich start (accel line x2, ramp x4) that would exceed T04 without the limiter must be held
    at the limit through the whole start, including the sub-40 % speed region where the old limiter lost authority."""
    import copy
    from jetsuite2.perf import matching, transient as ptr
    E = matching.EngineModel.from_design(design)
    req = design.outputs("requirements")
    amb = matching.Ambient.at(req["altitude_m"], req["mach"], req["dT_isa_K"])
    sched = ptr.steady_schedule(E, amb, [0.4, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.05])
    sh = copy.deepcopy(E.sched); sh._acc = 1.0 + (sh._acc - 1.0) * 4.0; sh.start_ramp_rate *= 4.0
    E_hot = matching.EngineModel(**{**E.__dict__, "sched": sh})
    # limit set 100 K below the design T04 so the rich start (natural peak ~1220 K on this design) clearly exceeds it
    limit = 1100.0
    runs = {}
    for name, T04_limit in (("limited", limit), ("unlimited", 5000.0)):
        ctrl = ptr.controller_from_schedules(sh); ctrl.self_sustain_frac = 0.22; ctrl.T04_limit = T04_limit
        # lit engine at 30 % speed (the sub-idle region the old limiter lost authority in), rich acceleration to idle
        runs[name] = ptr.simulate(E_hot, amb, ctrl, sched, 0.30, sh.idle_N, t_end=10.0, dt=0.05, starter=False)
    T_lim, T_unl = np.array(runs["limited"]["hist"]["T04"]), np.array(runs["unlimited"]["hist"]["T04"])
    N_lim = np.array(runs["limited"]["hist"]["N_frac"])
    assert T_unl.max() > limit + 50.0, "the case must be one the limiter has to catch"
    assert T_lim.max() <= limit + 2.0, f"T04 limiter lost authority: peak {T_lim.max():.0f} K"
    # the limiter must have acted below 40 % speed (the regime the defect was in), not only near idle
    lim = np.array(runs["limited"]["hist"]["lim"])
    assert np.any((lim == 1) & (N_lim < 0.40)), "limiter never acted in the low-speed region"
    assert runs["limited"]["final_N_frac"] > 0.4, "the limited start must still reach idle"


def test_freeze_compare_and_gate(design, tmp_path):
    """Work package B: freeze is hash-verifiable and immutable, the gate refuses unfrozen designs, compare diffs two states."""
    from jetsuite2 import compare as cmp
    assert cmp.freeze_status(design)["frozen"] is False
    with pytest.raises(SystemExit):
        cmp.require_frozen(design, False, "CAD build")
    cmp.require_frozen(design, True, "CAD build")           # explicit override passes
    rec = cmp.freeze(design, by="tester", note="unit test")
    assert cmp.freeze_status(design)["frozen"] is True
    v = rec["version"]
    ver = cmp.verify_frozen(design, v)
    assert ver["ok"] and ver["file_hash_ok"] and ver["content_hash_ok"]
    assert (Path(design.dir) / "frozen" / f"v{v:04d}.sha256").exists()
    cmp.require_frozen(design, False, "export")               # no exception while frozen
    # any input change unfreezes
    design.set({"cycle.T04_K": 1160.0})
    design.run()
    st = cmp.freeze_status(design)
    assert st["frozen"] is False and "changed since freeze" in st["reason"]
    # tampering with the frozen file is detected
    snap = Path(design.dir) / "frozen" / f"v{v:04d}.json"
    import os, stat
    os.chmod(snap, stat.S_IWRITE | stat.S_IREAD)
    snap.write_text(snap.read_text(encoding="utf-8").replace('"by": "tester"', '"by": "someone"'), encoding="utf-8")
    assert cmp.verify_frozen(design, v)["ok"] is False
    # compare current vs frozen: the T04 input differs and the headline shows it
    doc_a, na = cmp.load_spec(f"{design.dir}@frozen")
    doc_b, nb = cmp.load_spec(str(design.dir))
    res = cmp.compare(doc_a, doc_b, na, nb)
    assert any(d["path"] == "inputs.cycle.T04_K" for d in res["inputs_diff"])
    t04 = next(h for h in res["headline"] if h["label"] == "T04 K")
    assert abs(t04["delta"] - 10.0) < 1e-6
    text = cmp.render(res)
    assert "## Surge margins" in text and "MAP-1" in text
    design.set({"cycle.T04_K": 1150.0})
    design.run()


def test_surge_band_terms_combine_by_rss_and_show_arithmetic():
    """Work packages C / D: named terms, RSS combination, dominant term named, with-band arithmetic explicit."""
    from jetsuite2 import uncertainty as unc
    from jetsuite2.perf import closs
    b0 = unc.surge_band()
    assert abs(b0["total"] - closs.SURGE_BAND_SM) < 1e-12 and len(b0["terms"]) == 1 and b0["rule"] == "RSS"
    b = unc.surge_band(igv=0.06, lowspeed=True, transient=True)
    assert abs(b["total"] - math.sqrt(closs.SURGE_BAND_SM ** 2 + 0.06 ** 2 + 0.03 ** 2 + 0.03 ** 2)) < 1e-12
    assert b["dominant"].startswith("rig") and len(b["terms"]) == 4
    r = unc.annotate_rule(dict(id="X", value=0.12, limit=0.05, kind="min", verdict="pass"), b)
    assert r["pass_with_band"] is (0.12 - b["total"] >= 0.05)
    assert f"{0.12 - b['total']:+.3f}" in r["band_statement"] and "dominant term" in r["band_statement"]
    # the IGV term is half the credited benefit and zero with the IGV open
    class FakeMap:
        def surge_margin(self, Nc, W, PR, igv=0.0):
            return 0.20 if igv else 0.05
    assert abs(unc.igv_term(FakeMap(), 0.5, 0.3, 1.4, 25.0) - 0.075) < 1e-12
    assert unc.igv_term(FakeMap(), 0.5, 0.3, 1.4, 0.0) == 0.0


def test_disc_fe_mesh_and_dat_parser(tmp_path):
    """Work package E: the structured axisymmetric mesh honours the profile and the .dat parser reads CalculiX stresses."""
    from jetsuite2.fea import disc
    # a stepped disc: rim 30-35 mm between x 10-20, web 8-30 mm between x 13-17, bore at 8 mm
    prof = [[0.010, 0.035], [0.020, 0.035], [0.020, 0.030], [0.017, 0.030], [0.017, 0.008], [0.013, 0.008], [0.013, 0.030], [0.010, 0.030]]
    mesh = disc.build_mesh(prof, cell_mm=1.0)
    assert mesh["n_elements"] > 100 and mesh["rim_faces"] and abs(mesh["rim_len"] - 0.010) < 1e-9
    assert abs(mesh["r_rim"] - 0.035) < 1e-12 and abs(mesh["r_min"] - 0.008) < 1e-12 and len(mesh["stub_nodes"]) == 1
    corners = disc.reentrant_corners(prof)
    assert len(corners) == 2 and all(abs(r - 0.030) < 1e-9 for r, x in corners)
    dat = tmp_path / "t.dat"
    dat.write_text("\n S T E P 1\n\n stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz) for set DISC and time  0.1000000E+01\n\n"
                   "         1   1  1.0E+07  2.0E+07  3.0E+08  0.0E+00  0.0E+00  0.0E+00\n"
                   "         2   1  0.0E+00  0.0E+00  1.0E+08  0.0E+00  0.0E+00  0.0E+00\n", encoding="utf-8")
    nodes = {1: (0.0, 0.0), 2: (0.001, 0.0), 3: (0.001, 0.001), 4: (0.0, 0.001), 5: (0.002, 0.0), 6: (0.002, 0.001)}
    elements = {1: (1, 2, 3, 4), 2: (2, 5, 6, 3)}
    # impeller-style load: the outer boundary of every x column inside the gas path carries the smeared blade pull
    mesh2 = disc.build_mesh(prof, cell_mm=1.0, load_x_range=(0.013, 0.017))
    assert mesh2["rim_faces"] and abs(mesh2["rim_len"] - 0.004) < 1e-9
    assert abs(mesh2["load_area"] - 2 * math.pi * 0.035 * 0.004) < 1e-9        # the rim (r 35 mm) is the outer boundary over that range
    steps = disc.parse_dat(dat, elements, nodes, corners=[(0.0005, 0.0005)], exclusion_m=0.0008)
    assert len(steps) == 1
    s = steps[0]
    assert abs(s["hoop_max_Pa"] - 3.0e8) < 1 and abs(s["hoop_mean_Pa"] - 2.0e8) < 1     # equal-area elements
    assert s["vm_max_away_Pa"] < s["vm_max_Pa"] and abs(s["vm_max_away_Pa"] - 1.0e8) < 1  # element 1 excluded as corner-adjacent


def test_igv_is_a_mechanical_object(design):
    """Work package C: enabling the IGV adds a vane row to the layout, parts and mass to the geometry sheet,
    actuation / failure-position rules to the control stage, and the row length to the engine length."""
    L0 = design.outputs("layout")["length_m"]; m0 = design.outputs("geometry")["mass_total_kg"]
    design.set({"control.igv_enabled": True})
    rep = design.run()
    assert {"layout", "geometry", "control"} <= set(rep.ran)
    lay = design.outputs("layout")["igv"]
    assert lay["fitted"] and lay["n_vanes"] >= 9 and lay["n_vanes"] % 2 == 1 and lay["L_m"] > 0
    assert design.outputs("layout")["length_m"] > L0 + lay["L_m"] * 0.9
    ge = design.outputs("geometry")
    assert "igv" in ge["sheet"] and ge["sheet"]["igv"]["n"] == lay["n_vanes"]
    assert all(k in ge["mass"] for k in ("igv_vanes", "igv_ring", "igv_hub_bullet", "igv_actuator"))
    assert ge["mass_total_kg"] > m0 + 0.05
    ctl = design.outputs("control")
    assert ctl["igv_fail_position"] == "open" and ctl["igv_fail_deg"] == 0.0 and ctl["igv_rate_required_deg_s"] > 0
    rules = {r["id"]: r for r in design.rules("control")}
    assert rules["CTL-8"]["verdict"] in ("pass", "warn") and rules["CTL-9"]["verdict"] == "pass"
    design.set({"control.igv_enabled": False})
    design.run()
    assert not design.outputs("layout")["igv"]["fitted"] and "igv" not in design.outputs("geometry")["sheet"]


def test_paper_engine_data_and_result_formatting():
    """ROADMAP 2: the paper-correlation data file is complete and sourced; absolute-tolerance rows print in K."""
    db = cases.load_paper_engines()
    assert len(db["engines"]) >= 3
    for e in db["engines"]:
        assert e["source_url"].startswith("http") and {"thrust_N", "OPR", "rpm"} <= set(e["design"])
        mx = next(p for p in e["points"] if p["name"] == "max")
        assert mx["thrust_N"] > 0 and mx["N_rpm"] > 0 and mx["EGT_K"] > 900
        assert e["published"]["diameter_mm"] > 0 and e["published"]["mass_kg"] > 0
    txt = cases.format_results([dict(case="x", quantity="EGT_K", model=1080.0, reference=1023.0, error=57.0, tolerance=60.0, source="s")])
    assert "err +57 K" in txt and "tol 60 K" in txt and "ok" in txt


def test_cold_flow_rig_definition(design):
    """ROADMAP 2: the rig definition is generated from the design's map with a run matrix per speed line."""
    from jetsuite2 import rig
    r = rig.define(design)
    assert r["drive"]["power_kW"] > r["design_point"]["P_compressor_kW"] * 1.2
    assert len(r["run_matrix"]) >= 6 and all(m["predicted"]["W_corr_choke"] > m["predicted"]["W_corr_surge"] for m in r["run_matrix"])
    assert all(m["predicted"]["surge_band_W_corr"][0] < m["predicted"]["W_corr_surge"] < m["predicted"]["surge_band_W_corr"][1] for m in r["run_matrix"])
    assert any(i["measurement"] == "mass flow" for i in r["instrumentation"])
    res = rig.write(design)
    assert (Path(res["dir"]) / "compressor_rig.md").exists() and (Path(res["dir"]) / "ingest_template.json").exists()
    assert "## Run matrix" in rig.render(r)


def test_thermal_network_predicts_temperatures_and_feeds_life(design):
    """ROADMAP 6: secondary air + thermal network + oil system; life consumes the predicted temperatures."""
    rep = design.analyze(["thermal"], verbose=None)
    assert not rep.failed, rep.failed
    th = design.outputs("thermal")
    T = th["temperatures"]
    assert 900.0 < T["T_rim_K"] < 1250.0 and T["T_bore_K"] < T["T_rim_K"] and T["T_web_K"] < T["T_rim_K"]
    assert 300.0 < T["T_bearing_rear_K"] < 600.0 and T["T_bearing_front_K"] <= T["T_bearing_rear_K"] + 50.0
    sa = th["secondary_air"]
    assert 0.0 < sa["leak_fraction"] < 0.05 and sa["T_cavity_turbine_K"] >= sa["T_cavity_back_K"]
    assert th["bearing_heat"]["Q_per_bearing_W"] > 0 and th["oil_system"]["oil_flow_l_h"] > 0
    assert th["abort"]["bearing_T_abort_K"] > T["T_bearing_rear_K"]
    rules = {r["id"]: r for r in design.rules("thermal")}
    assert {"THM-1", "THM-3", "THM-4", "THM-5", "THM-8"} <= set(rules) and rules["THM-1"]["tier"] == "L1"
    # life must now cite the thermal network, and be stale-linked to it
    rep = design.analyze(["life"], verbose=None)
    assert not rep.failed, rep.failed
    life_rules = {r["id"]: r for r in design.rules("life")}
    assert "thermal network" in life_rules["LIFE-4"]["source"]
    design.set({"thermal.seal_radial_clearance_mm": 0.25})
    assert "thermal" in design.stale() and "life" in design.stale()
    design.set({"thermal.seal_radial_clearance_mm": 0.15})
    design.analyze(["thermal", "life"], verbose=None)


def test_dashboard_and_steady_schedule_cache(design):
    """ROADMAP 8: off-design exports the steady schedule the transient / bench reuse; the dashboard is self-contained."""
    from jetsuite2 import dashboard
    rep = design.analyze(["maps", "offdesign"], force=True, verbose=None)
    assert not rep.failed, rep.failed
    od = design.outputs("offdesign")
    ss = od["steady_schedule"]
    assert len(ss["N"]) >= 6 and len(ss["x"]) == len(ss["N"]) and all(len(x) == 3 for x in ss["x"])
    assert all(b > a for a, b in zip(ss["N"], ss["N"][1:]))
    out = dashboard.write(design)
    txt = Path(out).read_text(encoding="utf-8")
    assert "<title>" in txt and "data:image/png;base64," in txt and "MAP-1" in txt and "<h2>Stages</h2>" in txt
    assert "http" not in txt.split("<body>")[1][:200]   # no external resources


def test_throughflow_checks_the_blade_shape(design):
    """ROADMAP 7: meridional through-flow on the CAD's own channel and camber law; loading and incidence diagrams."""
    from jetsuite2.stages import throughflow as tf
    # the blade-angle law is the CAD's: quadratic hub-rms-shroud inlet angle, smooth-step ease to the backsweep
    assert abs(tf.blade_angle(0.0, 0.5, 30.0, 50.0, 58.0, 30.0) - 50.0) < 1e-12
    assert abs(tf.blade_angle(1.0, 0.0, 30.0, 50.0, 58.0, 30.0) - 30.0) < 1e-12
    assert abs(tf.blade_angle(0.5, 1.0, 30.0, 50.0, 58.0, 30.0) - 44.0) < 1e-12       # 58 + (30 - 58) * 0.5
    rep = design.analyze(["throughflow"], verbose=None)
    assert not rep.failed, rep.failed
    o = design.outputs("throughflow")
    assert len(o["incidence_deg"]["all"]) == o["n_span"] and -15 < o["incidence_deg"]["mid"] < 15
    for k in ("hub", "mid", "shroud"):
        s = o["streamlines"][k]
        assert len(s["W"]) == o["n_chord"] and all(w > 0 for w in s["W"]) and all(a >= b for a, b in zip(s["W_ss"], s["W_ps"]))
    cm2 = design.outputs("compressor")["Cm2_m_s"]
    assert 0.6 * cm2 < o["exit"]["Cm_hub"] < 1.6 * cm2
    assert 0.8 < o["exit"]["Ct_mean"] / o["exit"]["Ct_meanline"] < 1.1
    rules = {r["id"]: r for r in design.rules("throughflow")}
    assert {"TF-1", "TF-2", "TF-3", "TF-4", "TF-5"} <= set(rules) and rules["TF-1"]["verdict"] in ("pass", "warn", "fail")
    assert Path(o["plots"]["throughflow"]).exists()


def test_ecu_export_and_sensor_loss_fallback(design):
    """ROADMAP 10: the controller exports as tables + logic; the integrator's P3-sensor-loss fallback runs the N-only schedule."""
    from jetsuite2 import ecu
    from jetsuite2.perf import matching, transient as ptr
    if not design.outputs("offdesign").get("steady_schedule"):
        rep = design.analyze(["maps", "offdesign"], force=True, verbose=None)
        assert not rep.failed, rep.failed
    res = ecu.export(design)
    d = Path(res["dir"])
    assert all((d / f).exists() for f in res["files"]) and res["rows"] >= 10
    t = ecu.tables(design)
    lim = t["limits"]
    assert lim["N_max_frac"] > lim["idle_N_frac"] and lim["EGT_limit_K"] < lim["T04_limit_K"] and "ABORT" in ecu.logic_md(t)
    rows = t["schedules"]
    assert all(r["accel_mult"] > r["decel_mult"] for r in rows) and any(r["WfP3_steady_kg_s_per_Pa"] for r in rows)
    # the fallback: with the P3 sensor lost the commanded fuel follows the scheduled P3(N); run must still accelerate
    E = matching.EngineModel.from_design(design)
    req = design.outputs("requirements")
    amb = matching.Ambient.at(req["altitude_m"], req["mach"], req["dT_isa_K"])
    sched = design.outputs("offdesign")["steady_schedule"]
    ctrl = ptr.controller_from_schedules(E.sched); ctrl.self_sustain_frac = 0.22
    r = ptr.simulate(E, amb, ctrl, sched, ctrl.idle_frac, 0.9, t_end=6.0, dt=0.05, p3_sensor_lost=True, accel_derate=0.8)
    assert r["final_N_frac"] > ctrl.idle_frac + 0.1 and max(r["hist"]["T04"]) <= ctrl.T04_limit + 2.0


def test_drawings_with_fits(design):
    """ROADMAP 9: shaft / housing / casing drawings with ISO fits from the geometry sheet."""
    from jetsuite2 import drawings
    assert drawings.iso(drawings.ISO_SHAFT, "k5", 15.0) == (1, 9) and drawings.iso(drawings.ISO_HOLE, "H6", 28.0) == (0, 13)
    res = drawings.write(design)
    for f in ("shaft.svg", "housings.svg", "casing.svg", "drawings.md"):
        assert Path(res["dir"], f).exists()
    seats = next(r for r in res["tables"]["shaft"] if r["feature"].startswith("bearing seats"))
    bores = next(r for r in res["tables"]["housings"] if r["feature"].startswith("bearing bores"))
    assert seats["fit"] == "k5" and bores["fit"] == "H6" and seats["deviation_um"][0] > 0 >= bores["deviation_um"][0]
    md = Path(res["dir"], "drawings.md").read_text(encoding="utf-8")
    assert "| bearing seats" in md and "ISO 286" in md


def test_sweep_study_runs_and_flags_stale(design):
    res = studies.run_study(design, "sweep", "opr_sweep", {"variables": {"cycle.OPR": [3.5, 4.0]}, "objectives": {"mass_kg": "outputs.geometry.mass_total_kg", "TSFC": "outputs.cycle.TSFC_kg_per_N_h"}})
    assert len(res["rows"]) == 2 and all(not r["failed"] for r in res["rows"])
    assert res["rows"][1]["TSFC"] < res["rows"][0]["TSFC"]      # higher OPR -> lower TSFC
    lst = {s["name"]: s for s in studies.list_studies(design)}
    assert lst["opr_sweep"]["stale"] is False
    design.set({"requirements.thrust_N": 420.0})
    lst = {s["name"]: s for s in studies.list_studies(design)}
    assert lst["opr_sweep"]["stale"] is True
    design.set({"requirements.thrust_N": 400.0})


def test_uq_and_sensitivity_small(design):
    res = studies.run_study(design, "uq", "uq_small", {"n": 6, "objectives": {"mass_kg": "outputs.geometry.mass_total_kg", "TSFC": "outputs.cycle.TSFC_kg_per_N_h"}})
    assert res["stats"]["TSFC"]["p95"] >= res["stats"]["TSFC"]["p05"]
    res = studies.run_study(design, "sensitivity", "sens_small",
                            {"variables": {"cycle.OPR": [3.6, 4.4], "cycle.T04_K": [1100, 1200]}, "trajectories": 2,
                             "objectives": {"TSFC": "outputs.cycle.TSFC_kg_per_N_h"}})
    assert res["ranking"]["TSFC"][0]["variable"] in ("cycle.OPR", "cycle.T04_K")


def test_optimizer_produces_feasible_pareto_points(design):
    res = studies.run_study(design, "optimize", "opt_small",
                            {"variables": {"cycle.OPR": [3.3, 4.5], "compressor.backsweep_deg": [20.0, 40.0]},
                             "objectives": {"mass_kg": "min", "TSFC": "min"}, "pop": 6, "generations": 2})
    assert res["pareto"] and any(p["feasible"] for p in res["pareto"])


def test_hmesh_periodic_faces_match_under_one_pitch(design, tmp_path):
    from jetsuite2.cfd import hmesh
    info = hmesh.build(design, tmp_path, ni_blade=16, ni_in=4, ni_out=5, nj=8, nk=6)
    assert info["n_hexes"] > 0 and info["markers"]["PER_A"] == info["markers"]["PER_B"] > 0
    lines = Path(info["su2"]).read_text().splitlines()
    npoin = int(next(l for l in lines if l.startswith("NPOIN=")).split("=")[1])
    i0 = lines.index(next(l for l in lines if l.startswith("NPOIN="))) + 1
    pts = np.array([[float(v) for v in l.split()[:3]] for l in lines[i0:i0 + npoin]])
    def marker_nodes(tag):
        k = lines.index(f"MARKER_TAG= {tag}")
        n = int(lines[k + 1].split("=")[1])
        return sorted({int(v) for l in lines[k + 2:k + 2 + n] for v in l.split()[1:]})
    A, B = pts[marker_nodes("PER_A")], pts[marker_nodes("PER_B")]
    th = math.radians(info["pitch_deg"])
    rot = np.c_[A[:, 0], A[:, 1] * math.cos(th) - A[:, 2] * math.sin(th), A[:, 1] * math.sin(th) + A[:, 2] * math.cos(th)]
    d = np.sqrt(((rot[:, None, :] - B[None, :, :]) ** 2).sum(-1)).min(1)
    assert len(A) == len(B) and d.max() < 1e-9   # metres: every PER_A node lands on a PER_B node
    # hexes: positive volume for the first cell (orientation check the writer performs on every block)
    nel = int(next(l for l in lines if l.startswith("NELEM=")).split("=")[1])
    assert nel == info["n_hexes"]


def test_hmesh_initial_field_is_consistent(design, tmp_path):
    """The streamline-aligned start field: design passage mass flow at the inlet plane, no swirl upstream of the LE,
    swirl in the wheel's sense at the TE, SST columns for a RANS start."""
    from jetsuite2.cfd import hmesh
    info = hmesh.build(design, tmp_path, ni_blade=16, ni_in=4, ni_out=5, nj=8, nk=6, rans=True)
    z = np.load(tmp_path / "passage_ids.npz"); id1 = z["id1"]
    rows = (tmp_path / "passage_init.csv").read_text().splitlines()
    assert rows[0].endswith('"Turb_Kin_Energy","Omega"')
    d = np.array([[float(v) for v in r.split(",")] for r in rows[1:]]); d = d[np.argsort(d[:, 0])]
    X, rho, mom = d[:, 1:4], d[:, 4], d[:, 5:8]
    r = np.hypot(X[:, 1], X[:, 2]); vt = (mom[:, 2] * X[:, 1] - mom[:, 1] * X[:, 2]) / (rho * r)
    o = design.outputs(); W_pass = o["cycle"]["W_kg_s"] / o["geometry"]["sheet"]["impeller"]["n_main"]
    NI, NJ, NK = id1.shape
    F = 0.0
    for j in range(NJ - 1):
        for k in range(NK - 1):
            q = [id1[0, j, k], id1[0, j + 1, k], id1[0, j + 1, k + 1], id1[0, j, k + 1]]
            pts = X[q]; n = 0.5 * np.cross(pts[2] - pts[0], pts[3] - pts[1]); F += np.dot(mom[q].mean(0), n)
    assert abs(abs(F) * 2 - W_pass) < 0.25 * W_pass       # block 1 is half the passage
    assert abs(vt[id1[0].ravel()]).max() < 1e-6            # no swirl at the inlet plane
    sense = info["rotation_sense"]
    assert np.sign(vt[id1[int(z["i_te"]), NJ // 2, NK // 2]]) == np.sign(sense)   # swirl with the wheel at the TE
    assert (d[:, 9] > 0).all() and (d[:, 10] > 0).all()   # rho k, rho omega positive
