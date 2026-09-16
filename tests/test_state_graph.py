"""Value-hash invalidation: the property the whole suite rests on."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jetsuite2.api import Design  # noqa: E402
from jetsuite2.stages import ORDER  # noqa: E402
from jetsuite2.state.store import canonical_hash  # noqa: E402


def make(tmp_path, **over):
    d = Design.create(tmp_path / "d", "t", over)
    rep = d.run()
    assert not rep.failed, rep.failed
    assert rep.ran == ORDER
    return d


def test_second_run_skips_everything(tmp_path):
    d = make(tmp_path)
    rep = d.run()
    assert rep.ran == [] and rep.skipped == ORDER


def test_canonical_hash_insensitive_to_order_and_rounding():
    a = {"x": 1.0000000000001, "y": [1, 2], "z": {"p": 1, "q": 2}}
    b = {"z": {"q": 2, "p": 1}, "y": [1, 2], "x": 1.0}
    assert canonical_hash(a) == canonical_hash(b)
    assert canonical_hash(a) != canonical_hash({**a, "x": 1.001})


def test_material_change_reruns_only_affected_stages(tmp_path):
    d = make(tmp_path)
    res = d.set({"compressor.material": "Al2618-T61"})
    stale = res["stale"]
    assert "speed" in stale and "compressor" in stale and "geometry" in stale
    assert "cycle" not in stale and "requirements" not in stale
    # turbine is downstream of speed, so it is listed as potentially stale; the value hash skips it at run time
    rep = d.run()
    assert "cycle" in rep.skipped and "turbine" in rep.skipped and "combustor" in rep.skipped
    assert "compressor" in rep.ran and "mechanical" in rep.ran
    assert d.outputs("compressor")["material"] == "Al2618-T61"


def test_no_op_change_does_not_invalidate(tmp_path):
    d = make(tmp_path)
    v = d.store.version
    res = d.set({"cycle.OPR": 4.0})   # same as default
    assert res["stale"] == {}
    rep = d.run()
    assert rep.ran == []
    assert d.store.version == v + 1  # the set itself is versioned


def test_versions_diff_and_checkout(tmp_path):
    d = make(tmp_path)
    v_before = d.store.version
    d.set({"cycle.OPR": 3.5})
    d.run()
    rows = d.diff(v_before)
    paths = {p for p, _, _ in rows}
    assert "inputs.cycle.OPR" in paths and "outputs.cycle.W_kg_s" in paths
    d.store.checkout(v_before)
    d.load()
    assert d.doc["inputs"]["cycle"]["OPR"] == 4.0
    assert d.run().ran == []   # restored outputs match restored inputs


def test_rules_have_sources_and_verdicts(tmp_path):
    d = make(tmp_path)
    rules = d.rules()
    assert len(rules) > 40
    for r in rules:
        assert r["verdict"] in ("pass", "warn", "fail", "info")
        assert r["source"]
