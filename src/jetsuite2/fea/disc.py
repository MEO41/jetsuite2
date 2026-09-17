"""Turbine disc axisymmetric FE (CalculiX) at MCS and at the start-transient thermal gradient.

Mesh: the wheel's meridional profile (``outputs.rotor.turbine_disc_profile``, a closed polygon in
axial x / radius r) rasterised onto a structured CAX4 grid (cells whose centre is inside the
polygon).  Loads: centrifugal body force about the axis, the blade row's centrifugal pull as a
negative pressure on the rim face, and the nodal temperature field of the lumped rim/bore start
model at the instant of maximum rim-bore difference.  Constraint: axial fixity on the rear face of
the shaft stub (free radial growth).

Steps: (1) centrifugal at MCS; (2) centrifugal at MCS + start thermal gradient (the combination the
life stage assumes); (3) centrifugal at idle speed + start thermal gradient (the physical start instant).

Runs ``ccx`` natively if on PATH, else through WSL (``wsl -d <distro> -- ccx``).  Results are parsed
from the ``.dat`` element stress print and returned with the ingest file for
``mechanical.turbine.sigma_peak_Pa`` (L3, step 1) and ``life.sigma_bore_total_Pa`` (L3, step 2).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..library import materials


# ----------------------------------------------------------------------------- geometry / mesh
def _inside(poly: np.ndarray, px: float, py: float) -> bool:
    """Even-odd point-in-polygon."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > py) != (yj > py):
            xint = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < xint:
                inside = not inside
        j = i
    return inside


def reentrant_corners(profile_m) -> list[tuple[float, float]]:
    """Vertices where the section turns inward (interior angle > 180 deg): stress singularities in a sharp-cornered
    profile.  Returned as (r, x)."""
    poly = np.array(profile_m, float)
    n = len(poly)
    area2 = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    ccw = area2 > 0
    out = []
    for i in range(n):
        p0, p1, p2 = poly[i - 1], poly[i], poly[(i + 1) % n]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if (cross < 0) == ccw and abs(cross) > 1e-12:
            out.append((float(p1[1]), float(p1[0])))
    return out


def build_mesh(profile_m, cell_mm: float = 0.5, load_x_range=None) -> dict:
    """Structured CAX4 mesh of the profile polygon.  Returns nodes (id -> (r, x)), elements (id -> 4 node ids),
    node sets (stub rear face, rim face element list with faces) in metres."""
    poly = np.array(profile_m, float)                       # columns: x (axial), r (radius)
    xs, rs = poly[:, 0], poly[:, 1]
    h = cell_mm * 1e-3
    # grid lines: every vertex coordinate plus uniform refinement
    gx = np.unique(np.concatenate([xs, np.arange(xs.min(), xs.max() + h / 2, h)]))
    gr = np.unique(np.concatenate([rs, np.arange(rs.min(), rs.max() + h / 2, h)]))
    gx = gx[np.concatenate([[True], np.diff(gx) > 1e-5])]
    gr = gr[np.concatenate([[True], np.diff(gr) > 1e-5])]
    nid = {}
    nodes = {}
    elements = {}
    def node(i, j):
        key = (i, j)
        if key not in nid:
            nid[key] = len(nid) + 1
            nodes[nid[key]] = (float(gr[j]), float(gx[i]))       # (X = r, Y = x) for CAX elements (axis = Y)
        return nid[key]
    eid = 0
    cell_of = {}
    for i in range(len(gx) - 1):
        for j in range(len(gr) - 1):
            cx, cr = 0.5 * (gx[i] + gx[i + 1]), 0.5 * (gr[j] + gr[j + 1])
            if _inside(poly, cx, cr):
                eid += 1
                # counter-clockwise in the (X=r, Y=x) plane: (r0,x0) (r1,x0) (r1,x1) (r0,x1)
                elements[eid] = (node(i, j), node(i, j + 1), node(i + 1, j + 1), node(i + 1, j))
                cell_of[(i, j)] = eid
    r_rim = float(rs.max()); r_min = float(rs.min())
    # rim face: elements whose outer edge (r = r_rim) is a polygon boundary -> face 2 (nodes 2-3 at r1)
    if load_x_range is None:
        rim_faces = [(e, 2) for (i, j), e in cell_of.items() if abs(gr[j + 1] - r_rim) < 1e-9]
        rim_len = sum(gx[i + 1] - gx[i] for (i, j), e in cell_of.items() if abs(gr[j + 1] - r_rim) < 1e-9)
        load_area = 2 * math.pi * r_rim * rim_len
    else:
        # outer boundary of each x column inside the range (the blade-carrying hub surface of an impeller):
        # the topmost cell of the column gets the load on its outer face (face 2)
        x0, x1 = load_x_range
        rim_faces, rim_len, load_area = [], 0.0, 0.0
        for i in range(len(gx) - 1):
            xc = 0.5 * (gx[i] + gx[i + 1])
            if not (x0 - 1e-9 <= xc <= x1 + 1e-9):
                continue
            col = [j for j in range(len(gr) - 1) if (i, j) in cell_of]
            if not col:
                continue
            j = max(col)
            rim_faces.append((cell_of[(i, j)], 2))
            rim_len += gx[i + 1] - gx[i]
            load_area += 2 * math.pi * gr[j + 1] * (gx[i + 1] - gx[i])
    # stub rear face: nodes at x = x_min of the polygon with r <= r of that face
    x_min = float(xs.min())
    rear = [n for n, (r, x) in nodes.items() if abs(x - x_min) < 1e-9]
    # axial rigid-body fixity only: the single innermost node ring of the rear face (fixing the whole face would
    # restrain the Poisson / thermal axial strain and invent axial stress)
    stub_nodes = [min(rear, key=lambda n: nodes[n][0])]
    return dict(nodes=nodes, elements=elements, rim_faces=rim_faces, rim_len=rim_len, load_area=load_area, stub_nodes=stub_nodes,
                r_rim=r_rim, r_min=r_min, n_nodes=len(nodes), n_elements=len(elements), cell_mm=cell_mm)


# ----------------------------------------------------------------------------- thermal field
def start_thermal_state(doc: dict) -> dict:
    """Rim and bore temperature at the instant of maximum rim-bore difference during the start
    (same lumped model as the life stage), plus the steady values."""
    me = doc["outputs"]["mechanical"]["turbine"]
    li = doc["inputs"].get("life", {})
    tau_r, tau_b = float(li.get("rim_thermal_tau_s", 30.0)), float(li.get("bore_thermal_tau_s", 90.0))
    ramp = doc["outputs"].get("control", {}).get("start", {}).get("ramp_rate")
    t_ramp = (1.0 / float(ramp)) if ramp else 0.0
    T_r = T_b = 300.0
    best = (0.0, 300.0, 300.0, 0.0)
    dt = 0.1
    for i in range(3000):
        f = min(i * dt / t_ramp, 1.0) if t_ramp > 0 else 1.0
        T_gr = 300.0 + (me["T_rim_K"] - 300.0) * f
        T_gb = 300.0 + (me["T_bore_K"] - 300.0) * f
        T_r += (T_gr - T_r) * dt / tau_r
        T_b += (T_gb - T_b) * dt / tau_b + (T_r - T_b) * dt / 200.0
        if T_r - T_b > best[0]:
            best = (T_r - T_b, T_r, T_b, i * dt)
    return dict(dT_max_K=best[0], T_rim_K=best[1], T_bore_K=best[2], t_s=best[3], T_rim_ss_K=me["T_rim_K"], T_bore_ss_K=me["T_bore_K"])


# ----------------------------------------------------------------------------- deck
def write_deck(path: Path, mesh: dict, mat: dict, omega_mcs: float, omega_idle: float, F_blades_mcs: float,
               therm: dict, T_ref: float = 300.0) -> None:
    L = ["*HEADING", "jetsuite2 turbine disc, axisymmetric (X = radius, Y = axis), SI units", "*NODE"]
    for n, (r, x) in mesh["nodes"].items():
        L.append(f"{n}, {r:.7e}, {x:.7e}, 0.0")
    L.append("*ELEMENT, TYPE=CAX4, ELSET=DISC")
    for e, ns in mesh["elements"].items():
        L.append(f"{e}, {ns[0]}, {ns[1]}, {ns[2]}, {ns[3]}")
    L.append("*NSET, NSET=STUBREAR")
    L += [", ".join(str(n) for n in mesh["stub_nodes"][k:k + 12]) for k in range(0, len(mesh["stub_nodes"]), 12)]
    L.append("*NSET, NSET=NALL, GENERATE")
    L.append(f"1, {mesh['n_nodes']}")
    L.append("*MATERIAL, NAME=DISC")
    L.append("*ELASTIC"); L.append(f"{mat['E']:.6e}, {mat['nu']:.4f}")
    L.append("*DENSITY"); L.append(f"{mat['rho']:.4f}")
    L.append(f"*EXPANSION, ZERO={T_ref:.1f}"); L.append(f"{mat['alpha']:.6e}")
    L.append("*SOLID SECTION, ELSET=DISC, MATERIAL=DISC")
    L.append("*INITIAL CONDITIONS, TYPE=TEMPERATURE"); L.append(f"NALL, {T_ref:.1f}")
    L.append("*BOUNDARY"); L.append("STUBREAR, 2, 2, 0.0")
    # rim pressure (negative = outward pull) representing the blade row's centrifugal load
    p_mcs = -F_blades_mcs / max(mesh["load_area"], 1e-9)
    p_idle = p_mcs * (omega_idle / omega_mcs) ** 2
    T_field = therm.get("field")            # optional callable T(r, x) for non-disc components

    def temp_lines(T_r, T_b):
        out = ["*TEMPERATURE"]
        span = max(mesh["r_rim"] - mesh["r_min"], 1e-9)
        for n, (r, x) in mesh["nodes"].items():
            if T_field is not None:
                out.append(f"{n}, {T_field(r, x):.3f}")
            else:
                f = ((r - mesh["r_min"]) / span) ** 2
                out.append(f"{n}, {T_b + (T_r - T_b) * f:.3f}")
        return out

    def step(name, omega, p_rim, T_r=None, T_b=None):
        S = [f"** ---- {name}", "*STEP", "*STATIC", "*DLOAD"]
        S.append(f"DISC, CENTRIF, {omega * omega:.6e}, 0., 0., 0., 0., 1., 0.")
        for e, face in mesh["rim_faces"]:
            S.append(f"{e}, P{face}, {p_rim:.6e}")
        if T_r is not None:
            S += temp_lines(T_r, T_b)
        else:
            S += ["*TEMPERATURE", f"NALL, {T_ref:.1f}"]
        S += ["*NODE FILE", "U", "*EL FILE", "S", "*EL PRINT, ELSET=DISC", "S", "*END STEP"]
        return S
    L += step("step 1: centrifugal at MCS", omega_mcs, p_mcs)
    L += step("step 2: MCS + thermal field", omega_mcs, p_mcs, therm["T_rim_K"], therm["T_bore_K"])
    L += step("step 3: idle + thermal field", omega_idle, p_idle, therm["T_rim_K"], therm["T_bore_K"])
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- run
def _wsl_path(p: Path) -> str:
    p = p.resolve()
    drive = p.drive.rstrip(":").lower()
    return f"/mnt/{drive}" + str(p)[len(p.drive):].replace("\\", "/")


def ccx_available() -> dict:
    if shutil.which("ccx"):
        return dict(mode="native", cmd=["ccx"])
    try:
        r = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=20)
        distros = [d.strip() for d in r.stdout.decode("utf-16le", errors="ignore").splitlines() if d.strip()]
        for dist in distros:
            r2 = subprocess.run(["wsl.exe", "-d", dist, "--", "bash", "-lc", "which ccx"], capture_output=True, timeout=30)
            if r2.returncode == 0 and r2.stdout.strip():
                return dict(mode="wsl", distro=dist, ccx=r2.stdout.decode(errors="ignore").strip())
    except Exception:  # noqa: BLE001
        pass
    return dict(mode="none")


def run_ccx(inp: Path, env: dict) -> dict:
    job = inp.with_suffix("")
    if env["mode"] == "native":
        r = subprocess.run(["ccx", "-i", job.name], cwd=str(inp.parent), capture_output=True, text=True, timeout=1800)
    elif env["mode"] == "wsl":
        cmd = f"cd '{_wsl_path(inp.parent)}' && ccx -i {job.name}"
        r = subprocess.run(["wsl.exe", "-d", env["distro"], "--", "bash", "-lc", cmd], capture_output=True, text=True, timeout=1800)
    else:
        raise RuntimeError("no CalculiX (ccx) found natively or in WSL")
    log = inp.with_suffix(".log")
    log.write_text((r.stdout or "") + "\n" + (r.stderr or ""), encoding="utf-8")
    ok = r.returncode == 0 and inp.with_suffix(".dat").exists() and "Job finished" in (r.stdout or "")
    return dict(ok=ok, returncode=r.returncode, log=str(log), version=re.search(r"Version\s+([\d.]+)", r.stdout or "").group(1) if re.search(r"Version\s+([\d.]+)", r.stdout or "") else None)


# ----------------------------------------------------------------------------- results
def parse_dat(dat: Path, elements: dict, nodes: dict, corners=(), exclusion_m: float = 1.0e-3) -> list[dict]:
    """Per step: max von Mises, max hoop, area-weighted mean hoop, location of the peak (r, x), and the same maxima
    excluding integration points within ``exclusion_m`` of a re-entrant (sharp, unfilleted) corner, where the
    linear-elastic solution is singular and mesh-dependent."""
    text = dat.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n\s*stresses \(elem, integ\.?\s*pnt\.?,\s*sxx[^\n]*\n", text)[1:]
    steps = []
    # element areas (for the mean hoop stress)
    area = {}
    for e, ns in elements.items():
        (r0, x0), (r1, _), (_, x1) = nodes[ns[0]], nodes[ns[1]], nodes[ns[2]]
        area[e] = abs(r1 - r0) * abs(x1 - x0)
    for blk in blocks:
        vm_max = hoop_max = -1.0
        vm_away = hoop_away = -1.0
        loc = loc_away = None
        hoop_sum = a_sum = 0.0
        seen = {}
        centre = {}
        for e, ns in elements.items():
            r0, x0 = nodes[ns[0]]; r1, x1 = nodes[ns[2]]
            centre[e] = (0.5 * (r0 + r1), 0.5 * (x0 + x1))
        near = {e: any(math.hypot(c[0] - cr, c[1] - cx) < exclusion_m for cr, cx in corners) for e, c in centre.items()}
        for line in blk.splitlines():
            p = line.split()
            if len(p) < 8:
                if p and not p[0].isdigit():
                    break
                continue
            try:
                e, ip = int(p[0]), int(p[1]); sxx, syy, szz, sxy = (float(v) for v in p[2:6])
            except ValueError:
                continue
            vm = math.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * sxy * sxy)
            if vm > vm_max:
                vm_max = vm; loc = centre[e]
            hoop_max = max(hoop_max, szz)
            if not near[e]:
                if vm > vm_away:
                    vm_away = vm; loc_away = centre[e]
                hoop_away = max(hoop_away, szz)
            seen.setdefault(e, []).append(szz)
        for e, vals in seen.items():
            hoop_sum += area[e] * sum(vals) / len(vals); a_sum += area[e]
        steps.append(dict(vm_max_Pa=vm_max, hoop_max_Pa=hoop_max, hoop_mean_Pa=(hoop_sum / a_sum if a_sum else None),
                          peak_r_m=loc[0] if loc else None, peak_x_m=loc[1] if loc else None,
                          vm_max_away_Pa=vm_away, hoop_max_away_Pa=hoop_away,
                          peak_away_r_m=loc_away[0] if loc_away else None, peak_away_x_m=loc_away[1] if loc_away else None,
                          exclusion_m=exclusion_m))
    return steps


def boreless_profile(profile_m, r_axis: float = 0.0005) -> list:
    """What-if variant: the wheel's inner boundary moved from the bore radius to (almost) the axis, i.e. an
    integral boreless hub with the shaft attached at the stub faces instead of passing through."""
    poly = np.array(profile_m, float)
    r_min = poly[:, 1].min()
    out = poly.copy()
    out[np.abs(out[:, 1] - r_min) < 1e-9, 1] = r_axis
    return out.tolist()


def run_impeller_case(design, cell_mm: float = 0.5, write_ingest: bool = True) -> dict:
    """Impeller hub (axisymmetric, blades as a distributed centrifugal traction on the gas-path hub surface) at MCS,
    cold and with the steady eye-to-exit temperature field.  Ingests ``mechanical.impeller.sigma_peak_Pa``.
    The blade-to-hub fillet region is not resolved (blades are a smeared load), so the result is the disc/hub
    stress, not the blade-root stress (COMP-3 / MECH-4 keep the strip-theory value)."""
    doc = design.doc
    o = doc["outputs"]
    profile = o["rotor"]["impeller_hub_profile"]
    c = o["compressor"]
    L_imp = c["axial_length_m"]
    mesh = build_mesh(profile, cell_mm, load_x_range=(0.0, L_imp))
    mat_name = c["material"]
    m = materials.get(mat_name)
    rpm_mcs = o["speed"]["rpm_mcs"]
    idle = o.get("control", {}).get("idle_N", 0.5) * o["speed"]["rpm"]
    om_mcs, om_idle = rpm_mcs * 2 * math.pi / 60, idle * 2 * math.pi / 60
    m_bl = o["rotor"].get("m_blades_impeller_kg", 0.0)
    r_cg = 0.5 * (c["r1s_m"] + c["r2_m"])
    F_bl = m_bl * om_mcs ** 2 * r_cg
    T_eye, T_exit = o["cycle"]["Tt2_K"] + 20.0, c.get("T02_K", o["cycle"]["Tt3_K"])
    xs = [pt[0] for pt in profile]
    x_min = min(xs)

    def T_field(r, x):
        f = min(max((x - x_min) / max(L_imp - x_min, 1e-9), 0.0), 1.0)
        return T_eye + (T_exit - T_eye) * f
    therm = dict(T_rim_K=T_exit, T_bore_K=T_eye, field=T_field, dT_max_K=T_exit - T_eye, note="steady eye->exit field, linear in x")
    hdir = Path(design.dir) / "handoff" / "impeller_fea"
    hdir.mkdir(parents=True, exist_ok=True)
    inp = hdir / "impeller_axisym.inp"
    write_deck(inp, mesh, m, om_mcs, om_idle, F_bl, therm)
    env = ccx_available()
    run = run_ccx(inp, env)
    res = dict(case=str(inp), component="impeller", solver=env, run=run,
               mesh=dict(n_nodes=mesh["n_nodes"], n_elements=mesh["n_elements"], cell_mm=cell_mm, r_rim_m=mesh["r_rim"], r_min_m=mesh["r_min"],
                         load_area_m2=mesh["load_area"]),
               loads=dict(rpm_mcs=rpm_mcs, rpm_idle=idle, blade_pull_N=F_bl, thermal={k: v for k, v in therm.items() if k != "field"}), material=mat_name,
               reference_L1=dict(sigma_peak_Pa=o["mechanical"]["impeller"]["sigma_peak_Pa"], sigma_avg_Pa=o["mechanical"]["impeller"]["sigma_avg_Pa"]))
    if run["ok"]:
        corners = reentrant_corners(profile)
        steps = parse_dat(inp.with_suffix(".dat"), mesh["elements"], mesh["nodes"], corners)
        res["reentrant_corners_r_x_m"] = corners
        names = ["mcs_centrifugal", "mcs_plus_thermal", "idle_plus_thermal"]
        res["steps"] = {n: s_ for n, s_ in zip(names, steps)}
        res["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if write_ingest and len(steps) >= 2:
            src = (f"CalculiX {run.get('version') or ''} axisymmetric CAX4 impeller hub, {mesh['n_elements']} elements, blades as smeared "
                   f"traction, {res['at']}; peak >= 1 mm from re-entrant corners")
            ing = [dict(stage="mechanical", tier="L3", source=src,
                        fields={"impeller.sigma_peak_Pa": steps[1]["vm_max_away_Pa"]})]
            (hdir / "ingest_impeller_fe.json").write_text(json.dumps(ing, indent=1), encoding="utf-8")
            res["ingest_file"] = str(hdir / "ingest_impeller_fe.json")
    res["variant"] = "as-designed"
    (hdir / "impeller_fe_results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


def run_disc_case(design, cell_mm: float = 0.5, write_ingest: bool = True, variant: str = "as-designed") -> dict:
    """Build, run and post-process the turbine disc case.  Returns results and the ingest file path.
    ``variant='boreless'`` runs the what-if geometry (no ingest: it is not the design)."""
    doc = design.doc
    o = doc["outputs"]
    profile = o["rotor"]["turbine_disc_profile"]
    if variant == "boreless":
        profile = boreless_profile(profile)
        write_ingest = False
    mesh = build_mesh(profile, cell_mm)
    mat_name = o["turbine"]["material"]
    m = materials.get(mat_name)
    rpm_mcs = o["speed"]["rpm_mcs"]
    idle = o.get("control", {}).get("idle_N", 0.5) * o["speed"]["rpm"]
    om_mcs, om_idle = rpm_mcs * 2 * math.pi / 60, idle * 2 * math.pi / 60
    m_bl = o["rotor"].get("m_turbine_blades_kg", 0.0)
    r_cg = 0.5 * (o["turbine"]["r_hub_rotor_m"] + o["turbine"]["r_tip_rotor_m"])
    F_bl = m_bl * om_mcs ** 2 * r_cg
    therm = start_thermal_state(doc)
    hdir = Path(design.dir) / "handoff" / "turbine_fea"
    hdir.mkdir(parents=True, exist_ok=True)
    tag = "" if variant == "as-designed" else f"_{variant}"
    inp = hdir / f"disc_axisym{tag}.inp"
    write_deck(inp, mesh, m, om_mcs, om_idle, F_bl, therm)
    env = ccx_available()
    run = run_ccx(inp, env)
    res = dict(case=str(inp), solver=env, run=run, mesh=dict(n_nodes=mesh["n_nodes"], n_elements=mesh["n_elements"], cell_mm=cell_mm,
                                                             r_rim_m=mesh["r_rim"], r_min_m=mesh["r_min"]),
               loads=dict(rpm_mcs=rpm_mcs, rpm_idle=idle, blade_pull_N=F_bl, thermal=therm), material=mat_name,
               reference_L1=dict(sigma_peak_Pa=o["mechanical"]["turbine"]["sigma_peak_Pa"], sigma_avg_Pa=o["mechanical"]["turbine"]["sigma_avg_Pa"],
                                 thermal_stress_Pa=o.get("life", {}).get("thermal", {}).get("thermal_stress_Pa") if isinstance(o.get("life", {}).get("thermal"), dict) else None))
    if run["ok"]:
        corners = reentrant_corners(profile)
        steps = parse_dat(inp.with_suffix(".dat"), mesh["elements"], mesh["nodes"], corners)
        res["reentrant_corners_r_x_m"] = corners
        names = ["mcs_centrifugal", "mcs_plus_start_thermal", "idle_plus_start_thermal"]
        res["steps"] = {n: s for n, s in zip(names, steps)}
        res["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if write_ingest and len(steps) >= 2:
            src = f"CalculiX {run.get('version') or ''} axisymmetric CAX4 disc, {mesh['n_elements']} elements, {res['at']}"
            ing = [dict(stage="mechanical", tier="L3", source=src,
                        fields={"turbine.sigma_peak_Pa": steps[0]["vm_max_away_Pa"], "turbine.sigma_avg_Pa": steps[0]["hoop_mean_Pa"]}),
                   dict(stage="life", tier="L3", source=src + "; peak taken >= 1 mm from the unfilleted re-entrant corners (singular there)",
                        fields={"sigma_bore_total_Pa": steps[1]["vm_max_away_Pa"]})]
            (hdir / "ingest_disc_fe.json").write_text(json.dumps(ing, indent=1), encoding="utf-8")
            res["ingest_file"] = str(hdir / "ingest_disc_fe.json")
    res["variant"] = variant
    (hdir / f"disc_fe_results{tag}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res
