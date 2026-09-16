import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jetsuite2.library import components, materials  # noqa: E402
from jetsuite2 import geomlib  # noqa: E402


def test_bearing_selection_respects_dn_and_temperature():
    b = components.select_bearing(rpm=80_000, min_bore=12.0, T_bearing=420.0, hybrid=True)
    assert b["bore"] >= 12 and b["bore"] * 80_000 <= b["dn_limit"] and b["T_max"] >= 420
    with pytest.raises(ValueError):
        components.select_bearing(rpm=400_000, min_bore=20.0)


def test_retaining_ring_and_locknut_lookup():
    r = components.retaining_ring(12.0, "external")
    assert r["d"] == 12 and r["d2"] < 12
    n = components.locknut(15.0)
    assert n["d"] >= 15


def test_material_allowables_monotonic_in_temperature():
    assert materials.yield_at("Ti-6Al-4V", 300) > materials.yield_at("Ti-6Al-4V", 600)
    assert materials.allowable_at("IN713LC", 1100) < materials.yield_at("IN713LC", 1100)   # creep-limited
    assert materials.creep_allowable_at("IN713LC", 750) is None


def test_extension_directory_overrides(tmp_path, monkeypatch):
    (tmp_path / "bearings_extra.json").write_text(
        '{"items": [{"id": "7001C-HC", "type": "angular_contact", "bore": 12, "od": 28, "width": 8, "n_balls": 11, "ball_d": 4.0, '
        '"C": 4.9, "C0": 2.4, "n_lim_grease": 1, "n_lim_oil": 1, "dn_limit": 9e6, "hybrid": true, "T_max": 600, "mass_g": 20}]}',
        encoding="utf-8")
    monkeypatch.setenv("JETSUITE2_LIBRARY", str(tmp_path))
    components.catalogue.cache_clear()
    try:
        b = components.by_id("bearings", "7001C-HC")
        assert b["dn_limit"] == 9e6 and b["T_max"] == 600
    finally:
        components.catalogue.cache_clear()


def test_revolved_volume_and_inertia_of_a_cylinder():
    R, L, rho = 0.05, 0.1, 8000.0
    prof = [(0.0, 0.0), (0.0, R), (L, R), (L, 0.0)]
    import math
    V = geomlib.revolved_volume(prof)
    assert abs(V - math.pi * R ** 2 * L) / V < 1e-9
    m, ip, id_, xcg = geomlib.revolved_inertia(prof, rho)
    assert abs(m - rho * V) / m < 1e-6
    assert abs(ip - 0.5 * m * R ** 2) / ip < 1e-4
    id_exact = m * (3 * R ** 2 + L ** 2) / 12
    assert abs(id_ - id_exact) / id_exact < 1e-3
    assert abs(xcg - L / 2) < 1e-9
