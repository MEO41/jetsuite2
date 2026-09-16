"""Helpers shared by the stage modules."""
from __future__ import annotations

import math

from ..state.store import get_path

G0 = 9.80665


def isa(altitude_m: float, dT: float = 0.0) -> tuple[float, float, float]:
    """ISA static temperature [K], pressure [Pa], density [kg/m3] up to 20 km."""
    if altitude_m <= 11000.0:
        T = 288.15 - 0.0065 * altitude_m
        P = 101325.0 * (T / 288.15) ** 5.25588
    else:
        T = 216.65
        P = 22632.06 * math.exp(-G0 * (altitude_m - 11000.0) / (287.05 * T))
    T += dT
    rho = P / (287.05 * T)
    return T, P, rho


def is_auto(v) -> bool:
    return isinstance(v, str) and v.strip().lower() == "auto"


def inp(doc: dict, stage: str, key: str, default=None):
    """Read inputs.<stage>.<key> with a default."""
    v = get_path(doc, f"inputs.{stage}.{key}")
    return default if v is None else v


def out(doc: dict, stage: str, key: str | None = None):
    """Read outputs.<stage>[.key]; raise a clear error if the upstream stage has not run."""
    d = get_path(doc, f"outputs.{stage}")
    if d is None:
        raise RuntimeError(f"stage '{stage}' has no outputs yet (run it first)")
    if key is None:
        return d
    if key not in d:
        raise KeyError(f"outputs.{stage}.{key} missing")
    return d[key]


def nearest_prime_not_sharing(target: int, avoid: list[int], lo: int = 7, hi: int = 61) -> int:
    """Closest number to `target` in [lo, hi] that shares no factor > 1 with any of `avoid`."""
    def ok(n):
        return all(math.gcd(n, a) == 1 for a in avoid)
    best = None
    for n in range(lo, hi + 1):
        if ok(n) and (best is None or abs(n - target) < abs(best - target)):
            best = n
    return best if best is not None else target


def journal_rule(d_torque_mm: float, D_turbine_m: float, D2_m: float = 0.0) -> float:
    """Bearing journal diameter [mm]: the larger of the torque minimum and the stiffness
    rule of thumb (0.12 x turbine tip diameter, 0.09 x impeller diameter; micro-turbojet
    fleet: 8 mm at 60 mm wheels, 12-15 mm at 110 mm wheels)."""
    return max(d_torque_mm, 0.12 * D_turbine_m * 1e3, 0.09 * D2_m * 1e3, 7.0)


def r(x, n=4):
    """Round for tidy output (None-safe)."""
    if x is None:
        return None
    return float(f"{x:.{n}g}") if isinstance(x, float) else x
