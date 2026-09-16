"""The chain must close for any thrust in the brief's range with sane numbers."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jetsuite2.api import Design  # noqa: E402
from jetsuite2.stages import ORDER  # noqa: E402


@pytest.mark.parametrize("thrust", [100.0, 250.0, 500.0, 750.0, 1000.0])
def test_thrust_sweep_closes(tmp_path, thrust):
    d = Design.create(tmp_path / f"d{int(thrust)}", "sweep", {"requirements.thrust_N": thrust})
    rep = d.run()
    assert not rep.failed, rep.failed
    o = d.outputs()
    W = o["cycle"]["W_kg_s"]
    assert 0.6 * thrust / 600 < W < 1.4 * thrust / 500     # SLS specific thrust ~500-600 N/(kg/s)
    assert 0.09 < o["cycle"]["TSFC_kg_per_N_h"] < 0.16
    assert 30_000 < o["speed"]["rpm"] < 200_000
    D2 = o["compressor"]["D2_m"]
    assert 0.04 < D2 < 0.25
    assert 0.5 < o["turbine"]["hub_tip_ratio_exit"] < 0.9
    assert o["rotor"]["bearing_id"]
    assert o["geometry"]["mass_total_kg"] > 0
    # no hard failures other than the consistency rules (which `converge` resolves)
    fails = [r["id"] for r in d.rules() if r["verdict"] == "fail" and r["id"] not in ("COMP-12", "TURB-10")]
    assert fails == [], fails


def test_converge_brings_estimates_and_assumptions_together(tmp_path):
    d = Design.create(tmp_path / "c", "c", {"requirements.thrust_N": 300.0, "cycle.eta_c": 0.72, "cycle.eta_t": 0.80})
    d.run()
    hist = d.converge(tol=0.005)
    last = hist[-1]
    assert abs(last["eta_c_assumed"] - last["eta_c_estimate"]) < 0.006
    assert abs(last["eta_t_assumed"] - last["eta_t_estimate"]) < 0.006


def test_reference_engine_matches_boomsonic_v0_within_tolerance(tmp_path):
    """boomsonic_v0 frozen design: 500 N at M 1.02 / 5 km, OPR 4, T04 1150 K, 75 krpm, 15 deg backsweep,
    fielded efficiencies 0.70 / 0.75 -> W 1.326 kg/s, r2 66.9 mm, r1s 49.65 mm, turbine tip 61.1 mm."""
    d = Design.create(tmp_path / "ref", "ref", {
        "requirements.thrust_N": 500.0, "requirements.altitude_m": 5000.0, "requirements.mach": 1.02,
        "cycle.OPR": 4.0, "cycle.T04_K": 1150.0, "cycle.eta_c": 0.70, "cycle.eta_t": 0.75, "cycle.eta_b": 0.95,
        "cycle.intake_recovery": 0.97, "cycle.bleed_frac": 0.0, "cycle.power_offtake_W": 0.0, "cycle.dp_jetpipe": 0.0,
        "speed.rpm": 75000.0, "compressor.backsweep_deg": 15.0, "compressor.n_main": 12, "compressor.n_splitter": 12,
        "compressor.splitter_length_frac": 0.5, "compressor.diffuser_radius_ratio": 1.35})
    rep = d.run()
    assert not rep.failed, rep.failed
    o = d.outputs()
    assert abs(o["cycle"]["W_kg_s"] - 1.326) / 1.326 < 0.03
    assert abs(o["compressor"]["r2_m"] - 0.0669) / 0.0669 < 0.05
    assert abs(o["compressor"]["r1s_m"] - 0.04965) / 0.04965 < 0.05
    assert abs(o["cycle"]["turbine_PR_tt"] - 2.60) / 2.60 < 0.03
