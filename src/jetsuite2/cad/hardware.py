"""Standard hardware as CAD solids, drawn from the library dimensions:
ball bearings (rings + balls + cage), retaining rings, locknuts, socket
head cap screws, O-rings, glow-plug igniter, EGT probe.  Millimetres."""
from __future__ import annotations

import math

import cadquery as cq

from . import cadlib


def bearing(x_centre: float, bore: float, od: float, width: float, n_balls: int, ball_d: float) -> cq.Compound:
    """Angular-contact / deep-groove ball bearing envelope with inner ring, outer ring,
    balls on the pitch circle and a simple cage ring."""
    x0 = x_centre - width / 2
    r_pitch = (bore + od) / 4
    r_ball = ball_d / 2
    inner = cadlib.ring(x0, x0 + width, r_pitch - 0.55 * ball_d, bore / 2)
    outer = cadlib.ring(x0, x0 + width, od / 2, r_pitch + 0.55 * ball_d)
    balls = []
    for k in range(n_balls):
        a = 2 * math.pi * k / n_balls
        balls.append(cq.Solid.makeSphere(r_ball, cq.Vector(x_centre, r_pitch * math.cos(a), r_pitch * math.sin(a))))
    cage = cadlib.ring(x_centre - 0.25 * width, x_centre + 0.25 * width, r_pitch + 0.25 * ball_d, r_pitch - 0.25 * ball_d)
    return cq.Compound.makeCompound([inner, outer, cage] + balls)


def retaining_ring(x: float, groove_d: float, free_d: float, thickness: float, external: bool = True) -> cq.Solid:
    """DIN 471 / 472 ring: flat ring with a 30 deg gap."""
    if external:
        r_in, r_out = groove_d / 2, groove_d / 2 + 2.0 + 0.1 * groove_d
    else:
        r_out, r_in = groove_d / 2, groove_d / 2 - 2.0 - 0.1 * groove_d
    ring = cadlib.ring(x - thickness / 2, x + thickness / 2, r_out, r_in)
    gap = cq.Workplane("YZ", origin=(x - thickness, 0, 0)).polyline(
        [(0, 0), (r_out * 1.2 * math.cos(math.radians(-15)), r_out * 1.2 * math.sin(math.radians(-15))),
         (r_out * 1.2 * math.cos(math.radians(15)), r_out * 1.2 * math.sin(math.radians(15)))]).close().extrude(3 * thickness).val()
    return ring.cut(gap)


def locknut(x0: float, d: float, od: float, height: float, hex_flats: bool = True) -> cq.Solid:
    """Hex (or round KM-type) nut with a bore of d."""
    if hex_flats:
        nut = cq.Workplane("YZ", origin=(x0, 0, 0)).polygon(6, od).extrude(height).val()
    else:
        nut = cadlib.ring(x0, x0 + height, od / 2)
    return nut.cut(cadlib.cylinder_x(x0 - 1, height + 2, d / 2))


def cap_screw(d: float, dk: float, k: float, length: float, s_hex: float):
    """ISO 4762 socket head cap screw along -X from the head seat at x=0 (head from 0 to +k)."""
    head = cadlib.cylinder_x(0.0, k, dk / 2)
    sock = cq.Workplane("YZ", origin=(k - 0.6 * k, 0, 0)).polygon(6, s_hex / math.cos(math.radians(30))).extrude(0.6 * k + 0.1).val()
    head = head.cut(sock)
    shank = cadlib.cylinder_x(-length, length, d / 2)
    return head.fuse(shank)


def flange_screws(x_head: float, r_pcd: float, n: int, d: float, dk: float, k: float, length: float, s_hex: float,
                  offset_deg: float = 0.0) -> cq.Compound:
    sc = cap_screw(d, dk, k, length, s_hex)
    parts = []
    for i in range(n):
        a = math.radians(offset_deg + 360.0 * i / n)
        parts.append(sc.translate((x_head, r_pcd * math.cos(a), r_pcd * math.sin(a))))
    return cq.Compound.makeCompound(parts)


def o_ring(x: float, id_mm: float, cs: float) -> cq.Solid:
    r_major = id_mm / 2 + cs / 2
    return cq.Solid.makeTorus(r_major, cs / 2, cq.Vector(x, 0, 0), cq.Vector(1, 0, 0))


def glow_plug(x_base: float, r_base: float, angle_deg: float, d: float, hex_af: float, body_len: float, reach: float):
    """Glow-plug igniter: hex body outside the casing, threaded reach into the liner."""
    a = math.radians(angle_deg)
    thread = cadlib.cylinder_x(0.0, reach, d / 2)
    body = cq.Workplane("YZ", origin=(reach, 0, 0)).polygon(6, hex_af / math.cos(math.radians(30))).extrude(body_len).val()
    plug = thread.fuse(body)
    # orient radially inward: rotate so +X becomes -radial, then place on the casing
    plug = plug.rotate((0, 0, 0), (0, 0, 1), 90).rotate((0, 0, 0), (1, 0, 0), angle_deg)
    # after rotation the plug axis points along -y rotated by angle; place its base at radius r_base
    return plug.translate((x_base, (r_base + reach) * math.cos(a), (r_base + reach) * math.sin(a)))


def probe(x_base: float, r_base: float, angle_deg: float, d: float, probe_d: float, probe_len: float, hex_af: float = 12.0):
    a = math.radians(angle_deg)
    tip = cadlib.cylinder_x(0.0, probe_len, probe_d / 2)
    body = cq.Workplane("YZ", origin=(probe_len, 0, 0)).polygon(6, hex_af / math.cos(math.radians(30))).extrude(10.0).val()
    thread = cadlib.cylinder_x(probe_len - 6.0, 6.0, d / 2)
    p = tip.fuse(body).fuse(thread)
    p = p.rotate((0, 0, 0), (0, 0, 1), 90).rotate((0, 0, 0), (1, 0, 0), angle_deg)
    return p.translate((x_base, (r_base + probe_len) * math.cos(a), (r_base + probe_len) * math.sin(a)))
