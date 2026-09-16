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
