"""Part builders.  Each takes the geometry sheet (mm) and returns a dict of
``name -> (shape, material)``.  ``PART_GROUPS`` maps every builder to the
sheet groups it reads, which is what the per-part cache keys on.
"""
from __future__ import annotations

import math

import numpy as np
import cadquery as cq

from . import cadlib, hardware, impeller as impeller_mod, blades as blades_mod


# ----------------------------------------------------------------- impeller
def build_impeller(sheet: dict, notes: list) -> dict:
    res = impeller_mod.build_impeller(sheet["impeller"])
    notes.extend(res["notes"])
    out = {"impeller": (res["shape"], sheet["impeller"]["material"])}
    imp = sheet["impeller"]
    # impeller nose nut (fine-thread hex) on the shaft nose, seated on the impeller nose face
    x_nut = -0.5 - imp["nut_height"]
    out["impeller_nut"] = (hardware.locknut(x_nut, imp["bore_d"], imp["nut_od"], imp["nut_height"]), "AISI4340")
    return out


# --------------------------------------------------------------- inlet/shroud
def build_inlet(sheet: dict, notes: list) -> dict:
    s = sheet["inlet"]
    wall, sw = s["wall"], s["shroud_wall"]
    shroud = np.asarray(s["shroud_curve"])          # (x, r) from the eye to (L - b2, r2)
    r_throat = s["r_throat"]
    lip = s["lip_radius"]
    x0 = s["x0"]
    # meridional profile: bellmouth (quarter ellipse) -> throat -> shroud contour (+clearance) -> flange, then back outside
    n = 10
    bell_in = [(x0 + lip * (1 - math.cos(a)), r_throat + lip * (1 - math.sin(a))) for a in np.linspace(0, math.pi / 2, n)]
    inner = bell_in + [(x, r + (r_throat - shroud[0, 1])) for x, r in shroud[1:]]
    x_end, r_end = inner[-1]
    r_flange = s["r_flange"]
    outer = [(x_end, r_flange + 8.0), (x_end - 6.0, r_flange + 8.0)]
    outer_shroud = [(x, r + sw + (r_throat - shroud[0, 1])) for x, r in shroud[::-1][2:]]
    bell_out = [(x0 + (lip + wall) * (1 - math.cos(a)), r_throat + (lip + wall) * (1 - math.sin(a)))
                for a in np.linspace(math.pi / 2, 0, n)]
    prof = inner + outer + [(x_end - 6.0, outer_shroud[0][1] + 2.0)] + outer_shroud + bell_out
    # guard: strictly increasing then decreasing x is not required; just build and check
    shape = cadlib.revolve(prof)
    if not cadlib.valid(shape) or cadlib.volume(shape) <= 0:
        notes.append("inlet_shroud: revolve invalid")
    return {"inlet_shroud": (shape, s["material"])}


# ----------------------------------------------------------------- diffuser
def build_diffuser(sheet: dict, notes: list) -> dict:
    d = sheet["diffuser"]
    r2, r3, r4, b = d["r2"], d["r3"], d["r4"], d["width"]
    x0, x1 = d["x_channel0"], d["x_channel1"]
    bp = d["back_plate"]
    out = {}
    # back plate: annular plate behind the channel outside the impeller rim, stepping inward to the
    # hub only behind the impeller back face (clearance 1 mm to the rim / back-face boss)
    xb = max(d["x_impeller_back"] + 1.0, x1 + bp + 0.5)
    a = r2 + 1.0
    plate = cadlib.revolve([(x1, a), (x1, r4 + 4.0), (x1 + bp, r4 + 4.0), (x1 + bp, a + bp),
                            (xb + bp, a + bp), (xb + bp, 0.62 * r2), (xb, 0.62 * r2), (xb, a)])
    if not cadlib.valid(plate) or cadlib.volume(plate) <= 0:
        notes.append("diffuser back plate: L-profile invalid, using plain annulus")
        plate = cadlib.ring(x1, x1 + bp, r4 + 4.0, r2 + 1.0)
    out["diffuser_back_plate"] = (plate, d["material"])
    if d["type"] == "vaned" and d["n_vanes"] > 0:
        n = int(d["n_vanes"])
        a_le, a_te = d["vane_le_angle"], d["vane_te_angle"]
        t = d["vane_thickness"]
        rr = np.linspace(r3, r4, 40)
        al = np.radians(a_le + (a_te - a_le) * (rr - r3) / (r4 - r3))
        th = np.concatenate([[0.0], np.cumsum(np.tan(al[:-1]) / rr[:-1] * np.diff(rr))])
        cy, cz = rr * np.cos(th), rr * np.sin(th)
        # offset normal to the camber line for thickness (tapered to the TE)
        tx = np.gradient(cy); ty = np.gradient(cz)
        nn = np.hypot(tx, ty); nx, ny = -ty / nn, tx / nn
        half = 0.5 * t * (1 - 0.5 * (rr - r3) / (r4 - r3))
        half[0] = 0.5 * t * 0.5
        up = np.c_[cy + nx * half, cz + ny * half]
        lo = np.c_[cy - nx * half, cz - ny * half]
        poly = np.vstack([up, lo[::-1]])
        vane = cadlib.polygon_prism(poly, x0, b)
        out["diffuser_vanes"] = (cadlib.pattern(vane, n), d["material"])
    # deswirl: axial vanes in the annulus r_deswirl_inner .. r4 over the deswirl length
    nd = int(d["n_deswirl"])
    ri, L = d["r_deswirl_inner"], d["deswirl_length"]
    xd0 = x1 + bp
    vane = cq.Workplane("XY").box(L, r4 - ri - 0.5, 1.2, centered=(False, False, True)).translate((xd0, ri + 0.25, 0)).val()
    vane = vane.rotate((xd0, 0, 0), (xd0, 1, 0), 0)
    out["deswirl_vanes"] = (cadlib.pattern(vane, nd), d["material"])
    out["deswirl_inner_wall"] = (cadlib.ring(xd0, xd0 + L, ri, ri - 2.0), d["material"])
    return out


# ------------------------------------------------------------------- casing
def build_casing(sheet: dict, notes: list) -> dict:
    c = sheet["casing"]
    r, w = c["r_outer"], c["wall"]
    x0, x1 = c["x0"], c["x1"]
    ft, fw = c["flange_thickness"], c["flange_width"]
    prof = [(x0, r - w), (x0, r + fw), (x0 + ft, r + fw), (x0 + ft, r), (x1 - ft, r), (x1 - ft, r + fw),
            (x1, r + fw), (x1, r - w)]
    shape = cadlib.revolve(prof)
    n = int(c["n_bolts"])
    r_pcd = r + fw / 2 + 0.5
    from ..library import components
    scr = components.screw(c["screw"])
    holes = cq.Compound.makeCompound([cadlib.cylinder_x(x0 - 1, ft + 2, scr["d"] / 2 + 0.3).translate(
        (0, r_pcd * math.cos(2 * math.pi * i / n), r_pcd * math.sin(2 * math.pi * i / n))) for i in range(n)]
        + [cadlib.cylinder_x(x1 - ft - 1, ft + 2, scr["d"] / 2 + 0.3).translate(
            (0, r_pcd * math.cos(2 * math.pi * i / n), r_pcd * math.sin(2 * math.pi * i / n))) for i in range(n)])
    shape, ok, msg = cadlib.cut_checked(shape, holes, "casing bolt holes")
    notes.append(msg)
    out = {"outer_casing": (shape, c["material"])}
    length = [l for l in scr["lengths"] if l >= 2 * ft + 2][0] if any(l >= 2 * ft + 2 for l in scr["lengths"]) else scr["lengths"][-1]
    out["flange_screws_front"] = (hardware.flange_screws(x0 - 0.0, r_pcd, n, scr["d"], scr["dk"], scr["k"], length, scr["s"], 0.0), "AISI316")
    out["flange_screws_rear"] = (hardware.flange_screws(x1 + 0.0, r_pcd, n, scr["d"], scr["dk"], scr["k"], length, scr["s"], 0.0)
                                 .rotate((0, 0, 0), (0, 1, 0), 180).translate((2 * x1, 0, 0)), "AISI316")
    return out


# --------------------------------------------------------------- combustor
def build_combustor(sheet: dict, notes: list) -> dict:
    cb = sheet["combustor"]
    x0, L, Lt = cb["x0"], cb["L_liner"], cb["L_transition"]
    ro, ri, w = cb["r_liner_outer"], cb["r_liner_inner"], cb["liner_wall"]
    xo_end = x0 + L
    out = {}
    ric, wic = cb["inner_casing_r"], cb["inner_casing_wall"]
    r_cas_in = sheet["casing"]["r_outer"] - sheet["casing"]["wall"]
    # liner exits meet the NGV annulus but stay clear of the inner and outer casings
    ex_out = min(cb["exit_r_out"], r_cas_in - 1.0)
    ex_in = max(cb["exit_r_in"], ric + 1.0)
    # outer liner: tube + conical transition to the NGV tip radius
    outer = cadlib.revolve([(x0, ro), (xo_end, ro), (xo_end + Lt, ex_out), (xo_end + Lt, ex_out - w),
                            (xo_end, ro - w), (x0, ro - w)])
    inner = cadlib.revolve([(x0, ri + w), (xo_end, ri + w), (xo_end + Lt, ex_in + w), (xo_end + Lt, ex_in),
                            (xo_end, ri), (x0, ri)])
    # holes per zone
    def hole_cyls(r_wall, n, d, x, inward=True):
        cyls = []
        for i in range(n):
            a = 2 * math.pi * i / n + (0.5 * 2 * math.pi / n if not inward else 0)
            c = cq.Solid.makeCylinder(d / 2, 3 * w + 1.0, cq.Vector(x, (r_wall - 1.5 * w) * math.cos(a), (r_wall - 1.5 * w) * math.sin(a)),
                                      cq.Vector(0, math.cos(a), math.sin(a)))
            cyls.append(c)
        return cyls
    outer_cyls, inner_cyls = [], []
    for zone, h in cb["holes"].items():
        x = x0 + h["x_frac"] * L
        outer_cyls += hole_cyls(ro, int(h["n_outer"]), h["d"], x)
        inner_cyls += hole_cyls(ri + w, int(h["n_inner"]), h["d"], x, inward=False)
    outer, ok1, m1 = cadlib.cut_checked(outer, cq.Compound.makeCompound(outer_cyls), "outer liner holes")
    inner, ok2, m2 = cadlib.cut_checked(inner, cq.Compound.makeCompound(inner_cyls), "inner liner holes")
    notes += [m1, m2]
    out["liner_outer"] = (outer, cb["liner_material"])
    out["liner_inner"] = (inner, cb["liner_material"])
    # dome: annular plate at x0 with vaporiser holes
    nv, dv = int(cb["n_vaporisers"]), cb["vaporiser_d"]
    rv = cb["vaporiser_r"]
    dome = cadlib.ring(x0 - w, x0, ro, ri)
    vap_holes = cq.Compound.makeCompound([cadlib.cylinder_x(x0 - w - 1, w + 2, dv / 2 + 0.2).translate(
        (0, rv * math.cos(2 * math.pi * i / nv), rv * math.sin(2 * math.pi * i / nv))) for i in range(nv)])
    dome, ok3, m3 = cadlib.cut_checked(dome, vap_holes, "dome vaporiser holes")
    notes.append(m3)
    out["liner_dome"] = (dome, cb["liner_material"])
    # vaporisers: J-tubes: axial tube from the dome into the liner, turning 180 deg back toward the dome
    Lv = cb["vaporiser_length"]
    tube = cadlib.ring(x0 - 8.0, x0 + Lv, dv / 2, dv / 2 - 0.6)
    bend = cq.Solid.makeTorus(dv * 0.75, dv / 2, cq.Vector(x0 + Lv, rv - dv * 0.75, 0), cq.Vector(0, 0, 1), 0, 180)
    bend = bend.cut(cq.Solid.makeTorus(dv * 0.75, dv / 2 - 0.6, cq.Vector(x0 + Lv, rv - dv * 0.75, 0), cq.Vector(0, 0, 1), 0, 180))
    ret = cadlib.ring(x0 + 0.65 * Lv, x0 + Lv, dv / 2, dv / 2 - 0.6).translate((0, rv - 1.5 * dv, 0))
    one = cq.Compound.makeCompound([tube.translate((0, rv, 0)), bend, ret])
    out["vaporisers"] = (cadlib.pattern(one, nv), cb["liner_material"])
    # inner casing (shaft tunnel outer skin) from the dome to the NGV hub
    ric, wic = cb["inner_casing_r"], cb["inner_casing_wall"]
    out["inner_casing"] = (cadlib.ring(x0 - 4.0, xo_end + Lt, ric, ric - wic), "AISI321")
    # igniter(s) through the outer casing into the primary zone
    from ..library import components
    ign = components.igniter()
    x_ign = x0 + cb["igniter_x_frac"] * L
    r_cas = sheet["casing"]["r_outer"]
    for k in range(int(cb["n_igniters"])):
        out[f"igniter_{k+1}"] = (hardware.glow_plug(x_ign, r_cas, 90.0 + 180.0 * k, ign["d"], ign["hex"], ign["body_length"],
                                                    r_cas - ro + ign["reach"] + 2.0), "AISI316")
    return out


# ------------------------------------------------------------------ turbine
def build_ngv(sheet: dict, notes: list) -> dict:
    res = blades_mod.ngv_ring(sheet["ngv"])
    notes.extend(res["notes"])
    return {"ngv_ring": (res["shape"], sheet["ngv"]["material"])}


def build_turbine(sheet: dict, notes: list) -> dict:
    res = blades_mod.turbine_wheel(sheet["turbine"])
    notes.extend(res["notes"])
    ts = sheet["turbine_shroud"]
    shroud = cadlib.ring(ts["x0"], ts["x1"], ts["r_in"] + ts["wall"], ts["r_in"])
    t = sheet["turbine"]
    nut = hardware.locknut(t["x_disc_mid"] + t["t_rim"] / 2 + 6.0, t["bore_d"], 1.6 * t["bore_d"], 0.6 * t["bore_d"], hex_flats=False)
    return {"turbine_wheel": (res["shape"], t["material"]), "turbine_shroud": (shroud, ts["material"]),
            "turbine_nut": (nut, "IN718")}


# ---------------------------------------------------------- shaft & bearings
def build_shaft(sheet: dict, notes: list) -> dict:
    s = sheet["shaft"]
    b = sheet["bearings"]
    xn, xe = s["x_nose"], s["x_end"]
    rn, rj, rt = s["d_nose"] / 2, s["d_journal"] / 2, s["tube_od"] / 2
    xf, xr, bw = s["x_front_bearing"], s["x_rear_bearing"], s["bearing_width"]
    prof = [(xn, 0.0), (xn, rn * 0.9), (xn + 1.0, rn), (xf - bw, rn), (xf - bw, rj), (xf + bw, rj),
            (xf + bw + 1.0, rt), (xr - bw - 1.0, rt), (xr - bw, rj), (xr + bw, rj), (xr + bw, rj), (xe, rj), (xe, 0.0)]
    shaft = cadlib.revolve(prof)
    # hollow tube between the bearings
    bore = cadlib.ring(xf + bw + 3.0, xr - bw - 3.0, s["tube_id"] / 2)
    shaft, ok, msg = cadlib.cut_checked(shaft, bore, "shaft tube bore")
    notes.append(msg)
    # retaining-ring grooves behind each bearing
    for x in (xf + bw + 0.5 + s["ring_groove_w"] / 2, xr - bw - 0.5 - s["ring_groove_w"] / 2):
        groove = cadlib.ring(x - s["ring_groove_w"] / 2, x + s["ring_groove_w"] / 2, rj + 1.0, s["ring_groove_d"] / 2)
        shaft, ok, msg = cadlib.cut_checked(shaft, groove, "ring groove")
    out = {"shaft": (shaft, s["material"])}
    out["bearing_front"] = (hardware.bearing(xf, b["bore"], b["od"], b["width"], int(b["n_balls"]), b["ball_d"]), "bearing-steel")
    out["bearing_rear"] = (hardware.bearing(xr, b["bore"], b["od"], b["width"], int(b["n_balls"]), b["ball_d"]), "bearing-steel")
    out["retaining_ring_front"] = (hardware.retaining_ring(xf + bw + 0.5 + s["ring_groove_w"] / 2, s["ring_groove_d"],
                                                          s["d_journal"], s["ring_thickness"]), "AISI316")
    out["retaining_ring_rear"] = (hardware.retaining_ring(xr - bw - 0.5 - s["ring_groove_w"] / 2, s["ring_groove_d"],
                                                         s["d_journal"], s["ring_thickness"]), "AISI316")
    return out


def build_housings(sheet: dict, notes: list) -> dict:
    h = sheet["housings"]
    b = sheet["bearings"]
    cb = sheet["combustor"]
    out = {}
    rb = h["bearing_bore"] / 2
    ro = h["front_housing_r_out"]
    hw = h["wall"]
    # front housing: bearing seat + web to the diffuser hub, labyrinth seal lands, O-ring groove
    x0, x1 = h["front_housing_x0"], h["front_housing_x1"]
    prof = [(x0, rb - 1.5), (x0, rb - 1.5 + 4.0), (x0 + 2.0, rb - 1.5 + 4.0), (x0 + 2.0, ro + 6.0),
            (x1 + 2.0, ro + 6.0), (x1 + 2.0, ro), (x1, ro), (x1, rb), (x1 - b["width"] - 0.5, rb),
            (x1 - b["width"] - 0.5, rb - 1.5)]
    fh = cadlib.revolve(prof)
    groove = cadlib.ring(x1 - 4.0, x1 - 4.0 + h["oring_groove_width"], ro + 6.0 + 0.1, ro + 6.0 - h["oring_groove_depth"])
    fh, ok, msg = cadlib.cut_checked(fh, groove, "front housing O-ring groove")
    notes.append(msg)
    # labyrinth teeth on the housing nose (4 teeth)
    out["housing_front"] = (fh, h["material"])
    out["oring_front"] = (hardware.o_ring(x1 - 4.0 + h["oring_groove_width"] / 2, 2 * (ro + 6.0 - h["oring_groove_depth"]), h["oring_cs"]), "FKM")
    # shaft tunnel
    tx0, tx1 = h["tunnel_x0"], h["tunnel_x1"]
    out["shaft_tunnel"] = (cadlib.ring(tx0, tx1, h["tunnel_od"] / 2, h["tunnel_id"] / 2), h["material"])
    # rear housing: bearing seat with a web to the inner casing
    rx0, rx1 = h["rear_housing_x0"], h["rear_housing_x1"]
    ric = cb["inner_casing_r"]
    prof = [(rx0, rb), (rx0, ro), (rx0 + 1.0, ro), (rx0 + 1.0, ric - 0.5), (rx0 + 4.0, ric - 0.5), (rx0 + 4.0, ro),
            (rx1, ro), (rx1, rb)]
    out["housing_rear"] = (cadlib.revolve(prof), h["material"])
    return out


# ------------------------------------------------------------------- nozzle
def build_nozzle(sheet: dict, notes: list) -> dict:
    nz = sheet["nozzle"]
    x0, xe, w = nz["x0"], nz["x_exit"], nz["wall"]
    r_in, r8 = nz["r_in"], nz["r8"]
    prof = [(x0, r_in), (x0 + 0.3 * (xe - x0), r_in), (xe, r8), (xe, r8 + w), (x0 + 0.3 * (xe - x0), r_in + w), (x0, r_in + w)]
    cone = cadlib.revolve(prof)
    r0, L = nz["tail_cone_r0"], nz["tail_cone_L"]
    tail = cadlib.revolve([(x0, 0.0), (x0, r0), (x0 + L, 0.5)])
    inner = cadlib.revolve([(x0 - 1.0, 0.0), (x0 - 1.0, r0 - w), (x0 + L - 3.0, 0.3)])
    tail, ok, msg = cadlib.cut_checked(tail, inner, "tail cone shell")
    n = int(nz["n_struts"])
    strut = cq.Workplane("XY").box(0.25 * L, r_in - 0.7 * r0 + 1.0, 2.0, centered=(False, False, True)).translate((x0 + 0.1 * L, 0.7 * r0 - 1.0, 0)).val()
    out = {"nozzle": (cone, nz["material"]), "tail_cone": (tail, nz["material"]),
           "tail_cone_struts": (cadlib.pattern(strut, n, 45.0), nz["material"])}
    # hot casing: cone from the combustor casing rear flange to the nozzle inlet, over the NGV / turbine
    cs = sheet["casing"]
    xr, r_env, wc, ft, fw = cs["x1"], cs["r_outer"], cs["wall"], cs["flange_thickness"], cs["flange_width"]
    hot = cadlib.revolve([(xr, r_env - wc), (xr, r_env + fw), (xr + ft, r_env + fw), (xr + ft, r_env),
                          (x0 - 0.5, r_in + w), (x0 - 0.5, r_in)])
    out["hot_casing"] = (hot, nz["material"])
    from ..library import components
    pr = components.egt_probe()
    out["egt_probe"] = (hardware.probe(x0 + 0.15 * (xe - x0), r_in + w, 45.0, pr["d"], pr["probe_d"], min(pr["probe_length"], 0.6 * (r_in - r0))), "AISI316")
    return out


PART_GROUPS = {
    "impeller": (build_impeller, ["impeller"]),
    "inlet": (build_inlet, ["inlet"]),
    "diffuser": (build_diffuser, ["diffuser"]),
    "casing": (build_casing, ["casing", "combustor"]),
    "combustor": (build_combustor, ["combustor", "casing"]),
    "ngv": (build_ngv, ["ngv"]),
    "turbine": (build_turbine, ["turbine", "turbine_shroud"]),
    "shaft": (build_shaft, ["shaft", "bearings"]),
    "housings": (build_housings, ["housings", "bearings", "combustor"]),
    "nozzle": (build_nozzle, ["nozzle", "casing"]),
}

COLORS = {
    "Ti-6Al-4V": (0.55, 0.58, 0.62), "Al2618-T61": (0.75, 0.78, 0.82), "Al6061-T6": (0.80, 0.82, 0.85),
    "Al7075-T6": (0.72, 0.75, 0.80), "AISI4340": (0.45, 0.45, 0.48), "AISI321": (0.62, 0.62, 0.64),
    "AISI316": (0.70, 0.70, 0.72), "IN625": (0.70, 0.60, 0.45), "IN713LC": (0.55, 0.45, 0.35), "IN718": (0.58, 0.52, 0.42),
    "MAR-M247": (0.50, 0.42, 0.33), "17-4PH-H900": (0.50, 0.50, 0.53), "bearing-steel": (0.35, 0.35, 0.40), "FKM": (0.1, 0.1, 0.1),
}
