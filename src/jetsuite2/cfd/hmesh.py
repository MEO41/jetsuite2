"""Structured H-mesh of one impeller passage, written directly in SU2 format (no CAD booleans).

Grid directions: i = meridional (inlet extension -> blade -> outlet extension), j = span (hub -> shroud),
k = pitchwise.  Two pitchwise blocks: block 1 from the main blade's plus side to the splitter's minus side,
block 2 from the splitter's plus side to the next main blade's minus side.  Ahead of the main-blade LE and beyond
the TE the blade half-thickness is zero, so the k = 0 face of block 1 and the k = K face of block 2 are exact
rotational copies node for node (the periodic pair); ahead of the splitter LE the two blocks share the interface
nodes.  The camber law is the CAD's (inlet angle hub-rms-shroud eased to the backsweep, radial TE), the thickness
law too; the mesh *is* the geometry the solver sees, so what is being solved is stated in ``mesh_info``.

Limitations stated in the case file: no tip clearance (shroud attached to the blade, rotating with the frame),
elliptic LE resolved only to the pitchwise spacing, hexahedra only (no prism layers), y+ from the first cell height.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np


def _cluster(n, a=2.0):
    """n+1 points in [0,1] clustered toward both ends (tanh)."""
    u = np.linspace(-1, 1, n + 1)
    return 0.5 * (1 + np.tanh(a * u) / math.tanh(a))


def build(design, out_dir: Path, ni_blade: int = 48, ni_in: int = 12, ni_out: int = 14, nj: int = 22, nk: int = 14,
          x_in_ext: float = 0.6, r_out_ext: float = 1.12, verbose=None, rans: bool = False, nk_cluster: float = 1.6) -> dict:
    from ..cad.impeller import _resample, hub_curve_from_profile
    o = design.outputs()
    sheet = o["geometry"]["sheet"]["impeller"]
    n_main, n_spl = int(sheet["n_main"]), int(sheet["n_splitter"])
    pitch = 2 * math.pi / n_main
    r1s, r1h, r2 = float(sheet["r1s"]), float(sheet["r1h"]), float(sheet["r2"])
    beta_te = math.radians(float(sheet["backsweep"]))
    b_le = {"h": sheet["beta_le_hub"], "m": sheet["beta_le_rms"], "s": sheet["beta_le_shroud"]}
    t_root, t_tip = float(sheet["t_root"]), float(sheet["t_tip"])
    s_split = 1.0 - float(sheet["splitter_length_frac"]) if n_spl else 2.0
    hub = np.asarray(hub_curve_from_profile(sheet["hub_profile"], r1h, r2), float)
    shr = np.asarray(sheet["shroud_curve"], float)
    x_in = -x_in_ext * r1s
    r_out = r_out_ext * r2
    # ---- meridional grid: blade portion by arc fraction (clustered at LE/TE), extensions straight
    s_bl = _cluster(ni_blade, 1.6)
    hub_b, shr_b = _resample(hub, s_bl), _resample(shr, s_bl)
    def ext_up(c):
        x0, r0 = c[0]
        u = _cluster(ni_in, 1.2)[:-1]
        return np.c_[x_in + (x0 - x_in) * u, np.full(ni_in, r0)]
    def ext_dn(c):
        x1, r1 = c[-1]
        u = _cluster(ni_out, 1.2)[1:]
        return np.c_[np.full(ni_out, x1), r1 + (r_out - r1) * u]
    hub_m = np.concatenate([ext_up(hub_b), hub_b, ext_dn(hub_b)], axis=0)
    shr_m = np.concatenate([ext_up(shr_b), shr_b, ext_dn(shr_b)], axis=0)
    NI = hub_m.shape[0]
    i_le, i_te = ni_in, ni_in + ni_blade
    tj = _cluster(nj, 1.8)                                   # span stations hub -> shroud (clustered)
    NJ = nj + 1
    P = np.zeros((NI, NJ, 2))                                # (x, r)
    for j, t in enumerate(tj):
        P[:, j, :] = hub_m + (shr_m - hub_m) * t
    # ---- camber theta on every streamline (CAD law: beta eased, held constant in the extensions, radial TE)
    TH = np.zeros((NI, NJ))
    m_all = np.zeros((NI, NJ))
    sfrac = np.zeros((NI, NJ))
    for j, t in enumerate(tj):
        pts = P[:, j]
        m = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1])))])
        m_all[:, j] = m
        sf = np.clip((m - m[i_le]) / (m[i_te] - m[i_le]), 0.0, 1.0)
        sfrac[:, j] = sf
        ble = math.radians(float(np.interp(t, [0.0, 0.5, 1.0], [b_le["h"], b_le["m"], b_le["s"]])))
        ease = 3 * sf ** 2 - 2 * sf ** 3
        beta = ble + (beta_te - ble) * ease
        dth = np.tan(beta[:-1]) * np.diff(m) / np.maximum(pts[:-1, 1], 1e-3)
        th = np.concatenate([[0.0], np.cumsum(dth)])
        TH[:, j] = th - th[i_le]
    th_te_ref = float(np.mean(TH[i_te, :]))
    for j in range(NJ):
        TH[:, j] += (th_te_ref - TH[i_te, j]) * sfrac[:, j]  # radial TE, correction frozen downstream
    # ---- blade half-thickness in radians (elliptic LE over 8 % chord, rounded TE), zero outside the blade
    def half_thick(i_start, i_end, tt_scale=1.0):
        d = np.zeros((NI, NJ))
        for j, t in enumerate(tj):
            tn = (t_root + (t_tip - t_root) * t) * tt_scale
            for i in range(i_start, i_end + 1):
                sf = (m_all[i, j] - m_all[i_start, j]) / max(m_all[i_end, j] - m_all[i_start, j], 1e-9)
                # elliptic LE over 8 % and a parabolic TE close-out over the last 6 %: the blade must close to a line at
                # the LE and TE grid stations so the periodic faces (zero thickness) meet it without a step
                le = min(sf / 0.08, 1.0)
                th = tn * math.sqrt(max(1 - (1 - le) ** 2, 0.0))
                if sf > 0.94:
                    th = tn * math.sqrt(max((1.0 - sf) / 0.06, 0.0))
                if i == i_start or i == i_end:
                    th = 0.0
                d[i, j] = 0.5 * th / max(P[i, j, 1], 1e-3)
        return d
    dA = half_thick(i_le, i_te)
    i_sp = int(np.argmax(sfrac[:, NJ // 2] >= s_split)) if n_spl else i_te + 1
    dS = half_thick(i_sp, i_te, 0.85) if n_spl else np.zeros((NI, NJ))
    # ---- pitchwise nodes: block 1 [TH + dA, TH + pitch/2 - dS], block 2 [TH + pitch/2 + dS, TH + pitch - dA]
    NK = nk + 1
    tk = _cluster(nk, nk_cluster)
    # node ids: block1 k = 0..nk, block2 k = 0..nk; the interface (block1 k=nk / block2 k=0) is shared where dS == 0
    nodes = []
    id1 = np.full((NI, NJ, NK), -1, int); id2 = np.full((NI, NJ, NK), -1, int)
    def add(x, r, th):
        nodes.append((x, r * math.cos(th), r * math.sin(th)))
        return len(nodes) - 1
    for i in range(NI):
        for j in range(NJ):
            x, r = P[i, j]
            th0 = TH[i, j]
            a0, a1 = th0 + dA[i, j], th0 + 0.5 * pitch - dS[i, j]
            b0, b1 = th0 + 0.5 * pitch + dS[i, j], th0 + pitch - dA[i, j]
            for k in range(NK):
                id1[i, j, k] = add(x, r, a0 + (a1 - a0) * tk[k])
            for k in range(NK):
                if k == 0 and dS[i, j] == 0.0:
                    id2[i, j, k] = id1[i, j, nk]                # shared interface node
                else:
                    id2[i, j, k] = add(x, r, b0 + (b1 - b0) * tk[k])
    nodes = np.array(nodes) * 1e-3                             # mm -> m
    # ---- hexahedra (orientation checked on the first cell and flipped if needed)
    def hexes(ids):
        out = []
        for i in range(NI - 1):
            for j in range(NJ - 1):
                for k in range(nk):
                    out.append([ids[i, j, k], ids[i + 1, j, k], ids[i + 1, j + 1, k], ids[i, j + 1, k],
                                ids[i, j, k + 1], ids[i + 1, j, k + 1], ids[i + 1, j + 1, k + 1], ids[i, j + 1, k + 1]])
        return out
    H = hexes(id1) + hexes(id2)
    n0 = np.array(H[0])
    p = nodes[n0]
    vol = np.dot(np.cross(p[1] - p[0], p[3] - p[0]), p[4] - p[0])
    if vol < 0:                                              # left-handed (x, r, theta): swap the two k layers
        H = [[h[4], h[5], h[6], h[7], h[0], h[1], h[2], h[3]] for h in H]
    # ---- boundary quads
    def quad_i(ids, i):
        return [[ids[i, j, k], ids[i, j + 1, k], ids[i, j + 1, k + 1], ids[i, j, k + 1]] for j in range(NJ - 1) for k in range(nk)]
    def quad_j(ids, j):
        return [[ids[i, j, k], ids[i + 1, j, k], ids[i + 1, j, k + 1], ids[i, j, k + 1]] for i in range(NI - 1) for k in range(nk)]
    def quad_k(ids, k, i0, i1):
        return [[ids[i, j, k], ids[i + 1, j, k], ids[i + 1, j + 1, k], ids[i, j + 1, k]] for i in range(i0, i1) for j in range(NJ - 1)]
    markers = {
        "INLET": quad_i(id1, 0) + quad_i(id2, 0),
        "OUTLET": quad_i(id1, NI - 1) + quad_i(id2, NI - 1),
        "HUB": quad_j(id1, 0) + quad_j(id2, 0),
        "SHROUD": quad_j(id1, NJ - 1) + quad_j(id2, NJ - 1),
        "BLADE": quad_k(id1, 0, i_le, i_te) + quad_k(id2, nk, i_le, i_te) + (quad_k(id1, nk, i_sp, i_te) + quad_k(id2, 0, i_sp, i_te) if n_spl else []),
        "PER_A": quad_k(id1, 0, 0, i_le) + quad_k(id1, 0, i_te, NI - 1),
        "PER_B": quad_k(id2, nk, 0, i_le) + quad_k(id2, nk, i_te, NI - 1),
    }
    # ---- write SU2
    out_dir.mkdir(parents=True, exist_ok=True)
    su2 = out_dir / "passage.su2"
    with open(su2, "w", encoding="utf-8") as f:
        f.write("NDIME= 3\n")
        f.write(f"NELEM= {len(H)}\n")
        for e, h in enumerate(H):
            f.write("12 " + " ".join(str(n) for n in h) + f" {e}\n")
        f.write(f"NPOIN= {len(nodes)}\n")
        for n, (x, y, z) in enumerate(nodes):
            f.write(f"{x:.9e} {y:.9e} {z:.9e} {n}\n")
        f.write(f"NMARK= {len(markers)}\n")
        for name, quads in markers.items():
            f.write(f"MARKER_TAG= {name}\nMARKER_ELEMS= {len(quads)}\n")
            for q in quads:
                f.write("9 " + " ".join(str(n) for n in q) + "\n")
    # ---- initial field (SU2 ASCII restart): velocity along the meridional grid lines with the magnitude from
    # continuity, absolute swirl rising from zero at the LE to the mean-line work coefficient at the TE and held as
    # a free vortex downstream, static pressure ramped from the inlet to the outlet value.  SU2's uniform axial
    # start field slams into the radial exit, pulls fluid off the shroud face and the pressure outlet then feeds a
    # standing vortex (350 m/s inflow at the shroud / periodic corner, net flow zero, "heating" by compression);
    # a streamline-aligned start converges cleanly (validated on the bladeless channel: mass balance 1 %, Tt
    # exit 288.1 K, rms rho -6.9 in 400 iterations).
    c = o["compressor"]; cy = o["cycle"]
    omega = o["speed"]["rpm"] * 2 * math.pi / 60
    sense = -1.0 if th_te_ref > 0 else 1.0                   # the blade wraps in +theta along the flow -> wheel about -x
    W_pass = float(cy["W_kg_s"]) / n_main
    Pt_in, Tt_in = float(cy["Pt2_Pa"]), float(cy["Tt2_K"])
    psi = float(c.get("work_coefficient", 0.7))
    U2 = omega * r2 * 1e-3
    p_exit = Pt_in * float(c.get("PR_impeller_tt", cy["OPR"] * 1.06)) * (1 + 0.2 * (0.85 * float(c.get("M2_abs", 0.9))) ** 2) ** -3.5
    cp, R_air = 1004.5, 287.058
    # swirl fraction g(i): 0 upstream of the LE, eased to 1 at the TE, free vortex downstream
    g = np.zeros(NI)
    for i in range(NI):
        if i <= i_le:
            g[i] = 0.0
        elif i >= i_te:
            g[i] = 1.0
        else:
            sfi = (i - i_le) / (i_te - i_le)
            g[i] = 3 * sfi ** 2 - 2 * sfi ** 3
    init = np.zeros((len(nodes), 5))
    Vm_prev = np.full(NJ, 150.0); Cth_te = np.zeros(NJ); r_te = np.ones(NJ)
    for i in range(NI):
        # station area (per passage): pitch * mean radius * span width, m^2
        width = math.hypot(P[i, NJ - 1, 0] - P[i, 0, 0], P[i, NJ - 1, 1] - P[i, 0, 1]) * 1e-3
        r_mid = 0.5 * (P[i, 0, 1] + P[i, NJ - 1, 1]) * 1e-3
        A = pitch * r_mid * width
        p_st = Pt_in * 0.97 + (p_exit - Pt_in * 0.97) * (i / (NI - 1))
        for j in range(NJ):
            ia, ib = max(i - 1, 0), min(i + 1, NI - 1)
            t = np.array([P[ib, j, 0] - P[ia, j, 0], P[ib, j, 1] - P[ia, j, 1]])
            t /= max(np.linalg.norm(t), 1e-9)
            r_m = P[i, j, 1] * 1e-3
            # relative velocity along the blade camber (W_theta = W_m r dTheta/dm), absolute = wheel speed + W: the
            # walls then see no normal relative velocity at the start (a lagging swirl is a piston: the blade
            # pressure side compresses to 1e5 K and the suction side cavitates within 20 iterations)
            dth = (TH[ib, j] - TH[ia, j]) / max(math.hypot(P[ib, j, 0] - P[ia, j, 0], P[ib, j, 1] - P[ia, j, 1]), 1e-9)
            Wm_guess = Vm_prev[j] if i > 0 else 150.0
            Wth = Wm_guess * r_m * dth * 1e3 * (1.0 if i <= i_te else 0.0)   # dTheta/dm in rad/mm -> per m
            if i > i_te:                                                    # free vortex from the TE outward
                Cth = Cth_te[j] * r_te[j] / max(r_m, 1e-6)
            else:
                Cth = sense * omega * r_m + Wth * (1.0 if sense > 0 else -1.0) * (-1.0)
                Cth = (0.0 if i <= i_le else Cth * g[i])                   # no swirl upstream of the LE
            Tt = Tt_in + omega * r_m * abs(Cth) / cp
            rho_g = p_st / (R_air * Tt)
            Vm = W_pass / (rho_g * A)
            V2 = Vm * Vm + Cth * Cth
            T = max(Tt - V2 / (2 * cp), 150.0)
            rho = p_st / (R_air * T)
            Vm_prev[j] = Vm
            if i == i_te:
                Cth_te[j] = Cth; r_te[j] = r_m
            for ids in (id1, id2):
                for k in range(NK):
                    n = ids[i, j, k]
                    x, y, z = nodes[n]
                    th = math.atan2(z, y)
                    vx = t[0] * Vm
                    vr = t[1] * Vm
                    vy = vr * math.cos(th) - Cth * math.sin(th)
                    vz = vr * math.sin(th) + Cth * math.cos(th)
                    init[n] = (rho, rho * vx, rho * vy, rho * vz, rho * (717.6 * T + 0.5 * V2))
    np.savez_compressed(out_dir / "passage_ids.npz", id1=id1, id2=id2, P=P, TH=TH, i_le=i_le, i_te=i_te, i_sp=i_sp, pitch=pitch)
    init_path = out_dir / "passage_init.csv"
    # SST columns for a RANS start: k from 5 % intensity on the local speed, omega from mu_t / mu = 10
    mu_in = 1.716e-5 * (Tt_in / 273.15) ** 1.5 * (273.15 + 110.4) / (Tt_in + 110.4)
    with open(init_path, "w", encoding="utf-8") as f:
        f.write('"PointID","x","y","z","Density","Momentum_x","Momentum_y","Momentum_z","Energy"' + (',"Turb_Kin_Energy","Omega"' if rans else "") + "\n")
        for n, (x, y, z) in enumerate(nodes):
            row = f"{n}, {x:.9e}, {y:.9e}, {z:.9e}, " + ", ".join(f"{v:.9e}" for v in init[n])
            if rans:
                rho_n = init[n, 0]; v2 = (init[n, 1] ** 2 + init[n, 2] ** 2 + init[n, 3] ** 2) / rho_n ** 2
                k_t = 1.5 * (0.05 ** 2) * max(v2, 100.0)
                om_t = rho_n * k_t / (10.0 * mu_in)
                row += f", {rho_n * k_t:.9e}, {rho_n * om_t:.9e}"
            f.write(row + "\n")
    # first-cell height at the blade (pitchwise) and at the hub for a y+ estimate
    dth = (0.5 * pitch - dS[i_le + ni_blade // 2, NJ // 2] - dA[i_le + ni_blade // 2, NJ // 2]) * (tk[1] - tk[0])
    h_blade_mm = dth * P[i_le + ni_blade // 2, NJ // 2, 1]
    h_hub_mm = float(np.hypot(*(P[i_le + ni_blade // 2, 1] - P[i_le + ni_blade // 2, 0])))
    info = dict(su2=str(su2), init=str(init_path), rotation_sense=sense, n_nodes=int(len(nodes)), n_hexes=len(H), markers={k: len(v) for k, v in markers.items()},
                NI=NI, NJ=NJ, NK=NK, i_le=i_le, i_te=i_te, i_splitter=i_sp, pitch_deg=math.degrees(pitch), n_main=n_main, n_splitter=n_spl,
                first_cell_blade_mm=h_blade_mm, first_cell_hub_mm=h_hub_mm, x_in_mm=x_in, r_out_mm=r_out, theta_te_deg=math.degrees(th_te_ref),
                geometry="structured H-mesh on the CAD camber and thickness laws; no tip clearance; shroud attached")
    if verbose:
        verbose(f"  H-mesh: {info['n_nodes']} nodes, {info['n_hexes']} hexes; first cell blade {h_blade_mm:.3f} mm, hub {h_hub_mm:.3f} mm; markers {info['markers']}")
    return info
