import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jetsuite2 import gas  # noqa: E402


def test_cp_air_reference_points():
    # NIST / Walsh & Fletcher: 1003-1005 at 288 K, ~1141 at 1000 K, ~1211 at 1500 K
    assert abs(gas.cp(288.15) - 1004) < 3
    assert abs(gas.cp(1000.0) - 1141) < 4
    assert abs(gas.cp(1500.0) - 1211) < 5


def test_products_cp_above_air():
    assert gas.cp(1150.0, 0.02) > gas.cp(1150.0) + 20


def test_enthalpy_consistent_with_cp():
    h1 = gas.h(600.0) - gas.h(300.0)
    # trapezoid integral of cp
    T = [300 + i for i in range(301)]
    cps = [float(gas.cp(t)) for t in T]
    integral = sum(0.5 * (cps[i] + cps[i + 1]) for i in range(300))
    assert abs(h1 - integral) / integral < 1e-4


def test_isentropic_matches_ideal_gas_at_low_temperature():
    T2 = gas.isentropic_T(288.15, 2.0)
    T2_ideal = 288.15 * 2.0 ** (0.4 / 1.4)
    assert abs(T2 - T2_ideal) / T2_ideal < 0.004   # gamma drops slightly with T


def test_far_for_T04_energy_balance():
    f = gas.far_for_T04(500.0, 1150.0, 1.0)
    assert 0.016 < f < 0.020
    lhs = (1 + f) * gas.h(1150.0, f) - gas.h(500.0)
    assert abs(lhs - f * gas.LHV_KEROSENE) / (f * gas.LHV_KEROSENE) < 1e-6


def test_choked_mass_flow_function():
    A = 1e-3
    W = gas.mass_flow_function(1000.0, 2e5, 1.0, A)
    # ideal gas gamma ~1.336 at 1000 K: W* = A P0 sqrt(g/(R T0)) (2/(g+1))^((g+1)/(2(g-1)))
    g = float(gas.gamma(1000.0 / (1 + 0.5 * (1.336 - 1))))
    Wref = A * 2e5 * math.sqrt(g / (287.05 * 1000.0)) * (2 / (g + 1)) ** ((g + 1) / (2 * (g - 1)))
    assert abs(W - Wref) / Wref < 0.01
