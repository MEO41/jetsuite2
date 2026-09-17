"""2D manufacturing drawings with tolerances from the geometry sheet (roadmap section 9): shaft, bearing housings
and casing as dimensioned half-section SVGs, plus ``drawings.md`` with the fit / tolerance tables (ISO 286 deviations
for the sizes used, runout and flatness callouts, surface finish).  Drawn with matplotlib; every dimension comes
from ``outputs.geometry.sheet``, the fits from the bearing / seal selections in the rotor and geometry stages."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

# ISO 286 fundamental deviations (um) for the sizes this class of engine uses; (lower, upper)
ISO_SHAFT = {"k5": {(10, 18): (1, 9), (18, 30): (2, 11), (30, 50): (2, 13)},
             "h6": {(10, 18): (-11, 0), (18, 30): (-13, 0), (30, 50): (-16, 0)},
             "g6": {(10, 18): (-17, -6), (18, 30): (-20, -7), (30, 50): (-25, -9)}}
ISO_HOLE = {"H6": {(18, 30): (0, 13), (30, 50): (0, 16), (50, 80): (0, 19), (80, 120): (0, 22), (120, 180): (0, 25), (180, 250): (0, 29)},
            "H7": {(18, 30): (0, 21), (30, 50): (0, 25), (50, 80): (0, 30), (80, 120): (0, 35), (120, 180): (0, 40), (180, 250): (0, 46)},
            "J6": {(18, 30): (-5, 8), (30, 50): (-6, 10)}}


def iso(table: dict, grade: str, d: float) -> tuple[float, float] | None:
    for (lo, hi), dev in table[grade].items():
        if lo < d <= hi:
            return dev
    return None


def _dim(ax, x0, y0, x1, y1, text, offset=6.0, fontsize=7, color="0.2"):
    """Linear dimension between two points with extension lines, arrows and text."""
    import numpy as np
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return
    nx, ny = -dy / L, dx / L
    ax.plot([x0, x0 + nx * (offset + 2)], [y0, y0 + ny * (offset + 2)], color=color, lw=0.5)
    ax.plot([x1, x1 + nx * (offset + 2)], [y1, y1 + ny * (offset + 2)], color=color, lw=0.5)
    ax.annotate("", (x1 + nx * offset, y1 + ny * offset), (x0 + nx * offset, y0 + ny * offset),
                arrowprops=dict(arrowstyle="<->", color=color, lw=0.6, shrinkA=0, shrinkB=0))
    ax.text(0.5 * (x0 + x1) + nx * (offset + 2.5), 0.5 * (y0 + y1) + ny * (offset + 2.5), text, fontsize=fontsize, ha="center", va="center", color=color,
            rotation=math.degrees(math.atan2(dy, dx)))


def _frame(ax, title, note):
    ax.set_aspect("equal"); ax.grid(False)
    ax.set_title(title, fontsize=9, loc="left")
    ax.text(0.99, 0.01, note, transform=ax.transAxes, fontsize=6, ha="right", va="bottom", color="0.3")
    ax.set_xlabel("x [mm]"); ax.set_ylabel("r [mm]")


def shaft(sheet: dict, brg: dict, ax) -> list[dict]:
    s = sheet["shaft"]
    xs = [s["x_nose"], s["x_front_bearing"] - 0.5 * s["bearing_width"] - 3.0, s["x_front_bearing"] - 0.5 * s["bearing_width"],
          s["x_front_bearing"] + 0.5 * s["bearing_width"], s["x_rear_bearing"] - 0.5 * s["bearing_width"],
          s["x_rear_bearing"] + 0.5 * s["bearing_width"], s["x_end"]]
    rj = 0.5 * s["d_journal"]; rn = 0.5 * s["d_nose"]; rt = 0.5 * s["tube_od"]; rti = 0.5 * s["tube_id"]
    # outer profile (half section, r >= 0): nose / thread -> front seat -> tube between the bearings -> rear seat -> stub
    prof = [(xs[0], 0), (xs[0], rn), (xs[1], rn), (xs[1], rj), (xs[3], rj), (xs[3], rt), (xs[4], rt), (xs[4], rj), (xs[5], rj),
            (xs[5], rn), (xs[6], rn), (xs[6], 0)]
    px, py = zip(*prof)
    ax.fill(px, py, color="#d9e4f2", ec="k", lw=0.9)
    if rti > 0 and xs[4] > xs[3]:
        ax.fill([xs[3] + 2, xs[4] - 2, xs[4] - 2, xs[3] + 2], [0, 0, rti, rti], color="white", ec="k", lw=0.6)
    ax.plot([xs[0] - 5, xs[6] + 5], [0, 0], "-.", color="0.4", lw=0.6)
    # ring groove and nut threads
    xg = s["x_front_bearing"] - 0.5 * s["bearing_width"] - 1.5
    ax.fill([xg, xg + s["ring_groove_w"], xg + s["ring_groove_w"], xg], [rj, rj, 0.5 * s["ring_groove_d"], 0.5 * s["ring_groove_d"]], color="white", ec="k", lw=0.5)
    fits = []
    dj = s["d_journal"]
    kd = iso(ISO_SHAFT, "k5", dj)
    fits.append(dict(feature="bearing seats (front / rear)", nominal=f"d {dj:.3f}", fit="k5", deviation_um=kd, note=f"{brg['id']} inner ring, interference {kd[0]}..{kd[1]} um; Ra 0.4; runout 5 um to A-B"))
    hd = iso(ISO_SHAFT, "g6", s["d_nose"])
    fits.append(dict(feature="nose / impeller pilot", nominal=f"d {s['d_nose']:.3f}", fit="g6", deviation_um=hd, note="impeller bore slides on; thread for the nut beyond the pilot; Ra 0.8"))
    fits.append(dict(feature="tube between the bearings", nominal=f"OD {s['tube_od']:.2f} / ID {s['tube_id']:.2f}", fit="h11 / drilled", deviation_um=None,
                     note="not a fit; wall balance-machined, concentric to A-B within 0.02"))
    fits.append(dict(feature="retaining ring groove", nominal=f"d {s['ring_groove_d']:.2f} x {s['ring_groove_w']:.2f}", fit=s["retaining_ring"], deviation_um=(0, 60),
                     note="DIN 471 groove tolerance H13"))
    _dim(ax, xs[0], rt + 3, xs[6], rt + 3, f"overall {xs[6]-xs[0]:.2f}", offset=8)
    ax.set_ylim(-6, rt + 22)
    _dim(ax, xs[2], rj, xs[3], rj, f"{s['bearing_width']:.1f} seat k5", offset=6)
    _dim(ax, xs[4], rj, xs[5], rj, f"{s['bearing_width']:.1f} seat k5", offset=6)
    _dim(ax, xs[3] + 6, 0, xs[3] + 6, rt, f"d{s['tube_od']:.2f}", offset=-6)
    _dim(ax, xs[0] + 4, 0, xs[0] + 4, rn, f"d{s['d_nose']:.2f} g6", offset=-6)
    _dim(ax, xs[2] + 1, 0, xs[2] + 1, rj, f"d{dj:.3f} k5 ({kd[0]:+d}/{kd[1]:+d} um)", offset=6)
    ax.text(xs[2], rj + 4, "A", fontsize=8, ha="center", bbox=dict(boxstyle="square", fc="white")); ax.text(xs[4], rj + 4, "B", fontsize=8, ha="center", bbox=dict(boxstyle="square", fc="white"))
    _frame(ax, f"SHAFT  {s['material']}  half section", "datums A-B: bearing seats; runout 0.005 A-B on seats and pilot; all unspecified +/-0.1; chamfers 0.3x45")
    return fits


def housings(sheet: dict, brg: dict, ax) -> list[dict]:
    h = sheet["housings"]; b = sheet["bearings"]
    rb = 0.5 * h["bearing_bore"]; ro = h["front_housing_r_out"]; wall = h["wall"]
    fits = []
    for name, x0, x1 in (("front", h["front_housing_x0"], h["front_housing_x1"]), ("rear", h["rear_housing_x0"], h["rear_housing_x1"])):
        ax.fill([x0, x1, x1, x0], [rb, rb, ro, ro], color="#e8e0d0", ec="k", lw=0.9)
        # internal ring groove for the outer ring
        xg = x1 - 2.0 if name == "front" else x0 + 0.7
        ax.fill([xg, xg + b["internal_ring_groove_w"], xg + b["internal_ring_groove_w"], xg], [rb, rb, 0.5 * b["internal_ring_groove_d"], 0.5 * b["internal_ring_groove_d"]], color="white", ec="k", lw=0.5)
        _dim(ax, x0, ro, x1, ro, f"{x1-x0:.2f}", offset=5)
        ax.text(0.5 * (x0 + x1), rb - 2.5, f"{name} housing", fontsize=7, ha="center")
    # tunnel between the housings
    ax.fill([h["tunnel_x0"], h["tunnel_x1"], h["tunnel_x1"], h["tunnel_x0"]], [0.5 * h["tunnel_id"]] * 2 + [0.5 * h["tunnel_od"]] * 2, color="#e8e0d0", ec="k", lw=0.9)
    ax.plot([h["front_housing_x0"] - 5, h["rear_housing_x1"] + 5], [0, 0], "-.", color="0.4", lw=0.6)
    H6 = iso(ISO_HOLE, "H6", h["bearing_bore"])
    _dim(ax, h["front_housing_x0"] + 3, 0, h["front_housing_x0"] + 3, rb, f"d{h['bearing_bore']:.3f} H6 ({H6[0]:+d}/{H6[1]:+d} um)", offset=-6)
    _dim(ax, h["tunnel_x0"] + 15, 0, h["tunnel_x0"] + 15, 0.5 * h["tunnel_od"], f"d{h['tunnel_od']:.1f}", offset=-6)
    fits.append(dict(feature="bearing bores (front / rear)", nominal=f"d {h['bearing_bore']:.3f}", fit="H6", deviation_um=H6,
                     note=f"{brg['id']} outer ring, slight clearance for axial float; Ra 0.8; coaxial 0.010 to the tunnel bore"))
    fits.append(dict(feature="internal retaining ring groove", nominal=f"d {b['internal_ring_groove_d']:.2f} x {b['internal_ring_groove_w']:.2f}", fit=b["internal_ring"], deviation_um=(0, 60), note="DIN 472 groove H13"))
    fits.append(dict(feature="o-ring groove", nominal=f"depth {h['oring_groove_depth']:.2f} x width {h['oring_groove_width']:.2f}", fit=h["oring"], deviation_um=(0, 50),
                     note="static face seal, groove Ra 1.6"))
    fits.append(dict(feature="labyrinth seal", nominal=f"{h['labyrinth_teeth']} teeth, radial clearance {h['labyrinth_clearance']:.2f}", fit="running clearance", deviation_um=(-20, 20),
                     note="clearance set at assembly against the shaft; tooth tip 0.3 wide"))
    fits.append(dict(feature="tunnel bore", nominal=f"d {h['tunnel_id']:.2f}", fit="H7", deviation_um=iso(ISO_HOLE, "H7", h["tunnel_id"]), note="locates both housings: coaxiality datum C"))
    _frame(ax, f"BEARING HOUSINGS AND TUNNEL  {h['material']}  half section", "datum C: tunnel bore; bearing bores coaxial 0.010 C; faces square 0.02; unspecified +/-0.1")
    return fits


def casing(sheet: dict, ax) -> list[dict]:
    c = sheet["casing"]
    r_o = c["r_outer"]; r_i = r_o - c["wall"]; x0, x1 = c["x0"], c["x1"]
    ax.fill([x0, x1, x1, x0], [r_i, r_i, r_o, r_o], color="#dfe8dc", ec="k", lw=0.9)
    for xf in c["flange_x"]:
        ax.fill([xf - 0.5 * c["flange_thickness"], xf + 0.5 * c["flange_thickness"], xf + 0.5 * c["flange_thickness"], xf - 0.5 * c["flange_thickness"]],
                [r_o, r_o, r_o + c["flange_width"], r_o + c["flange_width"]], color="#dfe8dc", ec="k", lw=0.9)
        ax.plot([xf, xf], [r_o + 0.5 * c["flange_width"], r_o + 0.5 * c["flange_width"]], "k+", ms=6)
    if c.get("bleed_port"):
        bp = c["bleed_port"]
        ax.fill([bp["x"] - 0.5 * bp["boss_od"], bp["x"] + 0.5 * bp["boss_od"], bp["x"] + 0.5 * bp["boss_od"], bp["x"] - 0.5 * bp["boss_od"]],
                [r_o, r_o, r_o + bp["boss_h"], r_o + bp["boss_h"]], color="#dfe8dc", ec="k", lw=0.9)
        ax.text(bp["x"], r_o + bp["boss_h"] + 2, f"bleed port d{bp['d']:.1f}", fontsize=7, ha="center")
    ax.plot([x0 - 5, x1 + 5], [0, 0], "-.", color="0.4", lw=0.6)
    _dim(ax, x0, r_o + c["flange_width"] + 2, x1, r_o + c["flange_width"] + 2, f"{x1-x0:.2f}", offset=6)
    _dim(ax, x0 + 15, 0, x0 + 15, r_o, f"d{2*r_o:.2f} outer, wall {c['wall']:.2f}", offset=-8)
    fits = [dict(feature="flange faces", nominal=f"{len(c['flange_x'])} flanges, {c['flange_thickness']:.1f} thick, {c['n_bolts']} x {c['screw']} on the bolt circle", fit="-", deviation_um=None,
                 note="flatness 0.05; bolt circle position 0.1; faces square to the axis 0.05"),
            dict(feature="shell", nominal=f"d {2*r_o:.2f} x wall {c['wall']:.2f}", fit="rolled / spun sheet", deviation_um=(-100, 100), note="roundness 0.2; weld or roll seam ground flush"),
            dict(feature="diffuser / turbine shroud pilots", nominal="from the housing drawings", fit="H7 / h6", deviation_um=None, note="concentricity 0.05 to the bearing tunnel (drives the tip clearance stack, MFG-2)")]
    _frame(ax, f"CASING  {c['material']}  half section", "sheet metal; hydrostatic 1.5 x P3 proof; unspecified +/-0.2")
    return fits


def write(design, out_dir=None) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    o = design.outputs()
    sheet = o["geometry"]["sheet"]
    brg = o["rotor"]["bearing"]
    out = Path(out_dir or (Path(design.dir) / "handoff" / "drawings"))
    out.mkdir(parents=True, exist_ok=True)
    files, tables = {}, {}
    for name, fn, figsize in (("shaft", lambda ax: shaft(sheet, brg, ax), (12, 4)), ("housings", lambda ax: housings(sheet, brg, ax), (12, 4)),
                              ("casing", lambda ax: casing(sheet, ax), (12, 5))):
        fig, ax = plt.subplots(figsize=figsize, dpi=120)
        tables[name] = fn(ax)
        fig.tight_layout()
        for ext in ("svg", "png"):
            p = out / f"{name}.{ext}"; fig.savefig(p, format=ext); files[f"{name}.{ext}"] = str(p)
        plt.close(fig)
    L = [f"# Manufacturing drawings: {design.doc['name']} v{design.store.version:04d}", "",
         f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} from the geometry sheet.  Fits per ISO 286; deviations in um.", ""]
    for name, rows in tables.items():
        L += [f"## {name}", "", f"![{name}]({name}.png)", "", "| feature | nominal | fit | deviation [um] | note |", "|---|---|---|---|---|"]
        for r in rows:
            dev = "-" if r["deviation_um"] is None else f"{r['deviation_um'][0]:+d} / {r['deviation_um'][1]:+d}"
            L.append(f"| {r['feature']} | {r['nominal']} | {r['fit']} | {dev} | {r['note']} |")
        L.append("")
    (out / "drawings.md").write_text("\n".join(L), encoding="utf-8")
    files["drawings.md"] = str(out / "drawings.md")
    return dict(dir=str(out), files=files, tables=tables)
