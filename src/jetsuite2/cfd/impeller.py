"""Impeller passage CFD (SU2, RANS SST, rotating frame) driven from the design state (roadmap section 5).

Domain: one blade pitch of the hub-to-shroud channel, bounded by two copies of the main-blade camber surface
placed a quarter pitch and five quarters of a pitch from the main blade (so the periodic faces run midway
between the main blade and the splitter and never touch metal), with an inlet extension ahead of the leading
edge and a short vaneless extension beyond the exit radius.  The blades inside the sector (one main blade
and one splitter) are subtracted.  Built in CadQuery from the same camber grids as the CAD and the through-flow.

Mesh: gmsh (OCC kernel) on the exported STEP, tetrahedra with size fields (finer on blade and shroud), rotational
periodicity imposed between the two camber-shaped faces.  Boundary markers: INLET, OUTLET, HUB, SHROUD, BLADE,
PER_A, PER_B.

Solver: SU2 v8 compressible RANS, SST, rotating frame about x, total-condition inlet, static-pressure outlet
iterated on the target mass flow, no-slip adiabatic walls; the shroud rotates with the frame (a shrouded-impeller
simplification of the unshrouded design -- stated in the result).  Wall functions on a coarse first cell.

Result: mass-averaged total pressure and temperature at inlet and outlet -> impeller total-total pressure ratio
and isentropic efficiency, ingested as ``compressor.eta_impeller_cfd`` and ``compressor.PR_cfd`` (L3).  The mesh is
coarse by design (minutes, not hours); the file ``cfd_case.json`` states the cell count, y+ estimate and residual
drop so the reader can judge what the number is worth.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


# ----------------------------------------------------------------------------- SU2 location
def su2_executable() -> str | None:
    for cand in (os.environ.get("JET_SU2_CFD"), shutil.which("SU2_CFD"), shutil.which("SU2_CFD.exe")):
        if cand and Path(cand).exists():
            return cand
    for base in (Path(__file__).resolve().parents[3] / "tools" / "su2", Path.home() / "SU2"):
        for name in ("SU2_CFD.exe", "SU2_CFD"):
            p = base / "bin" / name
            if p.exists():
                return str(p)
    return None


# ----------------------------------------------------------------------------- geometry
def _rot_x(pts, ang):
    c, s = math.cos(ang), math.sin(ang)
    out = pts.copy()
    out[..., 1] = c * pts[..., 1] - s * pts[..., 2]
    out[..., 2] = s * pts[..., 1] + c * pts[..., 2]
    return out


def _extended_camber(sheet: dict, hub: np.ndarray, shr: np.ndarray, x_min: float, r_max: float, n_span: int = 9, n_chord: int = 41):
    """Camber surface (n_span, n_chord_ext, 3) in mm built on the CAD's own blade streamlines (identical theta inside the
    blade), extended upstream along -x at the LE radius with the LE blade angle and outward radially at the TE with
    the backsweep, both continuing the theta integration (no kink).  Rows: the CAD's stations with the root row
    buried and the tip row outside the shroud (negative clearance in the sheet copy)."""
    from ..cad.impeller import camber_streamlines
    # root row buried and tip row outside the shroud by 15 % of r2: the ruled caps of the sector between rows one pitch
    # apart are chords that dip 1 - cos(pitch/2) (8 % for 8 blades) toward the axis, and must stay outside the channel
    margin = 0.15 * float(sheet["r2"])
    sheet = dict(sheet); sheet["tip_clearance"] = -margin
    streamlines, theta_te_ref, _ = camber_streamlines(sheet, n_span=n_span, n_chord=n_chord, embed=margin)
    beta_te = math.radians(float(sheet["backsweep"]))
    grid = []
    for pts, theta, m, tt in streamlines:
        b_le = math.radians(float(np.interp(tt, [0.0, 0.5, 1.0], [sheet["beta_le_hub"], sheet["beta_le_rms"], sheet["beta_le_shroud"]])))
        x0, r0 = pts[0]; x1, r1 = pts[-1]
        # upstream: n_up points from x_min to x0 at r0, theta decreasing backwards with tan(beta_le) dm / r
        n_up, n_dn = 12, 12
        xs_up = np.linspace(x_min, x0, n_up + 1)[:-1]
        th_up = theta[0] - np.cumsum(np.full(n_up, math.tan(b_le) * (x0 - x_min) / n_up / max(r0, 1e-3)))[::-1]
        up = np.c_[xs_up, np.full(n_up, r0), th_up]
        rs_dn = np.linspace(r1, r_max, n_dn + 1)[1:]
        th_dn = theta[-1] + np.cumsum(math.tan(beta_te) * np.diff(np.linspace(r1, r_max, n_dn + 1)) / (0.5 * (rs_dn + np.linspace(r1, r_max, n_dn + 1)[:-1])))
        dn = np.c_[np.full(n_dn, x1), rs_dn, th_dn]
        mid = np.c_[pts[:, 0], pts[:, 1], theta]
        xrt = np.concatenate([up, mid, dn], axis=0)
        grid.append(np.c_[xrt[:, 0], xrt[:, 1] * np.cos(xrt[:, 2]), xrt[:, 1] * np.sin(xrt[:, 2])])
    return np.array(grid), theta_te_ref


def _spline_channel(hub: np.ndarray, shr: np.ndarray, x_in: float, r_out: float):
    """Meridional channel revolved 360 deg: straight inlet run, spline hub, radial exit run, spline shroud."""
    import cadquery as cq
    from OCP.gp import gp_Pnt, gp_Ax1, gp_Dir
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol

    def spline(pts):
        arr = TColgp_HArray1OfPnt(1, len(pts))
        for k, (x, r) in enumerate(pts, 1):
            arr.SetValue(k, gp_Pnt(float(x), float(r), 0.0))
        it = GeomAPI_Interpolate(arr, False, 1e-4)
        it.Perform()
        return BRepBuilderAPI_MakeEdge(it.Curve()).Edge()

    def line(a, b):
        return BRepBuilderAPI_MakeEdge(gp_Pnt(float(a[0]), float(a[1]), 0.0), gp_Pnt(float(b[0]), float(b[1]), 0.0)).Edge()

    def dedup(pts):
        out = [pts[0]]
        for q in pts[1:]:
            if abs(q[0] - out[-1][0]) > 1e-6 or abs(q[1] - out[-1][1]) > 1e-6:
                out.append(q)
        return out
    hub_pts, shr_pts = dedup([tuple(p) for p in hub]), dedup([tuple(p) for p in shr])
    wire = BRepBuilderAPI_MakeWire()
    wire.Add(line((x_in, hub_pts[0][1]), hub_pts[0]))
    wire.Add(spline(hub_pts))
    wire.Add(line(hub_pts[-1], (hub_pts[-1][0], r_out)))
    wire.Add(line((hub_pts[-1][0], r_out), (shr_pts[-1][0], r_out)))
    wire.Add(line((shr_pts[-1][0], r_out), shr_pts[-1]))
    wire.Add(spline(shr_pts[::-1]))
    wire.Add(line(shr_pts[0], (x_in, shr_pts[0][1])))
    wire.Add(line((x_in, shr_pts[0][1]), (x_in, hub_pts[0][1])))
    face = BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()
    rev = BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), 2 * math.pi).Shape()
    return cq.Shape.cast(rev)


def build_domain(design, out_dir: Path, x_in_ext: float = 0.6, r_out_ext: float = 1.12, verbose=None) -> dict:
    """Fluid domain STEP: sector between two camber-surface copies (+pitch/4, +5 pitch/4), hub, shroud, inlet and
    outlet extensions, minus the blades inside.  Lengths in mm (CAD convention)."""
    import cadquery as cq
    from ..cad import cadlib, impeller as imp
    o = design.outputs()
    sheet = dict(o["geometry"]["sheet"]["impeller"])
    sheet["splitter_start"] = 1.0 - float(sheet["splitter_length_frac"])
    n_main, n_spl = int(sheet["n_main"]), int(sheet["n_splitter"])
    pitch = 2 * math.pi / n_main
    r1s, r1h, r2, L = sheet["r1s"], sheet["r1h"], sheet["r2"], sheet["axial_length"]
    # meridional channel: hub curve and shroud curve, extended upstream (axial) and outward (radial) for the exits
    hub = np.asarray(imp.hub_curve_from_profile(sheet["hub_profile"], r1h, r2), float)
    shr = np.asarray(sheet["shroud_curve"], float)
    x_in = -x_in_ext * r1s
    r_out = r_out_ext * r2
    x_hub_end, x_shr_end = hub[-1, 0], shr[-1, 0]
    # channel of revolution with spline hub and shroud (one surface each): a polyline revolve gives one cone per
    # segment and trims the two periodic faces into different curve counts
    channel = _spline_channel(hub, shr, x_in, r_out)
    # periodic cutter: a "thick blade" whose two faces are ONE smooth camber surface (blade angle law inside the blade,
    # angle held constant upstream of the LE and downstream of the TE) spanning the inlet and outlet extensions and a
    # margin below the hub / above the shroud.  Both faces are exact rotational copies, so the channel trims them
    # identically and the periodic mesh faces match node for node.
    cam, th_te = _extended_camber(sheet, hub, shr, x_in - 2.0, r_out + 2.0)
    face_a = _rot_x(cam, 0.25 * pitch)
    face_b = _rot_x(cam, 1.25 * pitch)
    sector = cadlib.blade_solid_from_grids(face_a, face_b)          # closed solid between the two camber copies
    if cadlib.volume(sector) <= 0 or not cadlib.valid(sector):
        raise RuntimeError("camber sector solid invalid")
    x_le = 0.0
    fluid = channel.intersect(sector)
    if not cadlib.valid(fluid) or cadlib.volume(fluid) <= 0:
        raise RuntimeError("fluid sector invalid")
    # blades inside the sector: the main blade at +pitch and the splitter at +pitch/2
    res = imp.build_impeller(sheet, verbose=None)
    main = res["blades"][0]
    blades = [cadlib.rotate_x(main, math.degrees(pitch))]
    if n_spl:
        ss2, ps2, _ = imp.camber_grids(sheet, splitter=True)
        blades.append(cadlib.rotate_x(cadlib.blade_solid_from_grids(ss2, ps2), math.degrees(0.5 * pitch)))
    v_before = cadlib.volume(fluid)
    for b in blades:
        fluid = fluid.cut(b)
    if not cadlib.valid(fluid):
        raise RuntimeError("blade subtraction produced an invalid fluid solid")
    try:
        cleaned = fluid.clean()                      # merge co-surface faces left by the sector fuse (periodic topology)
        if cadlib.valid(cleaned) and abs(cadlib.volume(cleaned) - cadlib.volume(fluid)) < 1e-6 * cadlib.volume(fluid):
            fluid = cleaned
    except Exception:  # noqa: BLE001
        pass
    out_dir.mkdir(parents=True, exist_ok=True)
    step = out_dir / "passage.step"
    cq.exporters.export(cq.Workplane().add(fluid), str(step))
    cam_x = cam[..., 0].ravel(); cam_r = np.hypot(cam[..., 1], cam[..., 2]).ravel(); cam_th = np.arctan2(cam[..., 2], cam[..., 1]).ravel()
    info = dict(step=str(step), pitch_deg=math.degrees(pitch), n_main=n_main, n_splitter=n_spl, x_in_mm=x_in, r_out_mm=r_out,
                r1s_mm=r1s, r1h_mm=r1h, r2_mm=r2, volume_cm3=cadlib.volume(fluid) / 1e3, blade_volume_removed_cm3=(v_before - cadlib.volume(fluid)) / 1e3,
                x_le_mm=x_le, theta_te_rad=float(th_te), cam_field=dict(x=cam_x.tolist(), r=cam_r.tolist(), theta=cam_th.tolist()),
                hub_curve=hub.tolist(), shroud_curve=shr.tolist())
    if verbose:
        verbose(f"  fluid sector {info['volume_cm3']:.1f} cm3, blades removed {info['blade_volume_removed_cm3']:.2f} cm3")
    return info


# ----------------------------------------------------------------------------- mesh
def mesh(step: Path, out_dir: Path, info: dict, size_mm: float = 1.5, size_blade_mm: float = 0.5, verbose=None) -> dict:
    """gmsh tetra mesh with markers and rotational periodicity; writes passage.su2 (metres)."""
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1 if verbose else 0)
    gmsh.model.add("passage")
    gmsh.model.occ.importShapes(str(step))
    gmsh.model.occ.synchronize()
    pitch = math.radians(info["pitch_deg"])
    r1h, r1s, r2, r_out, x_in = info["r1h_mm"], info["r1s_mm"], info["r2_mm"], info["r_out_mm"], info["x_in_mm"]
    faces = gmsh.model.getEntities(2)
    groups = dict(INLET=[], OUTLET=[], HUB=[], SHROUD=[], BLADE=[], PER_A=[], PER_B=[])
    cf = info["cam_field"]; cx, cr, cth = np.asarray(cf["x"]), np.asarray(cf["r"]), np.asarray(cf["theta"])
    hub_c, shr_c = np.asarray(info["hub_curve"], float), np.asarray(info["shroud_curve"], float)
    x_le, th_te = info["x_le_mm"], info["theta_te_rad"]

    def cam_theta(x, r):
        """camber theta at a meridional point: nearest camber-grid sample (the grid is dense)"""
        k = int(np.argmin((cx - x) ** 2 + (cr - r) ** 2))
        return cth[k]

    def wrap(a):
        return (a + math.pi) % (2 * math.pi) - math.pi

    unclassified = []

    def on_surface(tag):
        """a point ON the face (parametric centre): the centroid of a wrapped face lies off the surface"""
        try:
            b = gmsh.model.getParametrizationBounds(2, tag)
            u, v = 0.5 * (b[0][0] + b[1][0]), 0.5 * (b[0][1] + b[1][1])
            return tuple(gmsh.model.getValue(2, tag, [u, v]))
        except Exception:  # noqa: BLE001
            return tuple(gmsh.model.occ.getCenterOfMass(2, tag))

    for dim, tag in faces:
        x, y, z = on_surface(tag)
        r = math.hypot(y, z); th = math.atan2(z, y)
        bb = gmsh.model.getBoundingBox(dim, tag)
        dx = bb[3] - bb[0]
        ftype = gmsh.model.getType(dim, tag)
        if abs(x - x_in) < 0.5 and dx < 0.5:
            groups["INLET"].append(tag); continue
        if abs(r - r_out) < 0.03 * r_out and dx < 0.6 * r2:
            groups["OUTLET"].append(tag); continue
        if ftype == "Plane":
            # planar periodic faces of the inlet / outlet extensions: theta = 0.25 or 1.25 pitch (+ theta_te for the outlet)
            base = th_te if x > x_le + 0.5 and r > 0.8 * r2 else 0.0
            off = wrap(th - base)
            if abs(off - 0.25 * pitch) < 0.1 * pitch:
                groups["PER_A"].append(tag); continue
            if abs(off - 1.25 * pitch) < 0.1 * pitch:
                groups["PER_B"].append(tag); continue
        # camber-relative offset: periodic copies at 0.25 / 1.25 pitch, splitter at 0.5, main blade at 1.0
        off = wrap(th - cam_theta(x, r))
        k4 = off / (0.25 * pitch)
        rh = float(np.interp(x, hub_c[:, 0], hub_c[:, 1])); rs = float(np.interp(x, shr_c[:, 0], shr_c[:, 1]))
        near_hub = r <= rh + 0.08 * (rs - rh); near_shr = r >= rs - 0.08 * (rs - rh)
        if ftype != "Plane" and abs(k4 - 1.0) < 0.35:
            groups["PER_A"].append(tag)
        elif ftype != "Plane" and abs(k4 - 5.0) < 0.35:
            groups["PER_B"].append(tag)
        elif ftype != "Plane" and (abs(k4 - 2.0) < 0.6 or abs(k4 - 4.0) < 0.6) and not (near_hub or near_shr):
            groups["BLADE"].append(tag)
        elif near_hub or (x < x_le and r < 0.5 * (r1h + r1s)):
            groups["HUB"].append(tag)
        elif near_shr or (x < x_le and r >= 0.5 * (r1h + r1s)):
            groups["SHROUD"].append(tag)
        else:
            unclassified.append((tag, round(x, 1), round(r, 1), round(k4, 2), ftype))
    if unclassified and verbose:
        verbose(f"  unclassified faces -> BLADE: {unclassified[:8]}")
    groups["BLADE"] += [u[0] for u in unclassified]
    for name, tags in groups.items():
        if tags:
            gmsh.model.addPhysicalGroup(2, tags, name=name)
    vols = [t for _, t in gmsh.model.getEntities(3)]
    gmsh.model.addPhysicalGroup(3, vols, name="FLUID")
    # periodicity: PER_B = rotation of PER_A by one pitch about x
    c, s = math.cos(pitch), math.sin(pitch)
    affine = [1, 0, 0, 0, 0, c, -s, 0, 0, s, c, 0, 0, 0, 0, 1]
    # pair each PER_A face with the PER_B face whose centroid is its rotation by one pitch, and require matching topology
    periodic_pairs, unpaired = [], []
    def _com(tag):
        x, y, z = gmsh.model.occ.getCenterOfMass(2, tag); return np.array([x, y, z])
    def _rot(v):
        return np.array([v[0], c * v[1] - s * v[2], s * v[1] + c * v[2]])
    def _npts(tag):
        return len(gmsh.model.getBoundary([(2, tag)], recursive=True))
    b_left = list(groups["PER_B"])
    for ta in groups["PER_A"]:
        target = _rot(_com(ta))
        if not b_left:
            unpaired.append(ta); continue
        tb = min(b_left, key=lambda t: np.linalg.norm(_com(t) - target))
        if np.linalg.norm(_com(tb) - target) < 0.02 * r2 and _npts(ta) == _npts(tb):
            periodic_pairs.append((ta, tb)); b_left.remove(tb)
        else:
            unpaired.append((ta, tb, round(float(np.linalg.norm(_com(tb) - target)), 2), _npts(ta), _npts(tb)))
    for ta, tb in periodic_pairs:
        try:
            gmsh.model.mesh.setPeriodic(2, [tb], [ta], affine)
        except Exception as e:  # noqa: BLE001
            unpaired.append((ta, tb, f"{e}"))
    if verbose:
        verbose(f"  periodic pairs set: {len(periodic_pairs)}; unpaired / failed: {unpaired}")
    # sizes: blade and shroud fine, elsewhere coarse
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.4 * size_blade_mm)
    gmsh.option.setNumber("Mesh.MeshSizeMax", size_mm)
    f_dist = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(f_dist, "SurfacesList", groups["BLADE"] + groups["SHROUD"])
    f_thr = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(f_thr, "InField", f_dist)
    gmsh.model.mesh.field.setNumber(f_thr, "SizeMin", size_blade_mm); gmsh.model.mesh.field.setNumber(f_thr, "SizeMax", size_mm)
    gmsh.model.mesh.field.setNumber(f_thr, "DistMin", 0.5); gmsh.model.mesh.field.setNumber(f_thr, "DistMax", 6.0)
    gmsh.model.mesh.field.setAsBackgroundMesh(f_thr)
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)          # HXT
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.model.mesh.generate(3)
    n_nodes = len(gmsh.model.mesh.getNodes()[0])
    n_tets = sum(len(t) for et, t in zip(*gmsh.model.mesh.getElements(3)[:2]))
    # SU2 format in metres
    gmsh.option.setNumber("Mesh.ScalingFactor", 1e-3)
    su2 = out_dir / "passage.su2"
    gmsh.write(str(su2))
    gmsh.finalize()
    if verbose:
        verbose(f"  mesh: {n_nodes} nodes, {n_tets} tets; markers " + ", ".join(f"{k} {len(v)}" for k, v in groups.items()))
    return dict(su2=str(su2), n_nodes=n_nodes, n_tets=n_tets, markers={k: len(v) for k, v in groups.items()},
                periodic_pairs=len(periodic_pairs), periodic_unpaired=len(unpaired))


# ----------------------------------------------------------------------------- SU2 config
def write_config(design, out_dir: Path, mesh_info: dict, p_out_Pa: float, iters: int = 1500, euler: bool = False,
                 cfl: float = 0.5, cfl_adapt: tuple | None = None, ramp_start_Pa: float | None = None, ramp_iters: int | None = None,
                 restart: bool = False, name: str = "passage", solution: str = "restart_flow.dat") -> Path:
    """SU2 configuration.  ``cfl_adapt`` = (down, up, min, max) enables adaptive CFL; ``ramp_start_Pa`` = None disables the
    outlet ramp; ``restart`` continues from ``restart_flow.dat`` (phase 2 of a run).  The history and log carry ``name``."""
    o = design.outputs()
    cy, sp = o["cycle"], o["speed"]
    omega = sp["rpm"] * 2 * math.pi / 60
    # rotation sense: the blade wraps in +theta from LE to TE (CAD camber law), so a backswept wheel turns about -x
    sense = -1.0 if float(mesh_info.get("theta_te_deg", 1.0)) > 0 else 1.0
    T_fs, P_fs = cy["Tt2_K"], cy["Pt2_Pa"]
    comp = o["compressor"]
    U1 = omega * float(comp.get("r1rms_m", 0.5 * (comp["r1s_m"] + comp["r1h_m"])))
    U2 = omega * float(comp["r2_m"])
    W1 = float(comp.get("W1s_m_s", 250.0))
    T_rel_in = T_fs - float(comp.get("C1_m_s", 120.0)) ** 2 / 2009.0 + W1 ** 2 / 2009.0
    T_wall = 0.5 * (T_rel_in + T_rel_in + (U2 ** 2 - U1 ** 2) / 2009.0)
    mu = 1.716e-5 * (T_fs / 273.15) ** 1.5 * (273.15 + 110.4) / (T_fs + 110.4)
    V_fs = 0.3 * math.sqrt(1.4 * 287.058 * T_fs)
    Re = (P_fs / (287.058 * T_fs)) * V_fs * 2 * o["compressor"]["r2_m"] / mu
    cfg = f"""% jetsuite2 impeller passage, generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}
SOLVER= {'EULER' if euler else 'RANS'}
KIND_TURB_MODEL= {'NONE' if euler else 'SST'}
MATH_PROBLEM= DIRECT
RESTART_SOL= {'YES' if restart else 'NO'}
READ_BINARY_RESTART= {'NO' if solution.endswith('.csv') else 'YES'}
SYSTEM_MEASUREMENTS= SI
% rotating frame about x
GRID_MOVEMENT= ROTATING_FRAME
MOTION_ORIGIN= 0.0 0.0 0.0
ROTATION_RATE= {sense * omega:.4f} 0.0 0.0
MACH_NUMBER= 0.3
AOA= 0.0
FREESTREAM_PRESSURE= {cy['Pt2_Pa']:.1f}
FREESTREAM_TEMPERATURE= {cy['Tt2_K']:.2f}
FREESTREAM_TURBULENCEINTENSITY= 0.05
FREESTREAM_TURB2LAMVISCRATIO= 10.0
REF_ORIGIN_MOMENT_X= 0.0
REF_ORIGIN_MOMENT_Y= 0.0
REF_ORIGIN_MOMENT_Z= 0.0
REF_LENGTH= {2 * o['compressor']['r2_m']:.5f}
REF_AREA= 1.0
REF_DIMENSIONALIZATION= DIMENSIONAL
INIT_OPTION= TD_CONDITIONS
FREESTREAM_OPTION= TEMPERATURE_FS
REYNOLDS_NUMBER= {Re:.0f}
REYNOLDS_LENGTH= {2 * o['compressor']['r2_m']:.5f}
FLUID_MODEL= IDEAL_GAS
GAMMA_VALUE= 1.4
GAS_CONSTANT= 287.058
VISCOSITY_MODEL= SUTHERLAND
MU_REF= 1.716E-5
MU_T_REF= 273.15
SUTHERLAND_CONSTANT= 110.4
CONDUCTIVITY_MODEL= CONSTANT_PRANDTL
PRANDTL_LAM= 0.72
PRANDTL_TURB= 0.90
% boundaries
{'MARKER_EULER= ( HUB, SHROUD, BLADE )' if euler else 'MARKER_HEATFLUX= ( HUB, 0.0, SHROUD, 0.0, BLADE, 0.0 )'}
MARKER_INLET= ( INLET, {cy['Tt2_K']:.2f}, {cy['Pt2_Pa']:.1f}, 1.0, 0.0, 0.0 )
MARKER_OUTLET= ( OUTLET, {p_out_Pa:.1f} )
RAMP_OUTLET= {'YES' if ramp_start_Pa else 'NO'}
RAMP_OUTLET_COEFF= ( {ramp_start_Pa or p_out_Pa:.1f}, 10, {ramp_iters or max(int(0.6 * iters), 100)} )
MARKER_PERIODIC= ( PER_A, PER_B, 0.0, 0.0, 0.0, {math.degrees(2 * math.pi / mesh_info.get('n_main', 8)):.6f}, 0.0, 0.0, 0.0, 0.0, 0.0 )
MARKER_MONITORING= ( BLADE )
MARKER_ANALYZE= ( INLET, OUTLET )
MARKER_ANALYZE_AVERAGE= MASSFLUX

% numerics
NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CFL_NUMBER= {cfl}
CFL_ADAPT= {'YES' if cfl_adapt else 'NO'}
CFL_ADAPT_PARAM= ( {', '.join(str(v) for v in (cfl_adapt or (0.5, 1.1, 0.5, 4.0)))} )
ITER= {iters}
LINEAR_SOLVER= FGMRES
LINEAR_SOLVER_PREC= ILU
LINEAR_SOLVER_ERROR= 1E-4
LINEAR_SOLVER_ITER= 25
MGLEVEL= 0
CONV_NUM_METHOD_FLOW= ROE
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.05
TIME_DISCRE_FLOW= EULER_IMPLICIT
CONV_NUM_METHOD_TURB= SCALAR_UPWIND
MUSCL_TURB= NO
TIME_DISCRE_TURB= EULER_IMPLICIT
CONV_FIELD= RMS_DENSITY
CONV_RESIDUAL_MINVAL= -8
CONV_STARTITER= 50
% i/o
MESH_FILENAME= passage.su2
MESH_FORMAT= SU2
SOLUTION_FILENAME= {solution}
RESTART_FILENAME= restart_{name}.dat
OUTPUT_FILES= ( RESTART, PARAVIEW, SURFACE_CSV )
VOLUME_FILENAME= flow
SURFACE_FILENAME= surface_flow
CONV_FILENAME= history_{name}
HISTORY_OUTPUT= ( ITER, RMS_RES, FLOW_COEFF, SURFACE_MASSFLOW, SURFACE_TOTAL_PRESSURE, SURFACE_TOTAL_TEMPERATURE, SURFACE_STATIC_PRESSURE, AVG_MASSFLOW )
OUTPUT_WRT_FREQ= 200
SCREEN_OUTPUT= ( INNER_ITER, RMS_DENSITY, {'RMS_ENERGY' if euler else 'RMS_TKE'}, SURFACE_MASSFLOW, SURFACE_TOTAL_PRESSURE )
SCREEN_WRT_FREQ_INNER= 10
"""
    p = out_dir / f"{name}.cfg"
    p.write_text(cfg, encoding="utf-8")
    return p


# ----------------------------------------------------------------------------- run + post
def run_su2(cfg: Path, threads: int = 4, verbose=None) -> dict:
    exe = su2_executable()
    if not exe:
        return dict(ok=False, error="SU2_CFD not found (set JET_SU2_CFD or put the binaries in tools/su2/bin)")
    env = dict(os.environ, OMP_NUM_THREADS=str(threads))
    log = cfg.with_suffix(".log")
    with open(log, "w", encoding="utf-8") as f:
        r = subprocess.run([exe, "-t", str(threads), cfg.name], cwd=str(cfg.parent), stdout=f, stderr=subprocess.STDOUT, env=env, timeout=6 * 3600)
    return dict(ok=r.returncode == 0, returncode=r.returncode, log=str(log), exe=exe)


def post(out_dir: Path, name: str = "passage") -> dict:
    """Read the history and return mass-averaged inlet / outlet totals and the derived impeller performance."""
    import csv
    hist = out_dir / f"history_{name}.csv"
    if not hist.exists():
        return dict(ok=False, error="no history.csv")
    rows = list(csv.DictReader(open(hist, encoding="utf-8")))
    if not rows:
        return dict(ok=False, error="empty history")
    last = {k.strip().strip('"'): v for k, v in rows[-1].items()}
    def g(*names):
        for n in names:
            for k, v in last.items():
                if k.replace(" ", "") == n.replace(" ", ""):
                    try:
                        return float(v)
                    except ValueError:
                        pass
        return None
    W_in = g("Avg_Massflow(INLET)", "Massflow(INLET)"); W_out = g("Avg_Massflow(OUTLET)", "Massflow(OUTLET)")
    Pt_in = g("Avg_TotalPress(INLET)", "TotalPressure(INLET)"); Pt_out = g("Avg_TotalPress(OUTLET)", "TotalPressure(OUTLET)")
    Tt_in = g("Avg_TotalTemp(INLET)", "TotalTemperature(INLET)"); Tt_out = g("Avg_TotalTemp(OUTLET)", "TotalTemperature(OUTLET)")
    rms = g("rms[Rho]", "rms_Rho")
    res = dict(ok=all(v is not None for v in (Pt_in, Pt_out, Tt_in, Tt_out)), W_in=W_in, W_out=W_out, Pt_in=Pt_in, Pt_out=Pt_out, Tt_in=Tt_in, Tt_out=Tt_out,
               rms_rho_last=rms, iterations=len(rows), columns=list(last.keys())[:30])
    if res["ok"] and Pt_in and Tt_in:
        PR = Pt_out / Pt_in
        T_ratio = Tt_out / Tt_in
        eta = (PR ** (0.4 / 1.4) - 1.0) / max(T_ratio - 1.0, 1e-6)
        res.update(PR_tt=PR, T_ratio=T_ratio, eta_tt=eta)
    return res


def run_case(design, iters: int = 1500, threads: int = 4, size_mm: float = 1.5, size_blade_mm: float = 0.5, verbose=None, solve: bool = True,
             mesher: str = "hmesh", euler: bool = False, throttle_start: float = 1.10, max_throttle: int = 12) -> dict:
    o = design.outputs()
    out = Path(design.dir) / "handoff" / "impeller_cfd"
    out.mkdir(parents=True, exist_ok=True)
    if mesher == "hmesh":
        from . import hmesh
        # RANS: wall-resolved pitchwise spacing (first cell ~0.02 mm).  SU2's node-centred moving no-slip wall puts the
        # blade's pressure work on the wall node, which only conduction through the first cell can carry away: with a
        # 0.35 mm first cell the pressure-side wall nodes run to 3000 K, with 0.02 mm they stay within 240-570 K.
        m = hmesh.build(design, out, verbose=verbose, rans=not euler, nk=22 if not euler else 14, nk_cluster=3.2 if not euler else 1.6)
        m["n_tets"] = m["n_hexes"]
        info = dict(mesher="hmesh", volume_cm3=None, **{k: m[k] for k in ("pitch_deg", "n_main", "n_splitter", "x_in_mm", "r_out_mm", "geometry")})
    else:
        info = build_domain(design, out, verbose=verbose)
        m = mesh(Path(info["step"]), out, info, size_mm=size_mm, size_blade_mm=size_blade_mm, verbose=verbose)
        info["mesher"] = "cad+gmsh (experimental: periodic faces may not match)"
    m["n_main"] = info["n_main"]
    # outlet static pressure from the mean line: impeller exit static at the extension radius ~ Pt2 * PR_imp * (p/Pt)_exit
    c, cy = o["compressor"], o["cycle"]
    Pt2_imp = cy["Pt2_Pa"] * c.get("PR_impeller_tt", cy["OPR"] * 1.06)
    M2 = float(c.get("M2_abs", 0.9)) * 0.85          # slightly decelerated at the extension radius
    p_out = Pt2_imp * (1 + 0.2 * M2 * M2) ** -3.5
    # ---- throttle continuation.  SU2 8.5 has no compressible mass-flow outlet and its outlet ramp acts only on the
    # Giles / Riemann boundaries, so the operating point is found by iterating the outlet static pressure.  The
    # lossless, slip-free wheel's speed line sits above the mean line: at the mean-line back pressure the exit runs
    # towards choke (three times the design flow, the choked inducer cannot feed it, the passage empties), while a
    # back pressure above the wheel's Euler head collapses the flow (surge).  Blocks of n_block iterations start
    # from the streamline-aligned initial field or the last healthy solution; a block is healthy when both surface
    # mass flows are within 0.3..2 x the target and agree within 25 %.  Choke -> raise p, collapse -> lower p
    # (bracketing), healthy -> secant towards the design passage flow (steps clamped to 8 %).
    W_target = cy["W_kg_s"] / info["n_main"]
    n_block = max(150, min(iters // 5, 400))
    init = Path(m.get("init", "passage_init.csv")).name
    case = dict(domain=info, mesh=m, p_out_meanline_Pa=p_out, target_mass_flow_kg_s=W_target,
                at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                solver="EULER (inviscid check)" if euler else "RANS-SST",
                initial_field="streamline-aligned, relative velocity along the blade camber, mean-line swirl (passage_init.csv)",
                numerics=f"Roe (AUSM+-up2 mishandles the rotating-frame grid velocity in SU2 8.5), MUSCL/Venkatakrishnan, implicit Euler CFL 2 (final block adaptive 1-5), {n_block} iterations per throttle block",
                rotation="about -x (blade wraps in +theta along the flow)" if float(m.get("theta_te_deg", 1.0)) > 0 else "about +x",
                simplifications=["shroud rotates with the frame (shrouded-impeller approximation)",
                                 "adiabatic walls; SU2 8.5 win64 pollutes the wall-node energy of walls moving normal to themselves in the rotating frame (docs/validation.md): the totals are NOT trusted and nothing is ingested until that is resolved",
                                 "static-pressure outlet iterated (throttle continuation) to the design passage mass flow +/- 2 %",
                                 "structured H-mesh, blade first cell 0.02 mm (RANS) / hub and shroud 0.25 mm (wall-function range), no tip clearance", "steady, single passage, no diffuser"],
                reference_L1=dict(eta_impeller_assumed=c.get("eta_impeller_assumed"), PR_impeller_tt=c.get("PR_impeller_tt")),
                throttle=[])
    if solve:
        p_k = throttle_start * p_out
        prev_sol = init
        healthy = []                   # (p, W) pairs from healthy blocks
        p_choke, p_surge = None, None  # bracket: highest p that choked, lowest p that collapsed
        final_done = False
        n_same, max_same = 0, 3        # blocks allowed at one pressure while the transient settles
        last_healthy_sol = None
        for k in range(max_throttle):
            name = f"passage_t{k}"
            last = (k == max_throttle - 1)
            converged_flow = bool(healthy) and abs(healthy[-1][1] - W_target) <= 0.02 * W_target
            final = converged_flow or last
            cfg_k = write_config(design, out, m, p_k, iters=n_block * (2 if final else 1), euler=euler, cfl=2.0,
                                 cfl_adapt=(0.5, 1.1, 1.0, 5.0) if final else None, ramp_start_Pa=None, restart=True, name=name, solution=prev_sol)
            run = run_su2(cfg_k, threads=threads, verbose=verbose)
            res = post(out, name) if run["ok"] else dict(ok=False)
            W_in, W_out = res.get("W_in"), res.get("W_out")
            W = None
            state = "failed"
            if res.get("ok") and W_in is not None and W_out is not None and np.isfinite(W_in) and np.isfinite(W_out):
                W_in, W_out = abs(W_in), abs(W_out)
                W = 0.5 * (W_in + W_out)
                hi, lo = max(W_in, W_out), min(W_in, W_out)
                if lo > 0.3 * W_target and hi < 2.0 * W_target and (hi - lo) <= 0.25 * hi:
                    state = "healthy"
                elif hi >= 2.0 * W_target or W_out > 1.5 * W_target:
                    state = "choke"
                else:
                    state = "collapse"
            step = dict(block=k, p_out_Pa=p_k, run_ok=run["ok"], state=state, W_kg_s=W, W_in=W_in, W_out=W_out,
                        PR_tt=res.get("PR_tt"), eta_tt=res.get("eta_tt"), rms_rho=res.get("rms_rho_last"), log=run.get("log"), final=final)
            case["throttle"].append(step)
            if verbose:
                verbose(f"  throttle block {k}: p_out {p_k:.0f} Pa -> {state}, W_in {W_in} W_out {W_out} (target {W_target:.4f}), PR_tt {res.get('PR_tt')}, eta_tt {res.get('eta_tt')}, rms {res.get('rms_rho_last')}")
            if state == "healthy":
                prev_sol = f"restart_{name}.dat"
                last_healthy_sol = prev_sol
                n_same = 0
                case["run"] = run
                case["result"] = res
                case["result"].update(p_out_Pa=p_k, W_kg_s=W, W_in=W_in, W_out=W_out)
                case["config"] = str(cfg_k)
                healthy.append((p_k, W))
                if final:
                    final_done = True
                    break
                if len(healthy) >= 2 and abs(healthy[-1][1] - healthy[-2][1]) > 1e-6 and abs(healthy[-1][0] - healthy[-2][0]) > 1.0:
                    slope = (healthy[-1][1] - healthy[-2][1]) / (healthy[-1][0] - healthy[-2][0])
                    if slope >= 0:
                        slope = -W_target / (0.25 * p_out)
                else:
                    slope = -W_target / (0.25 * p_out)
                p_new = p_k + (W_target - W) / slope
                p_new = min(max(p_new, 0.92 * p_k), 1.08 * p_k)
            elif state != "failed" and n_same < max_same - 1:
                # unhealthy but running: the pseudo-transient (the passage filling or draining) needs more iterations
                # at the same pressure before the state can be judged; continue from this block's own solution
                prev_sol = f"restart_{name}.dat"
                p_new = p_k
                n_same += 1
                if verbose:
                    verbose(f"    continuing at the same p_out (block {n_same + 1} of {max_same} at this pressure)")
            else:
                # judged: continue from this solution (physical continuation along the speed line) unless it failed
                prev_sol = f"restart_{name}.dat" if state != "failed" else (last_healthy_sol or init)
                if state == "choke" or (state == "failed" and healthy and healthy[-1][1] > W_target):
                    p_choke = max(p_choke or 0.0, p_k)
                    p_new = 1.12 * p_k
                else:
                    p_surge = min(p_surge or 1e12, p_k)
                    p_new = p_k / 1.12
                if p_choke is not None and p_surge is not None and p_surge > p_choke:
                    p_new = 0.5 * (p_choke + p_surge)
                n_same = 0
            p_k = p_new
        case["throttle_bracket"] = dict(p_choke=p_choke, p_surge=p_surge)
        r = case.get("result", {})
        trusted = bool(os.environ.get("JET_SU2_ROTATING_WALLS_OK"))   # set only when the rotating moving-wall energy defect is resolved
        if not trusted:
            case["note"] = ("SU2 8.5 win64: wall-node energy of walls moving normal to themselves is not conserved in the rotating frame "
                            "(validation.md, impeller passage CFD); totals reported for information, nothing written for ingest")
        if trusted and final_done and r.get("ok") and r.get("PR_tt") and abs(r["W_kg_s"] - W_target) <= 0.05 * W_target:
            n_it = sum(n_block * (2 if st.get("final") else 1) for st in case["throttle"])
            src = (f"SU2 8.5 {case['solver']} rotating frame, {m['n_tets']} hexes, {n_it} iters, W {r['W_kg_s']:.4f} kg/s (target {W_target:.4f}), "
                   f"p_out {r['p_out_Pa']:.0f} Pa, rms rho {r['rms_rho_last']}, {case['at']}; " + "; ".join(case["simplifications"][:2]))
            ing = [dict(stage="compressor", tier="L3", source=src, fields={"eta_impeller_cfd": r["eta_tt"], "PR_cfd": r["PR_tt"]})]
            (out / "ingest_impeller_cfd.json").write_text(json.dumps(ing, indent=1), encoding="utf-8")
            case["ingest_file"] = str(out / "ingest_impeller_cfd.json")
        elif r.get("ok"):
            case["note"] = f"last healthy block: W {r.get('W_kg_s')} vs target {W_target:.4f}; no converged operating point, nothing written for ingest"
        else:
            case["note"] = "no healthy throttle block; nothing written for ingest"
    (out / "cfd_case.json").write_text(json.dumps(case, indent=1, default=str), encoding="utf-8")
    return case
