"""Axial turbine blading: NGV ring and rotor wheel.

Blade sections are planar 2-D profiles (camber angle varying linearly from
inlet to exit angle, NACA thickness) placed on planes tangent to cylinders
at three radii and ruled-lofted -- the construction boomsonic_v0 found to
be robust (wrapped sections gave non-planar wires and invalid solids).
The root section is embedded into the platform ring / disc rim so the fuse
is watertight; the tip section stops at the running clearance.
"""
from __future__ import annotations

import math

import numpy as np
import cadquery as cq

from . import cadlib


def _section_wire(chord, a_in, a_out, t_over_c, te, r, x_le, twist_deg=0.0):
    p2 = cadlib.camber_section(chord, a_in, a_out, t_over_c, n=26, te_thickness=te)
    p2[:, 0] -= p2[:, 0].min()
    p2[:, 1] -= p2[:, 1].mean()
    # plane tangent to the cylinder at radius r: local (x, y_tangential) -> 3-D (x, r, y) rotated by twist
    pts = []
    for x, y in p2:
        pts.append((x_le + x, r, y))
    w = cadlib.wire_from_points(pts)
    if twist_deg:
        w = w.rotate((0, 0, 0), (1, 0, 0), twist_deg)
    return w


def blade_row(x_le, r_hub, r_tip, chord_hub, chord_tip, a_in, a_out, t_over_c, te, n, embed=0.8,
              tip_clearance=0.0, twist_tip_deg=0.0):
    """Ruled loft between root (embedded), mid and tip sections; returns (pattern, single)."""
    radii = [r_hub - embed, 0.5 * (r_hub + r_tip), r_tip - tip_clearance]
    chords = [chord_hub, 0.5 * (chord_hub + chord_tip), chord_tip]
    twists = [0.0, 0.5 * twist_tip_deg, twist_tip_deg]
    wires = [_section_wire(c, a_in, a_out, t_over_c, te, r, x_le, tw) for c, r, tw in zip(chords, radii, twists)]
    blade = cadlib.loft_sections(wires, ruled=True)
    return cadlib.pattern(blade, n), blade


def ngv_ring(sh: dict, verbose=None) -> dict:
    """NGV: hub ring + shroud ring + vanes (fused when the boolean passes its check)."""
    n = int(sh["n"])
    cx, chord = sh["cx"], sh["chord"]
    x0, rt, rh = sh["x0"], sh["r_tip"], sh["r_hub"]
    t_ring = sh["ring_thickness"]
    L_ring = cx * 1.4
    x_ring0 = x0 - 0.2 * cx
    hub_ring = cadlib.ring(x_ring0, x_ring0 + L_ring, rh, rh - t_ring)
    shroud_ring = cadlib.ring(x_ring0, x_ring0 + L_ring, rt + t_ring, rt)
    vanes, vane = blade_row(x0, rh, rt, chord, chord, sh["angle_in"], sh["angle_out"], sh["tmax_over_c"],
                            sh["te_thickness"], n, embed=0.6 * t_ring, tip_clearance=-0.6 * t_ring)
    body, ok, msg = cadlib.fuse_checked(hub_ring, [shroud_ring] + list(vanes.Solids()), "ngv ring")
    notes = [msg]
    if not ok:
        body = cq.Compound.makeCompound([hub_ring, shroud_ring, vanes])
        notes.append("ngv: fuse failed -> compound")
    return dict(shape=body, notes=notes, fused=ok, vane_volume_cm3=cadlib.volume(vane) / 1e3)


def turbine_wheel(sh: dict, verbose=None) -> dict:
    """Integral turbine wheel: disc of revolution + rotor blades on the rim."""
    n = int(sh["n"])
    disc = cadlib.revolve(sh["disc_profile"])
    blades, blade = blade_row(sh["x0"], sh["r_hub"], sh["r_tip"], sh["chord"], sh["chord"] * 0.9,
                              sh["angle_in"], sh["angle_out"], sh["tmax_over_c"], sh["te_thickness"], n,
                              embed=1.0, tip_clearance=0.0)
    body, ok, msg = cadlib.fuse_checked(disc, list(blades.Solids()), "turbine wheel")
    notes = [msg]
    if not ok:
        cur, ok = disc, True
        for i, b in enumerate(blades.Solids()):
            cur2, ok_i, m_i = cadlib.fuse_checked(cur, [b], f"turbine blade {i}")
            if not ok_i:
                ok = False
                notes.append(m_i + " -> FAILED")
                break
            cur = cur2
        if ok:
            body = cur
            notes.append("turbine: sequential fuse OK")
        else:
            body = cq.Compound.makeCompound([disc, blades])
            notes.append("turbine: fuse failed -> compound")
    return dict(shape=body, notes=notes, fused=ok, blade_volume_cm3=cadlib.volume(blade) / 1e3, disc=disc)
