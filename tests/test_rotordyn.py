import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jetsuite2.rotordyn import RotorModel  # noqa: E402


def uniform_beam(n=30, L=0.3, d=0.02, E=205e9, rho=7850.0):
    x = np.linspace(0, L, n + 1)
    I = math.pi / 64 * d ** 4
    A = math.pi / 4 * d ** 2
    return x, [E * I] * n, [rho * A] * n, I, A


def test_simply_supported_beam_matches_closed_form():
    x, EI, rhoA, I, A = uniform_beam()
    L, E, rho = x[-1], 205e9, 7850.0
    k_big = 1e12
    m = RotorModel(x, EI, rhoA, masses={}, Id={}, Ip={}, springs={0: k_big, len(x) - 1: k_big})
    w = m.static_frequencies(3)
    w1_exact = math.pi ** 2 * math.sqrt(E * I / (rho * A * L ** 4))
    assert abs(w[0] - w1_exact) / w1_exact < 2e-3
    w2_exact = 4 * w1_exact
    assert abs(w[1] - w2_exact) / w2_exact < 5e-3


def test_gyroscopic_forward_branch_stiffens():
    # rigid disc (Ip = 2 Id) overhung on a stiff short shaft: forward conical mode rises with spin
    x, EI, rhoA, I, A = uniform_beam(n=10, L=0.1, d=0.02)
    n = len(x) - 1
    Id, Ip = 2e-4, 4e-4
    m = RotorModel(x, EI, [1e-3] * n, masses={n: 0.5}, Id={n: Id}, Ip={n: Ip}, springs={0: 1e9, 2: 1e9})
    w0 = [f for f, fw, fr in m.whirl(1.0)]
    modes_hi = m.whirl(3000.0)
    fwd = [f for f, fw, fr in modes_hi if fw]
    bwd = [f for f, fw, fr in modes_hi if not fw]
    # lowest forward frequency above the lowest static; lowest backward below it
    assert min(fwd) > w0[0] * 1.02
    assert min(bwd) < w0[0] * 0.98


def test_critical_speed_found_for_jeffcott_like_rotor():
    # symmetric mass at mid-span, no gyroscopics: critical = static natural frequency
    x, EI, rhoA, I, A = uniform_beam(n=20, L=0.2, d=0.015)
    mid = 10
    m = RotorModel(x, EI, rhoA, masses={mid: 0.8}, Id={mid: 1e-5}, Ip={mid: 2e-5}, springs={0: 1e9, 20: 1e9})
    w_static = m.static_frequencies(1)[0]
    crits = m.critical_speeds(omega_max=2.0 * w_static, n_scan=40)
    assert crits, "no critical found"
    assert abs(crits[0][0] - w_static) / w_static < 0.03
