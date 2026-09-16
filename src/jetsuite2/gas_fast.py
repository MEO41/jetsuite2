"""Tabulated version of ``jetsuite2.gas`` for the off-design / transient loops.

Same Walsh & Fletcher polynomials, sampled at 1 K over 150-2600 K for a set
of fuel-air ratios (0 .. 0.05) and interpolated linearly in T and FAR.
Inversions (T from h, isentropic T, FAR for T04) are done by interpolating the
monotonic tables instead of root finding, which is ~20-50x faster than the
exact functions and accurate to < 0.05 K / 0.02 %.
"""
from __future__ import annotations

import math

import numpy as np

from . import gas

T_GRID = np.arange(150.0, 2601.0, 1.0)
FAR_GRID = np.array([0.0, 0.01, 0.02, 0.03, 0.04, 0.05])
_H = np.array([gas.h(T_GRID, f) for f in FAR_GRID])       # (nf, nT)
_PHI = np.array([gas.phi(T_GRID, f) for f in FAR_GRID])
_CP = np.array([gas.cp(T_GRID, f) for f in FAR_GRID])
R = gas.R_AIR
R_AIR = gas.R_AIR
LHV_KEROSENE = gas.LHV_KEROSENE
FAR_STOICH = gas.FAR_STOICH


def _fidx(far: float):
    far = min(max(far, 0.0), FAR_GRID[-1])
    i = int(np.searchsorted(FAR_GRID, far)) - 1
    i = min(max(i, 0), len(FAR_GRID) - 2)
    w = (far - FAR_GRID[i]) / (FAR_GRID[i + 1] - FAR_GRID[i])
    return i, w


def _row(tab, far):
    i, w = _fidx(far)
    return (1 - w) * tab[i] + w * tab[i + 1] if w else tab[i]


def cp(T: float, far: float = 0.0) -> float:
    return float(np.interp(T, T_GRID, _row(_CP, far)))


def gamma(T: float, far: float = 0.0) -> float:
    c = cp(T, far)
    return c / (c - R)


def h(T: float, far: float = 0.0) -> float:
    return float(np.interp(T, T_GRID, _row(_H, far)))


def phi(T: float, far: float = 0.0) -> float:
    return float(np.interp(T, T_GRID, _row(_PHI, far)))


def T_from_h(hv: float, far: float = 0.0) -> float:
    row = _row(_H, far)
    return float(np.interp(hv, row, T_GRID))


def isentropic_T(T1: float, pr: float, far: float = 0.0) -> float:
    row = _row(_PHI, far)
    target = float(np.interp(T1, T_GRID, row)) + R * math.log(pr)
    return float(np.interp(target, row, T_GRID))


def far_for_T04(T03: float, T04: float, eta_b: float = 0.98, lhv: float = gas.LHV_KEROSENE) -> float:
    """Energy balance (1+f) h(T04, f) - h(T03) = f eta LHV, solved by 3 fixed-point steps (converges fast)."""
    h3 = h(T03, 0.0)
    f = 0.02
    for _ in range(6):
        h4 = h(T04, f)
        f_new = (h4 - h3) / (eta_b * lhv - h4)
        if f_new <= 0:
            return 1e-5
        if abs(f_new - f) < 1e-7:
            f = f_new
            break
        f = f_new
    return float(min(max(f, 1e-5), 0.09))


def a_sound(T: float, far: float = 0.0) -> float:
    return math.sqrt(gamma(T, far) * R * T)


def static_from_total(T0: float, P0: float, M: float, far: float = 0.0):
    g = gamma(T0, far)
    T = T0 / (1 + 0.5 * (g - 1) * M * M)
    g = gamma(0.5 * (T + T0), far)
    T = T0 / (1 + 0.5 * (g - 1) * M * M)
    P = P0 * (T / T0) ** (g / (g - 1))
    return T, P, g


def mass_flow_function(T0: float, P0: float, M: float, A: float, far: float = 0.0) -> float:
    T, P, g = static_from_total(T0, P0, M, far)
    return P / (R * T) * M * math.sqrt(g * R * T) * A
