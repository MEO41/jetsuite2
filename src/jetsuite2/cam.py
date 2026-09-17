"""CAM-ready impeller package (roadmap section 9): the blade surfaces the machining software needs, the hub / shroud
revolution surfaces, the fillet specification, and an attempt to apply the blade-root fillet on the analysis solid.

The analysis solid is sharp-cornered by design (blades fused onto the hub).  For 5-axis flank milling the CAM
system wants: the suction / pressure surfaces of one main blade and one splitter as ordered point grids (span x
chord), the hub and shroud meridional curves, the blade count / pitch, the fillet radius and the tip thickness.
This module writes those (CSV grids + STEP of the blade solids and the hub) and then tries a fillet with the
OCC fillet builder on the edges the blade shares with the hub.  If the fillet fails (it often does on wrapped
blades with thin trailing edges), the sharp solid is exported and the failure is reported; the CAM package is
complete either way, because a CAM system applies the root fillet from the specification, not from the STEP.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def _spline_hub_solid(profile_mm: list, hub_curve: np.ndarray):
    """Hub of revolution whose gas-path contour is a single B-spline edge (the rest of the closed profile stays
    straight): one revolved face under the blades instead of one cone per profile segment."""
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Ax1, gp_Dir
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    prof = [tuple(map(float, p)) for p in profile_mm]
    hc = [tuple(map(float, p)) for p in np.asarray(hub_curve)]
    i0 = next(i for i, p in enumerate(prof) if abs(p[0] - hc[0][0]) < 1e-6 and abs(p[1] - hc[0][1]) < 1e-6)
    i1 = next(i for i, p in enumerate(prof) if abs(p[0] - hc[-1][0]) < 1e-6 and abs(p[1] - hc[-1][1]) < 1e-6)
    arr = TColgp_HArray1OfPnt(1, len(hc))
    for k, (x, r) in enumerate(hc, 1):
        arr.SetValue(k, gp_Pnt(x, r, 0.0))
    interp = GeomAPI_Interpolate(arr, False, 1e-4)
    interp.Perform()
    spline_edge = BRepBuilderAPI_MakeEdge(interp.Curve()).Edge()
    wire = BRepBuilderAPI_MakeWire()
    seq = list(range(i1, len(prof))) + list(range(0, i0 + 1))
    for a_, b_ in zip(seq[:-1], seq[1:]):
        pa, pb = prof[a_], prof[b_]
        if abs(pa[0] - pb[0]) < 1e-9 and abs(pa[1] - pb[1]) < 1e-9:
            continue
        wire.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(pa[0], pa[1], 0.0), gp_Pnt(pb[0], pb[1], 0.0)).Edge())
    wire.Add(spline_edge)
    face = BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()
    rev = BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), 2 * math.pi).Shape()
    return cq.Shape.cast(rev)


def _fillet_impeller(sheet: dict, blades: list, radius_mm: float, hub_curve, verbose=None):
    """Fuse the blades onto the spline hub and fillet the blade-root edges.  Returns (shape or None, n_edges, note)."""
    import cadquery as cq
    from .cad import cadlib
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_BSplineSurface, GeomAbs_SurfaceOfRevolution
    hub = _spline_hub_solid(sheet["hub_profile"], hub_curve)
    if not cadlib.valid(hub) or cadlib.volume(hub) <= 0:
        return None, 0, "spline hub revolve invalid"
    fused, ok, msg = cadlib.fuse_checked(hub, blades, "impeller on spline hub")
    if not ok:
        return None, 0, "blade fuse on the spline hub failed (" + str(msg) + ")"
    solid = fused
    v0 = cadlib.volume(solid)
    root_edges = []
    for e in solid.Edges():
        fl = list(e.ancestors(solid, "Face"))
        if len(fl) != 2:
            continue
        kinds = [int(BRepAdaptor_Surface(f.wrapped).GetType()) for f in fl]
        is_blade = [k == int(GeomAbs_BSplineSurface) for k in kinds]
        is_hub = [k == int(GeomAbs_SurfaceOfRevolution) for k in kinds]
        if (is_blade[0] and is_hub[1]) or (is_blade[1] and is_hub[0]):
            root_edges.append(e)
    if not root_edges:
        return None, 0, "no blade-root edges found on the spline hub"
    long_edges = [e for e in root_edges if e.Length() > 4.0]          # suction / pressure root curves (the caps are < 2 mm)
    # fallback ladder: full chain at the spec radius, then the long curves only, then a smaller radius
    attempts = [(radius_mm, root_edges, "all root edges"), (radius_mm, long_edges, "suction/pressure root curves only"),
                (0.6 * radius_mm, long_edges, "suction/pressure root curves only, 0.6 x radius")]
    last = ""
    for r_try, edges, label in attempts:
        if not edges:
            continue
        if verbose:
            verbose(f"  filleting {len(edges)} blade-root edges at r {r_try:.2f} mm ({label}) ...")
        mk = BRepFilletAPI_MakeFillet(solid.wrapped)
        for e in edges:
            mk.Add(r_try, e.wrapped)
        try:
            mk.Build()
            ok = mk.IsDone()
        except Exception as ex:  # noqa: BLE001
            ok, last = False, f"{type(ex).__name__}"
        if not ok:
            last = f"OCC fillet builder failed ({label}, r {r_try:.2f} mm, {len(edges)} edges)"
            continue
        fsh = cq.Shape.cast(mk.Shape())
        v1 = cadlib.volume(fsh)
        if cadlib.valid(fsh) and 0.99 * v0 < v1 < 1.05 * v0:
            return fsh, len(edges), f"OCC fillet r {r_try:.2f} mm on {len(edges)} blade-root edges ({label}); volume +{(v1 / v0 - 1) * 100:.2f} %"
        last = f"fillet result invalid ({label}: valid={cadlib.valid(fsh)}, volume ratio {v1 / v0:.3f})"
    return None, len(root_edges), last


def write(design, out_dir=None, try_fillet: bool = True, verbose=None) -> dict:
    import cadquery as cq
    from .cad import cadlib, impeller as imp
    o = design.outputs()
    sheet = dict(o["geometry"]["sheet"]["impeller"])
    sheet["splitter_start"] = 1.0 - float(sheet["splitter_length_frac"])
    mfg = o.get("manufacturing", {}).get("impeller_machining", {})
    fillet_mm = float(mfg.get("fillet_mm", 1.0))
    out = Path(out_dir or (Path(design.dir) / "handoff" / "impeller_cam"))
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    # ---- surfaces as ordered grids (mm), one main blade and one splitter at theta = 0
    ss, ps, th_te = imp.camber_grids(sheet)
    np.savetxt(out / "main_blade_suction.csv", ss.reshape(-1, 3), delimiter=",", header="x_mm,y_mm,z_mm (span-major, chord-minor; %d x %d)" % ss.shape[:2], comments="# ")
    np.savetxt(out / "main_blade_pressure.csv", ps.reshape(-1, 3), delimiter=",", header="x_mm,y_mm,z_mm (span-major, chord-minor; %d x %d)" % ps.shape[:2], comments="# ")
    files.update(main_blade_suction="main_blade_suction.csv", main_blade_pressure="main_blade_pressure.csv")
    if int(sheet["n_splitter"]) > 0:
        ss2, ps2, _ = imp.camber_grids(sheet, splitter=True)
        np.savetxt(out / "splitter_suction.csv", ss2.reshape(-1, 3), delimiter=",", header="x_mm,y_mm,z_mm", comments="# ")
        np.savetxt(out / "splitter_pressure.csv", ps2.reshape(-1, 3), delimiter=",", header="x_mm,y_mm,z_mm", comments="# ")
        files.update(splitter_suction="splitter_suction.csv", splitter_pressure="splitter_pressure.csv")
    hub = imp.hub_curve_from_profile(sheet["hub_profile"], sheet["r1h"], sheet["r2"])
    np.savetxt(out / "hub_curve.csv", np.asarray(hub), delimiter=",", header="x_mm,r_mm (meridional hub curve, eye -> exit)", comments="# ")
    np.savetxt(out / "shroud_curve.csv", np.asarray(sheet["shroud_curve"]), delimiter=",", header="x_mm,r_mm (meridional shroud curve incl. clearance)", comments="# ")
    files.update(hub_curve="hub_curve.csv", shroud_curve="shroud_curve.csv")
    # ---- solids: hub and one blade as STEP, plus the fused impeller (sharp), plus the fillet attempt
    res = imp.build_impeller(sheet, verbose=verbose)
    hub_solid = res["hub"]; blade = res["blades"][0]; shape = res["shape"]
    cq.exporters.export(cq.Workplane().add(hub_solid), str(out / "hub.step"))
    cq.exporters.export(cq.Workplane().add(blade), str(out / "main_blade.step"))
    cq.exporters.export(cq.Workplane().add(shape), str(out / "impeller_sharp.step"))
    files.update(hub="hub.step", main_blade="main_blade.step", impeller_sharp="impeller_sharp.step")
    fillet = dict(radius_mm=fillet_mm, applied=False, note="")
    if try_fillet:
        # The analysis hub is a polyline revolve (one cone per profile segment), which fragments every blade root into
        # hundreds of short intersection edges the fillet builder cannot chain.  For the CAM solid the gas-path hub is
        # rebuilt as ONE spline surface of revolution, the blades fused onto it, and the root edges selected by face
        # ancestry (a B-spline blade face meeting the hub face).
        try:
            fsh, n_edges, note = _fillet_impeller(sheet, res["blades"], fillet_mm, hub, verbose)
            fillet["edges"] = n_edges
            if fsh is not None:
                cq.exporters.export(cq.Workplane().add(fsh), str(out / "impeller_filleted.step"))
                files["impeller_filleted"] = "impeller_filleted.step"
                fillet.update(applied=True, note=note)
            else:
                fillet["note"] = note + "; sharp solid exported"
        except Exception as e:  # noqa: BLE001
            fillet["note"] = f"fillet attempt raised {type(e).__name__}: {e}; sharp solid exported"
    spec = dict(design=design.doc["name"], version=design.store.version, at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                material=sheet["material"], n_main=int(sheet["n_main"]), n_splitter=int(sheet["n_splitter"]), pitch_deg=360.0 / int(sheet["n_main"]),
                wrap_deg=res["wrap_deg"], D2_mm=2 * sheet["r2"], r1s_mm=sheet["r1s"], r1h_mm=sheet["r1h"], b2_mm=sheet["b2"], axial_length_mm=sheet["axial_length"],
                blade_thickness_mm=dict(root=sheet["t_root"], tip=sheet["t_tip"]), tip_clearance_mm=sheet["tip_clearance"],
                fillet=fillet, process=mfg.get("process"), passage_width_min_mm=mfg.get("passage_width_min_mm"), surface_Ra_um=mfg.get("surface_Ra_um"),
                machining_notes=["flank-mill the suction and pressure surfaces from the CSV grids (span-major order)",
                                 f"root fillet r {fillet_mm} mm applied by the CAM system along the hub intersection", "leave 0.1 mm on the shroud contour for the final tip-clearance grind",
                                 "balance to the grade in manufacturing.balance after machining"], files=files, cad_notes=res["notes"])
    (out / "cam_spec.json").write_text(json.dumps(spec, indent=1, default=float), encoding="utf-8")
    files["cam_spec"] = "cam_spec.json"
    return dict(dir=str(out), files=files, fillet=fillet)
