"""CadQuery / OCCT helpers shared by the part builders.

Units: millimetres.  Engine axis = +X (aft), x = 0 at the impeller nose.
Every boolean result is checked by volume, because a silent OCCT boolean
failure returns a plausible-looking shape (boomsonic_v0 lesson).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCP.BRepFill import BRepFill
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface
from OCP.GeomAbs import GeomAbs_Shape
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.gp import gp_Pnt
from OCP.ShapeFix import ShapeFix_Solid, ShapeFix_Shape
from OCP.TopoDS import TopoDS
from OCP.TopAbs import TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape
from OCP.BRep import BRep_Builder


class CadError(RuntimeError):
    pass


# ------------------------------------------------------------------ basics
def revolve(profile, angle=360.0) -> cq.Solid:
    """Closed (x, r) profile [mm] revolved about the X axis."""
    pts = [(float(x), float(r)) for x, r in profile]
    # drop consecutive duplicates
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > 1e-6 or abs(p[1] - clean[-1][1]) > 1e-6:
            clean.append(p)
    if abs(clean[0][0] - clean[-1][0]) < 1e-6 and abs(clean[0][1] - clean[-1][1]) < 1e-6:
        clean.pop()
    wp = cq.Workplane("XY").polyline(clean).close().revolve(angle, (0, 0, 0), (1, 0, 0))
    return wp.val()


def ring(x0, x1, r_out, r_in=0.0) -> cq.Solid:
    if r_in <= 1e-9:
        return revolve([(x0, 0.0), (x0, r_out), (x1, r_out), (x1, 0.0)])
    return revolve([(x0, r_in), (x0, r_out), (x1, r_out), (x1, r_in)])


def cylinder_x(x0, length, r) -> cq.Solid:
    return cq.Solid.makeCylinder(r, length, cq.Vector(x0, 0, 0), cq.Vector(1, 0, 0))


def rotate_x(shape, deg):
    return shape.rotate((0, 0, 0), (1, 0, 0), deg)


def pattern(shape, n: int, offset_deg: float = 0.0) -> cq.Compound:
    return cq.Compound.makeCompound([rotate_x(shape, offset_deg + 360.0 * k / n) for k in range(n)])


def valid(shape) -> bool:
    try:
        return BRepCheck_Analyzer(shape.wrapped).IsValid()
    except Exception:
        return False


def volume(shape) -> float:
    try:
        return float(shape.Volume())
    except Exception:
        return float("nan")


def fix(shape):
    sf = ShapeFix_Shape(shape.wrapped)
    sf.Perform()
    return cq.Shape.cast(sf.Shape())


def fuse_checked(base, tools: list, label: str, tol_frac: float = 0.02):
    """Fuse base with tools; verify the result is valid and its volume lies between
    V_base and V_base + sum(V_tools) (overlaps make it smaller than the sum).
    Returns (shape, ok)."""
    v0 = volume(base)
    vt = sum(volume(t) for t in tools)
    try:
        res = base.fuse(*tools) if tools else base
        res = res.clean()
    except Exception as e:  # noqa: BLE001
        return None, False, f"{label}: fuse raised {type(e).__name__}"
    v = volume(res)
    ok = valid(res) and v > v0 * (1 - tol_frac) and v <= (v0 + vt) * (1 + tol_frac)
    return res, ok, f"{label}: fused volume {v/1e3:.2f} cm3 (base {v0/1e3:.2f} + tools {vt/1e3:.2f})"


def cut_checked(base, tool, label: str):
    v0 = volume(base)
    try:
        res = base.cut(tool).clean()
    except Exception as e:  # noqa: BLE001
        return base, False, f"{label}: cut raised {type(e).__name__}"
    v = volume(res)
    ok = valid(res) and 0 < v <= v0 * (1 + 1e-6)
    return res, ok, f"{label}: cut {(v0 - v)/1e3:.3f} cm3"


# --------------------------------------------------------- blade surfaces
def bspline_surface(grid: np.ndarray, deg_min=3, deg_max=8, tol=1e-3):
    """grid: (ns, nc, 3) points -> Geom_BSplineSurface through them."""
    ns, nc = grid.shape[:2]
    arr = TColgp_Array2OfPnt(1, ns, 1, nc)
    for i in range(ns):
        for j in range(nc):
            arr.SetValue(i + 1, j + 1, gp_Pnt(*map(float, grid[i, j])))
    return GeomAPI_PointsToBSplineSurface(arr, deg_min, deg_max, GeomAbs_Shape.GeomAbs_C2, tol).Surface()


def _edge_iso(face_surface, first: bool, along_u: bool):
    """Boundary edge of a B-spline surface as a TopoDS_Edge (u-iso or v-iso at first/last)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    u1, u2, v1, v2 = face_surface.Bounds()
    if along_u:   # curve at constant v (row)
        curve = face_surface.VIso(v1 if first else v2)
    else:         # curve at constant u (column)
        curve = face_surface.UIso(u1 if first else u2)
    return BRepBuilderAPI_MakeEdge(curve).Edge()


def blade_solid_from_grids(ss: np.ndarray, ps: np.ndarray, sew_tol=2e-2):
    """Blade solid from suction and pressure side point grids (n_span, n_chord, 3).

    Rows (index 0) run root -> tip, columns (index 1) run LE -> TE.  The four
    open sides (LE, TE, root, tip) are closed by ruled faces between the
    matching boundary edges of the two surfaces, then sewn into a solid."""
    S_ss, S_ps = bspline_surface(ss), bspline_surface(ps)
    faces = [BRepBuilderAPI_MakeFace(S_ss, 1e-6).Face(), BRepBuilderAPI_MakeFace(S_ps, 1e-6).Face()]
    # caps: root (first row / v1), tip (last row / v2), LE (first col / u1), TE (last col / u2)
    # PointsToBSplineSurface maps rows -> U and columns -> V
    for first, along_u in ((True, False), (False, False), (True, True), (False, True)):
        e1 = _edge_iso(S_ss, first, along_u)
        e2 = _edge_iso(S_ps, first, along_u)
        faces.append(BRepFill.Face_s(e1, e2))
    sew = BRepBuilderAPI_Sewing(sew_tol)
    for f in faces:
        sew.Add(f)
    sew.Perform()
    shell_shape = sew.SewedShape()
    exp = TopExp_Explorer(shell_shape, TopAbs_SHELL)
    if not exp.More():
        raise CadError("blade sewing produced no shell")
    shell = TopoDS.Shell_s(exp.Current())
    solid = BRepBuilderAPI_MakeSolid(shell).Solid()
    sf = ShapeFix_Solid(solid)
    sf.Perform()
    sol = cq.Shape.cast(sf.Solid())
    nf = len(sol.Faces())
    if nf != 6 or volume(sol) <= 0 or not valid(sol):
        raise CadError(f"blade solid degenerate: {nf} faces, volume {volume(sol):.3g}, valid={valid(sol)}")
    return sol


# ------------------------------------------------------------ 2-D sections
def naca_thickness(xc: np.ndarray, t_over_c: float, te_frac: float = 0.02) -> np.ndarray:
    """NACA 4-digit half-thickness distribution (per unit chord) with finite TE."""
    return 5 * t_over_c * (0.2969 * np.sqrt(xc) - 0.1260 * xc - 0.3516 * xc ** 2 + 0.2843 * xc ** 3
                           - (0.1036 - te_frac) * xc ** 4) / 2.0


def camber_section(chord: float, angle_in_deg: float, angle_out_deg: float, t_over_c: float,
                   n: int = 30, te_thickness: float = 0.0, le_radius_frac: float = 0.02) -> np.ndarray:
    """Closed 2-D blade section (x, y) [mm] with the blade angle varying linearly from
    angle_in to angle_out along the chord (angles from the axial direction), NACA
    thickness normal to the camber line.  Returns an (N, 2) array, counterclockwise."""
    s = np.linspace(0, 1, n)
    ang = np.radians(angle_in_deg + (angle_out_deg - angle_in_deg) * s)
    # integrate the camber line: dx = cos(a) dm, dy = sin(a) dm; scale so the axial extent = chord*cos(stagger)
    dm = 1.0 / (n - 1)
    x = np.concatenate([[0.0], np.cumsum(np.cos(ang[:-1]) * dm)])
    y = np.concatenate([[0.0], np.cumsum(np.sin(ang[:-1]) * dm)])
    L = math.hypot(x[-1], y[-1])
    x, y = x / L * chord, y / L * chord
    ht = naca_thickness(s, t_over_c, te_frac=0.0) * chord + 0.5 * te_thickness * s ** 2
    nx, ny = -np.sin(ang), np.cos(ang)
    up = np.c_[x + nx * ht, y + ny * ht]
    lo = np.c_[x - nx * ht, y - ny * ht]
    pts = np.vstack([up, lo[::-1][1:-1] if len(lo) > 2 else lo[::-1]])
    return pts


def polygon_prism(pts2d: np.ndarray, x0: float, length: float, plane_normal="X") -> cq.Solid:
    """Extrude a closed 2-D polygon (in the plane normal to X, coords (y, z)) along +X."""
    wp = cq.Workplane("YZ", origin=(x0, 0, 0)).polyline([tuple(map(float, p)) for p in pts2d]).close().extrude(length)
    return wp.val()


def loft_sections(section_wires: list, ruled: bool = True) -> cq.Solid:
    return cq.Solid.makeLoft(section_wires, ruled)


def wire_from_points(points3d) -> cq.Wire:
    pts = [cq.Vector(*map(float, p)) for p in points3d]
    return cq.Wire.makePolygon(pts, close=True)


# ---------------------------------------------------------------- caching
def export_brep(shape, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    BRepTools.Write_s(shape.wrapped, str(path))


def import_brep(path: Path):
    s = TopoDS_Shape()
    b = BRep_Builder()
    BRepTools.Read_s(s, str(path), b)
    return cq.Shape.cast(s)
