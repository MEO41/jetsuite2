"""Parametric centrifugal impeller: hub of revolution + main and splitter blades.

Blade definition (all from the geometry sheet, millimetres / degrees):

* meridional channel: hub curve (from the hub profile) and shroud curve;
  streamlines are linear blends between them at matched meridional fraction;
* blade angle beta(s) along each streamline eases from the inlet blade angle
  (hub / rms / shroud values) to the exit backsweep; the wrap angle follows
  from d(theta) = tan(beta) dm / r;
* the trailing edge is made radial (same theta on every streamline), which
  is the manufacturable radial-fibre exducer the stress sizing assumes;
* normal thickness tapers from the root value at the hub to the tip value at
  the shroud, with an elliptic leading edge;
* suction / pressure surfaces are B-spline surfaces through the offset grids,
  closed by ruled caps and sewn (``cadlib.blade_solid_from_grids``);
* the root row is embedded 0.6 mm into the hub so the fuse is watertight.

Build time is dominated by the single multi-tool fuse of all blades onto the
hub.  If the fuse fails its volume check, the part is returned as a compound
(hub + blades) and flagged, never silently.
"""
from __future__ import annotations

import math

import numpy as np
import cadquery as cq

from . import cadlib


def _arc_param(curve: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.sum(np.diff(curve, axis=0) ** 2, axis=1))
    s = np.concatenate([[0.0], np.cumsum(d)])
    return s / s[-1]


def _resample(curve: np.ndarray, s_new: np.ndarray) -> np.ndarray:
    s = _arc_param(curve)
    return np.c_[np.interp(s_new, s, curve[:, 0]), np.interp(s_new, s, curve[:, 1])]


def hub_curve_from_profile(profile: list, r1h: float, r2: float) -> np.ndarray:
    """Extract the flow-path hub curve (nose -> exit rim) from the closed hub profile."""
    p = np.asarray(profile, dtype=float)
    # the flow-path hub runs from the first point at r ~ r1h to the first point at r ~ r2
    i0 = int(np.argmin(np.abs(p[:, 1] - r1h) + 1e3 * (p[:, 0] < 0)))
    i1 = int(np.argmax(p[:, 1] >= r2 - 1e-6))
    return p[i0:i1 + 1]


def camber_streamlines(sheet: dict, n_span=7, n_chord=41, embed=0.6, splitter=False):
    """The CAD's blade streamlines: list of (pts (n_chord, 2) meridional x/r, theta (n_chord,), m (n_chord,), tt)
    after the radial-TE correction, plus theta_te_ref and the chord grid.  ``camber_grids`` builds the surfaces
    from these; the CFD domain extends these same streamlines so the periodic faces sit exactly where the CAD
    blades are."""
    r1s, r1h, r2, L = sheet["r1s"], sheet["r1h"], sheet["r2"], sheet["axial_length"]
    clearance = sheet["tip_clearance"]
    hub = hub_curve_from_profile(sheet["hub_profile"], r1h, r2)
    shroud = np.asarray(sheet["shroud_curve"], dtype=float)
    s_start = sheet["splitter_start"] if splitter else 0.0
    s_grid = np.linspace(s_start, 1.0, n_chord)
    # meridional distribution: cluster toward LE
    s_grid = s_start + (1.0 - s_start) * (1 - np.cos(np.pi * np.linspace(0, 1, n_chord))) / 2 * 0.3 + \
        (1.0 - s_start) * np.linspace(0, 1, n_chord) * 0.7 + 0.0
    s_grid = s_start + (s_grid - s_grid[0]) / (s_grid[-1] - s_grid[0]) * (1.0 - s_start)
    hub_pts = _resample(hub, s_grid)
    shr_pts = _resample(shroud, s_grid)
    # span stations: embedded root row, then hub..tip (minus clearance)
    t_stations = np.concatenate([[-embed / max(r1s - r1h, 1.0)], np.linspace(0.0, 1.0, n_span - 1)])
    beta_le = {"h": sheet["beta_le_hub"], "m": sheet["beta_le_rms"], "s": sheet["beta_le_shroud"]}
    beta_te = sheet["backsweep"]
    t_root, t_tip = sheet["t_root"], sheet["t_tip"]
    thetas_te = []
    streamlines = []
    def inward_normal(curve):
        d = np.gradient(curve, axis=0)
        n = np.c_[d[:, 1], -d[:, 0]]            # rotate the tangent by -90 deg: (dx, dr) -> (dr, -dx), points to smaller r
        return n / np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]

    n_hub_in = inward_normal(hub_pts)          # into the hub metal (toward the axis)
    n_shr_in = -inward_normal(shr_pts)         # into the shroud metal (away from the axis)
    for t in t_stations:
        tt = min(max(t, 0.0), 1.0)
        if t < 0:
            pts = hub_pts + n_hub_in * embed   # root row buried a fixed depth below the hub surface
        elif t >= 1.0 - 1e-9:
            pts = shr_pts - n_shr_in * clearance   # tip row pulled off the shroud by the running clearance
        else:
            pts = hub_pts + (shr_pts - hub_pts) * t          # (n_chord, 2): x, r
        # inlet blade angle interpolated hub->shroud (quadratic through rms)
        b_le = np.interp(tt, [0.0, 0.5, 1.0], [beta_le["h"], beta_le["m"], beta_le["s"]])
        m = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])))])
        sfrac = (s_grid - s_grid[0]) / (s_grid[-1] - s_grid[0])
        ease = 3 * sfrac ** 2 - 2 * sfrac ** 3
        beta = np.radians(b_le + (beta_te - b_le) * ease)
        dtheta = np.tan(beta[:-1]) * np.diff(m) / np.maximum(pts[:-1, 1], 1e-3)
        theta = np.concatenate([[0.0], np.cumsum(dtheta)])
        streamlines.append((pts, theta, m, tt))
        thetas_te.append(theta[-1])
    # radial trailing edge: shift each streamline's theta linearly in s so all end at the mean theta_TE
    theta_te_ref = float(np.mean(thetas_te[1:]))
    corrected = []
    for pts, theta, m, tt in streamlines:
        corrected.append((pts, theta + (theta_te_ref - theta[-1]) * (m / m[-1]), m, tt))
    return corrected, theta_te_ref, s_grid


def camber_grids(sheet: dict, n_span=7, n_chord=41, embed=0.6, splitter=False):
    """Suction and pressure side grids (n_span, n_chord, 3) in mm for one blade at theta = 0."""
    streamlines, theta_te_ref, s_grid = camber_streamlines(sheet, n_span=n_span, n_chord=n_chord, embed=embed, splitter=splitter)
    t_root, t_tip = sheet["t_root"], sheet["t_tip"]
    P_grid, thick_grid = [], []
    for i, (pts, theta, m, tt) in enumerate(streamlines):
        sfrac = m / m[-1]
        # thickness: root->tip taper, elliptic LE over the first 8 % of meridional length, TE rounded
        t_n = t_root + (t_tip - t_root) * tt
        le = np.clip(sfrac / 0.08, 0, 1)
        thick = t_n * np.sqrt(np.clip(1 - (1 - le) ** 2, 0, 1))
        thick = np.maximum(thick, 0.35 * t_n)
        thick[-1] = 0.9 * t_n
        x, r = pts[:, 0], pts[:, 1]
        P_grid.append(np.c_[x, r * np.cos(theta), r * np.sin(theta)])
        thick_grid.append(thick)
    P = np.array(P_grid)                 # (n_span, n_chord, 3) camber surface
    T = np.array(thick_grid)             # (n_span, n_chord)
    dPs = np.gradient(P, axis=1)         # along the chord
    dPt = np.gradient(P, axis=0)         # across the span (well defined everywhere incl. the TE)
    nrm = np.cross(dPs, dPt)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=2), 1e-9)[..., None]
    ss = P + nrm * (T / 2)[..., None]
    ps = P - nrm * (T / 2)[..., None]
    return ss, ps, theta_te_ref


def build_impeller(sheet: dict, verbose=None) -> dict:
    """Return dict(shape, parts, notes, blades_fused: bool)."""
    notes = []
    n_main, n_split = int(sheet["n_main"]), int(sheet["n_splitter"])
    sheet = dict(sheet)
    sheet["splitter_start"] = 1.0 - float(sheet["splitter_length_frac"])
    hub = cadlib.revolve(sheet["hub_profile"])
    if verbose:
        verbose(f"  impeller hub {cadlib.volume(hub)/1e3:.1f} cm3, valid={cadlib.valid(hub)}")
    ss, ps, th_te = camber_grids(sheet)
    main = cadlib.blade_solid_from_grids(ss, ps)
    v_main = cadlib.volume(main)
    notes.append(f"main blade volume {v_main/1e3:.3f} cm3, valid={cadlib.valid(main)}, wrap {math.degrees(th_te):.1f} deg")
    blades = [cadlib.rotate_x(main, 360.0 * k / n_main) for k in range(n_main)]
    if n_split > 0:
        ss2, ps2, _ = camber_grids(sheet, splitter=True)
        split = cadlib.blade_solid_from_grids(ss2, ps2)
        v_split = cadlib.volume(split)
        notes.append(f"splitter volume {v_split/1e3:.3f} cm3, valid={cadlib.valid(split)}")
        pitch = 360.0 / n_main
        blades += [cadlib.rotate_x(split, pitch / 2 + 360.0 * k / n_split) for k in range(n_split)]
    fused, ok, msg = cadlib.fuse_checked(hub, blades, "impeller (multi-tool fuse)")
    notes.append(msg)
    if not ok:
        # fall back to sequential fuses, each checked; slower but far more robust
        cur, ok = hub, True
        for i, b in enumerate(blades):
            cur2, ok_i, m_i = cadlib.fuse_checked(cur, [b], f"impeller blade {i}")
            if not ok_i:
                notes.append(m_i + " -> FAILED")
                ok = False
                break
            cur = cur2
        if ok:
            fused = cur
            notes.append("impeller: sequential fuse OK")
    if ok:
        shape = fused
    else:
        notes.append("impeller: blade fuse FAILED volume/validity check -> compound of hub + blades")
        shape = cq.Compound.makeCompound([hub] + blades)
    return dict(shape=shape, hub=hub, blades=blades, notes=notes, blades_fused=ok,
                blade_volume_cm3=v_main / 1e3, wrap_deg=math.degrees(th_te))
