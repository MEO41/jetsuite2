"""Gas properties for air and kerosene combustion products.

Polynomial cp(T) after Walsh & Fletcher, *Gas Turbine Performance* (2nd ed.),
Chart 3.x / eqs. F3.23-F3.26: dry air plus a fuel-air-ratio correction for
kerosene products.  Valid 200-2000 K.  Enthalpy and the entropy function are
integrated analytically from the same polynomial so h, phi and cp are
mutually consistent.

All quantities in SI (J/kg/K, J/kg, K, Pa).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

R_AIR = 287.05  # J/kg/K, dry air
# Products of kerosene combustion: molar mass barely changes for FAR < 0.03;
# W&F treat R as constant to within 0.1 %.
LHV_KEROSENE = 43.124e6  # J/kg, Jet-A / kerosene (W&F, Table)
FAR_STOICH = 0.0683      # kerosene

# Walsh & Fletcher dry-air coefficients (cp in kJ/kg/K, TZ = T/1000)
_A = np.array([0.992313, 0.236688, -1.852148, 6.083152, -8.893933,
               7.097112, -3.234725, 0.794571, -0.081873])
# Kerosene products correction (multiplied by FAR/(1+FAR))
_B = np.array([-0.718874, 8.747481, -15.863157, 17.254096, -10.233795,
               3.081778, -0.361112, -0.003919])


def cp(T, far: float = 0.0):
    """Specific heat at constant pressure [J/kg/K] for air + kerosene products."""
    tz = np.asarray(T, dtype=float) / 1000.0
    c = np.polyval(_A[::-1], tz)
    if far:
        c = c + far / (1.0 + far) * np.polyval(_B[::-1], tz)
    return c * 1000.0


def _int_poly(coef):
    """Coefficients of the antiderivative of sum(coef[i] * x^i)."""
    return np.concatenate([[0.0], coef / np.arange(1, len(coef) + 1)])


_IA = _int_poly(_A)
_IB = _int_poly(_B)


def h(T, far: float = 0.0):
    """Specific enthalpy [J/kg] relative to 0 K datum of the same polynomial."""
    tz = np.asarray(T, dtype=float) / 1000.0
    v = np.polyval(_IA[::-1], tz)
    if far:
        v = v + far / (1.0 + far) * np.polyval(_IB[::-1], tz)
    return v * 1000.0 * 1000.0  # kJ/kg * (T/1000 scaling) -> J/kg


def phi(T, far: float = 0.0):
    """Entropy function phi(T) = int cp/T dT [J/kg/K] (datum at 200 K)."""
    # int (a0 + a1 tz + ...)/tz dtz = a0 ln tz + a1 tz + a2 tz^2/2 + ...
    tz = np.asarray(T, dtype=float) / 1000.0
    tz0 = 0.2

    def _phi(coef, t):
        return coef[0] * np.log(t) + np.polyval(_int_poly(coef[1:])[::-1], t)

    v = _phi(_A, tz) - _phi(_A, tz0)
    if far:
        v = v + far / (1.0 + far) * (_phi(_B, tz) - _phi(_B, tz0))
    return v * 1000.0


def gamma(T, far: float = 0.0):
    c = cp(T, far)
    return c / (c - R_AIR)


def T_from_h(h_target: float, far: float = 0.0, lo: float = 150.0, hi: float = 2500.0) -> float:
    return brentq(lambda T: h(T, far) - h_target, lo, hi, xtol=1e-6)


def isentropic_T(T1: float, pr: float, far: float = 0.0) -> float:
    """Temperature after an isentropic pressure change by ratio pr (P2/P1)."""
    target = phi(T1, far) + R_AIR * math.log(pr)
    return brentq(lambda T: phi(T, far) - target, 100.0, 3000.0, xtol=1e-6)


def a_sound(T: float, far: float = 0.0) -> float:
    return math.sqrt(gamma(T, far) * R_AIR * T)


def static_from_total(T0: float, P0: float, M: float, far: float = 0.0):
    """Static T, P from total conditions and Mach (gamma evaluated at static T, iterated)."""
    T = T0
    for _ in range(20):
        g = float(gamma(T, far))
        Tn = T0 / (1 + 0.5 * (g - 1) * M * M)
        if abs(Tn - T) < 1e-6:
            T = Tn
            break
        T = Tn
    g = float(gamma(T, far))
    P = P0 * (T / T0) ** (g / (g - 1))
    return T, P, g


def mass_flow_function(T0: float, P0: float, M: float, A: float, far: float = 0.0) -> float:
    """Mass flow through area A at total T0, P0 and Mach M."""
    T, P, g = static_from_total(T0, P0, M, far)
    rho = P / (R_AIR * T)
    V = M * math.sqrt(g * R_AIR * T)
    return rho * V * A


def mach_from_area(W: float, T0: float, P0: float, A: float, far: float = 0.0, subsonic: bool = True) -> float:
    """Subsonic (or supersonic) Mach for mass flow W through area A. Raises if choked."""
    Wmax = mass_flow_function(T0, P0, 1.0, A, far)
    if W > Wmax * (1 + 1e-9):
        raise ValueError(f"choked: W={W:.4f} > Wchoke={Wmax:.4f} kg/s for A={A*1e4:.2f} cm2")
    lo, hi = (1e-4, 1.0) if subsonic else (1.0, 4.0)
    return brentq(lambda M: mass_flow_function(T0, P0, M, A, far) - W, lo, hi, xtol=1e-8)


def far_for_T04(T03: float, T04: float, eta_b: float = 0.98, lhv: float = LHV_KEROSENE,
                T_fuel: float = 298.15) -> float:
    """Fuel-air ratio for combustor exit T04 from inlet T03 (energy balance on products)."""
    # (1+f) h(T04, f) - h(T03, 0) = f * eta_b * LHV   (fuel sensible enthalpy neglected)
    def res(f):
        return (1 + f) * h(T04, f) - h(T03, 0.0) - f * eta_b * lhv
    return brentq(res, 1e-5, 0.09, xtol=1e-9)
