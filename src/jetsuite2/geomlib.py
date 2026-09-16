"""Meridional profiles shared by the sizing stages and the CAD builder.

Everything here is a pure function of numbers -> point lists (x, r) in metres,
x along the engine axis (positive aft, x = 0 at the impeller nose).  The rotor,
mechanical and geometry stages use the same profiles for masses and inertias
that the CAD stage revolves, so analysis and geometry cannot drift apart.
"""
from __future__ import annotations

import math

import numpy as np


# ------------------------------------------------------------- helpers
def bezier(p0, p1, p2, p3, n=24):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)


def revolved_volume(profile) -> float:
    """Volume of a closed (x, r) polygon revolved about the x axis (Pappus / Green)."""
    p = np.asarray(profile, dtype=float)
    x, r = p[:, 0], p[:, 1]
    x2, r2 = np.roll(x, -1), np.roll(r, -1)
    # V = pi * integral r^2 dx  (signed, closed polygon)
    v = np.sum((r ** 2 + r * r2 + r2 ** 2) / 3.0 * (x2 - x)) * math.pi
    return abs(float(v))


def revolved_inertia(profile, rho: float) -> tuple[float, float, float, float]:
    """(mass, Ip polar, Id diametral about the CG, x_cg) of a revolved (x, r) polygon.

    Uses thin-disc slicing along x with the piecewise-linear r(x) of each edge."""
    p = np.asarray(profile, dtype=float)
    n = len(p)
    m = ip = mx = mxx = 0.0
    for i in range(n):
        x0, r0 = p[i]
        x1, r1 = p[(i + 1) % n]
        if abs(x1 - x0) < 1e-12:
            continue
        xs = np.linspace(x0, x1, 40)
        rs = r0 + (r1 - r0) * (xs - x0) / (x1 - x0)
        dx = (x1 - x0) / (len(xs) - 1)
        w = np.full(len(xs), dx)
        w[0] = w[-1] = dx / 2
        dm = rho * math.pi * rs ** 2 * w          # signed by dx
        m += dm.sum()
        ip += (0.5 * dm * rs ** 2).sum()
        mx += (dm * xs).sum()
        mxx += (dm * (xs ** 2 + rs ** 2 / 4)).sum()  # thin disc: Id about own axis = m r^2/4
    if abs(m) < 1e-15:
        return 0.0, 0.0, 0.0, 0.0
    x_cg = mx / m               # signed sums share one sign: the ratio is orientation-free
    m, ip, mxx = abs(m), abs(ip), abs(mxx)
    id_cg = mxx - m * x_cg ** 2
    return m, ip, max(id_cg, 0.0), x_cg


# ------------------------------------------------------------ impeller
def impeller_hub_profile(r1h, r2, L, r_bore=0.0, back_boss_r=None, back_boss_len=0.0,
                         rim_thickness=None, nose_len=None, n=20):
    """Closed meridional profile of an impeller hub (solid of revolution) with a
    back-face boss, x from 0 (nose) to L (exit face) + boss.

    The hub curve is a cubic Bezier from (0, r1h) tangent to the axis direction
    to (L, r2) tangent to radial (Aungier-style)."""
    rim = 0.06 * r2 if rim_thickness is None else rim_thickness
    boss_r = 0.35 * r2 if back_boss_r is None else back_boss_r
    nose = 0.15 * L if nose_len is None else nose_len
    hub = bezier((nose, r1h), (nose + 0.55 * (L - nose), r1h), (L, r1h + 0.35 * (r2 - r1h)), (L, r2), n)
    pts = [(0.0, r_bore), (0.0, 0.75 * r1h), (nose, r1h)]
    pts += [tuple(p) for p in hub[1:]]
    # exit face and back face: rim, then back-face scallop down to the boss
    x_back = L + rim
    pts += [(x_back, r2), (x_back + 0.02 * r2, 0.85 * r2)]
    back = bezier((x_back + 0.02 * r2, 0.85 * r2), (x_back + 0.08 * r2, 0.6 * r2),
                  (x_back + 0.10 * r2, boss_r + 0.02 * r2), (x_back + 0.12 * r2, boss_r), 10)
    pts += [tuple(p) for p in back[1:]]
    x_boss_end = x_back + 0.12 * r2 + back_boss_len
    pts += [(x_boss_end, boss_r), (x_boss_end, r_bore)]
    return [(float(x), float(r)) for x, r in pts]


def impeller_shroud_curve(r1s, r2, L, b2, n=24):
    """Shroud (casing) contour from the eye (0, r1s) to the exit (L - b2, r2); the exit
    passage width b2 separates it axially from the hub's exit corner at (L, r2)."""
    xe = L - b2
    return [tuple(map(float, p)) for p in
            bezier((0.0, r1s), (0.45 * xe, r1s), (0.75 * xe, r1s + 0.7 * (r2 - r1s)), (xe, r2), n)]


# ------------------------------------------------------------- turbine
def turbine_disc_profile(r_hub, r_bore, t_rim, t_web, t_hub, x_rim0, hub_len, n=12):
    """Closed profile of a turbine disc: rim (blade platform) of thickness t_rim at
    r_hub, web tapering to a hub of length hub_len at r_bore .. r_bore+hub height.
    x_rim0 = axial position of the rim front face."""
    x_rim1 = x_rim0 + t_rim
    xc = 0.5 * (x_rim0 + x_rim1)
    r_web_top = 0.92 * r_hub
    r_web_bot = max(r_bore + 0.25 * (r_hub - r_bore), r_bore + 3e-3)
    x_hub0, x_hub1 = xc - hub_len / 2, xc + hub_len / 2
    pts = [(x_rim0, r_hub), (x_rim1, r_hub), (x_rim1, r_web_top),
           (xc + t_web / 2, 0.8 * r_hub), (xc + t_web / 2, r_web_bot), (x_hub1, r_web_bot - 1e-3),
           (x_hub1, r_bore), (x_hub0, r_bore), (x_hub0, r_web_bot - 1e-3), (xc - t_web / 2, r_web_bot),
           (xc - t_web / 2, 0.8 * r_hub), (x_rim0, r_web_top)]
    return [(float(x), float(r)) for x, r in pts]


# --------------------------------------------------------------- shaft
def shaft_profile(segments, r_bore=0.0):
    """segments: list of (length, radius) from the front end; returns a closed (x, r) profile."""
    pts = [(0.0, r_bore)]
    x = 0.0
    for L, rr in segments:
        pts.append((x, rr))
        x += L
        pts.append((x, rr))
    pts.append((x, r_bore))
    return [(float(a), float(b)) for a, b in pts]


def tube_volume(od, id_, L):
    return math.pi / 4 * (od ** 2 - id_ ** 2) * L


def ring_volume(r_out, r_in, L):
    return math.pi * (r_out ** 2 - r_in ** 2) * L
