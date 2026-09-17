"""Analysis stage - impeller meridional through-flow with blade loading (L2.5, roadmap section 7).

A streamline-curvature-type quasi-3D analysis of the impeller passage on the *same* meridional channel
and blade-angle law the CAD builds from (hub / shroud curves, inlet blade angles hub-rms-shroud eased to
the exit backsweep), so it checks the blade shape rather than just its end angles:

* meridional streamlines hub -> shroud, curvature from the geometry; at every quasi-orthogonal the
  meridional velocity profile follows the normal-equilibrium term d ln Cm / dn = -kappa (streamline
  curvature) and continuity with blade + boundary-layer blockage, rothalpy-conserving relative-frame
  thermodynamics with a polytropic loss law;
* flow follows the blade (relative angle = blade angle) except for a slip-based deviation that grows
  toward the trailing edge so the exit swirl matches the mean-line slip factor;
* Stanitz blade-to-blade loading: W_ss - W_ps = (2 pi / N) cos(beta) d(r C_theta)/dm, splitter row doubling
  N from the splitter leading edge;
* hub-to-shroud incidence at the leading edge, suction / pressure surface velocity diagrams on hub, mid
  and shroud streamlines, suction-side deceleration ratio, loading parameter, reverse-flow (negative
  pressure-side velocity) check, exit Cm distortion.

What it is not: a viscous 3-D solution.  Secondary flows, the tip-leakage jet and the wake are not in it;
the correlations it feeds (Dean deceleration 1.6, Aungier loading 0.9, incidence spread) are the checks
practice applies to exactly this kind of analysis.  Declared band: velocities +/-10 %.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..rules import check
from .common import inp, out

TIER = "L2"
CORE = False

DEFAULTS = {
    "n_span": 7, "n_chord": 41,
    "blockage_le": 0.03, "blockage_te": 0.12,        # aerodynamic (boundary-layer) blockage growth along m
    "loss_polytropic_eta": 0.88,                     # polytropic efficiency along the passage (density law)
    "deviation_exponent": 3.0,                       # slip-based deviation grows as (m/m_te)^k toward the TE
    "plots": True,
    "_doc": {"n_span": "streamlines hub -> shroud", "n_chord": "quasi-orthogonal stations", "blockage_le": "boundary-layer blockage at the LE",
             "blockage_te": "boundary-layer blockage at the TE", "loss_polytropic_eta": "polytropic efficiency for the density along m",
             "deviation_exponent": "exponent of the deviation growth toward the trailing edge", "plots": "write the loading / incidence plots"},
}

READS = ["inputs.throughflow.*", "inputs.compressor.splitter_length_frac", "outputs.geometry.sheet.impeller", "outputs.compressor.*",
         "outputs.cycle.W_kg_s", "outputs.cycle.Tt2_K", "outputs.cycle.Pt2_Pa", "outputs.speed.rpm"]

R = 287.05
CP = 1005.0
GAM = 1.4


def _arc(curve):
    d = np.sqrt(np.sum(np.diff(curve, axis=0) ** 2, axis=1))
    s = np.concatenate([[0.0], np.cumsum(d)])
    return s / s[-1]


def _resample(curve, s_new):
    s = _arc(curve)
    return np.c_[np.interp(s_new, s, curve[:, 0]), np.interp(s_new, s, curve[:, 1])]


def _hub_curve(profile, r1h, r2):
    p = np.asarray(profile, float)
    i0 = int(np.argmin(np.abs(p[:, 1] - r1h) + 1e3 * (p[:, 0] < 0)))
    i1 = int(np.argmax(p[:, 1] >= r2 - 1e-6))
    return p[i0:i1 + 1]


def blade_angle(sfrac, t, beta_le_h, beta_le_m, beta_le_s, beta_te):
    """The CAD camber law (cad/impeller.camber_grids): inlet angle quadratic hub-rms-shroud, smooth-step ease to the backsweep."""
    b_le = np.interp(t, [0.0, 0.5, 1.0], [beta_le_h, beta_le_m, beta_le_s])
    ease = 3 * sfrac ** 2 - 2 * sfrac ** 3
    return b_le + (beta_te - b_le) * ease


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "throughflow", k, DEFAULTS[k])  # noqa: E731
    sh = out(doc, "geometry")["sheet"]["impeller"]
    c = out(doc, "compressor")
    W_dot = out(doc, "cycle", "W_kg_s"); Tt1, Pt1 = out(doc, "cycle", "Tt2_K"), out(doc, "cycle", "Pt2_Pa")
    omega = out(doc, "speed", "rpm") * 2 * math.pi / 60
    MM = 1e-3
    n_span, n_chord = int(g("n_span")), int(g("n_chord"))
    hub = _hub_curve(sh["hub_profile"], sh["r1h"], sh["r2"]) * MM
    shr = np.asarray(sh["shroud_curve"], float) * MM
    s_grid = np.linspace(0.0, 1.0, n_chord)
    hub_pts, shr_pts = _resample(hub, s_grid), _resample(shr, s_grid)
    t_st = np.linspace(0.0, 1.0, n_span)
    N_main, N_spl = int(sh["n_main"]), int(sh["n_splitter"])
    s_split = 1.0 - float(doc["inputs"].get("compressor", {}).get("splitter_length_frac", 0.6)) if N_spl else 1.1
    beta_te = float(sh["backsweep"])
    b_h, b_m, b_s = float(sh["beta_le_hub"]), float(sh["beta_le_rms"]), float(sh["beta_le_shroud"])
    slip = float(c.get("slip_factor", 0.85))
    t_root, t_tip = float(sh["t_root"]) * MM, float(sh["t_tip"]) * MM
    k_dev = float(g("deviation_exponent"))
    B_le, B_te = float(g("blockage_le")), float(g("blockage_te"))
    eta_p = float(g("loss_polytropic_eta"))
    # ---- streamlines (x, r) and meridional arc length, blade angle field, curvature
    pts = np.array([hub_pts + (shr_pts - hub_pts) * t for t in t_st])          # (n_span, n_chord, 2)
    m = np.zeros((n_span, n_chord))
    for i in range(n_span):
        m[i, 1:] = np.cumsum(np.hypot(np.diff(pts[i, :, 0]), np.diff(pts[i, :, 1])))
    sfrac = m / m[:, -1:]
    beta_b = np.array([blade_angle(sfrac[i], t_st[i], b_h, b_m, b_s, beta_te) for i in range(n_span)])   # deg, from meridional
    # meridional streamline curvature kappa (1/m): dphi/dm with phi = atan2(dr, dx)
    kappa = np.zeros_like(m)
    for i in range(n_span):
        dx, dr = np.gradient(pts[i, :, 0]), np.gradient(pts[i, :, 1])
        phi = np.unwrap(np.arctan2(dr, dx))
        kappa[i] = np.gradient(phi) / np.maximum(np.gradient(m[i]), 1e-6)
    # ---- deviation: relative flow angle = blade angle + dev(m) so that the exit swirl matches the slip factor
    # exit: Ct2 = slip * U2 - Cm2 tan(beta_te) (backsweep from radial, positive) -> flow angle at TE from slip
    U2 = omega * float(sh["r2"]) * MM
    Cm2_ml = float(c.get("Cm2_m_s", 0.28 * U2))
    Ct2_ml = float(c.get("Ct2_m_s", slip * U2 - Cm2_ml * math.tan(math.radians(beta_te))))
    beta2_flow = math.degrees(math.atan2(U2 - Ct2_ml, Cm2_ml))
    dev_te = beta2_flow - beta_te
    beta_f = beta_b + dev_te * sfrac ** k_dev
    # ---- march the quasi-orthogonals: Cm profile from curvature + continuity, rothalpy thermodynamics
    rothalpy = CP * Tt1                                                        # W1 relative frame: I = h + W^2/2 - U^2/2 (Cθ1 = 0)
    Cm = np.zeros((n_span, n_chord)); Wrel = np.zeros_like(Cm); Ct = np.zeros_like(Cm); rho = np.zeros_like(Cm); p = np.zeros_like(Cm)
    T_st = np.zeros_like(Cm); Ws = np.zeros_like(Cm); Wp = np.zeros_like(Cm)
    p_ref = Pt1
    for j in range(n_chord):
        r = pts[:, j, 1]; U = omega * r
        n_coord = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(pts[:, j, 0]), np.diff(pts[:, j, 1])))])
        # normal equilibrium: d ln Cm / dn = -kappa (curvature of the meridional streamlines, mean over the q-o)
        kap = kappa[:, j]
        lnCm = np.concatenate([[0.0], np.cumsum(-0.5 * (kap[1:] + kap[:-1]) * np.diff(n_coord))])
        shape = np.exp(lnCm - lnCm.mean())
        B = B_le + (B_te - B_le) * sfrac[:, j].mean()
        N_here = N_main + (N_spl if sfrac[:, j].mean() >= s_split else 0)
        t_bl = t_root + (t_tip - t_root) * t_st
        beta_r = np.radians(beta_f[:, j])
        # blade metal blockage: N t / (2 pi r cos(beta))
        B_blade = np.clip(N_here * t_bl / (2 * math.pi * r * np.cos(beta_r)), 0.0, 0.6) if j > 0 else np.zeros(n_span)
        # iterate density with the velocity level for continuity
        Cm_level = 100.0
        for _ in range(30):
            Cm_j = Cm_level * shape
            W_j = Cm_j / np.cos(beta_r)
            Ct_j = U - Cm_j * np.tan(beta_r)                                   # absolute tangential (backsweep reduces it)
            h_st = rothalpy - 0.5 * W_j ** 2 + 0.5 * U ** 2
            T_j = np.maximum(h_st / CP, 150.0)
            # polytropic pressure law from the inlet static state along the passage
            T_ref = Tt1 - 0.5 * (Cm_j[0] ** 2) / CP if j == 0 else T_j
            p_j = p_ref * (T_j / Tt1) ** (GAM / (GAM - 1) * eta_p) if j > 0 else Pt1 * (T_j / Tt1) ** (GAM / (GAM - 1))
            rho_j = p_j / (R * T_j)
            # continuity across the quasi-orthogonal (annular strips between streamlines, projected normal to Cm)
            dA = 2 * math.pi * 0.5 * (r[1:] + r[:-1]) * np.diff(n_coord)
            flux = np.sum(0.5 * (rho_j[1:] * Cm_j[1:] + rho_j[:-1] * Cm_j[:-1]) * dA * (1 - B) * (1 - 0.5 * (B_blade[1:] + B_blade[:-1])))
            if flux <= 0:
                break
            Cm_new = Cm_level * W_dot / flux
            if abs(Cm_new - Cm_level) < 1e-3 * Cm_level:
                Cm_level = Cm_new
                break
            Cm_level = 0.5 * (Cm_level + Cm_new)
        Cm[:, j], Wrel[:, j], Ct[:, j], rho[:, j], p[:, j], T_st[:, j] = Cm_j, W_j, Ct_j, rho_j, p_j, T_j
    # ---- Stanitz loading: W_ss - W_ps = (2 pi / N) cos(beta) d(r Ct)/dm
    for i in range(n_span):
        rCt = pts[i, :, 1] * Ct[i]
        d_rCt = np.gradient(rCt, np.maximum(m[i], 1e-9))
        Nrow = np.where(sfrac[i] >= s_split, N_main + N_spl, N_main)
        dW = (2 * math.pi / Nrow) * np.cos(np.radians(beta_f[i])) * d_rCt
        dW = np.clip(dW, 0.0, 3.0 * Wrel[i])
        Ws[i] = Wrel[i] + 0.5 * dW
        Wp[i] = Wrel[i] - 0.5 * dW
    # ---- incidence at the LE: flow angle from Cm(n) and U(r) (no pre-swirl) vs blade angle
    beta_flow_le = np.degrees(np.arctan2(omega * pts[:, 0, 1], Cm[:, 0]))
    incidence = beta_flow_le - beta_b[:, 0]
    # ---- diagnostics
    i_h, i_m, i_s = 0, n_span // 2, n_span - 1
    def decel(i):
        ws = Ws[i]; k = int(np.argmax(ws[: max(3, n_chord // 3)]))
        return float(ws[k] / max(ws[-1], 1e-6))
    decel_ratio = {"hub": decel(i_h), "mid": decel(i_m), "shroud": decel(i_s)}
    loading = float(np.max((Ws - Wp)[:, 2:-1] / np.maximum(Wrel[:, 2:-1], 1e-6)))
    min_Wp = float(np.min(Wp[:, 2:]))
    reverse = bool(min_Wp < 0.0)
    cm_distortion = float(Cm[i_s, -1] / max(Cm[i_h, -1], 1e-6))
    inc_spread = float(incidence.max() - incidence.min())
    diffusion = {"hub": float(Wrel[i_h, 0] / max(Wrel[i_h, -1], 1e-6)), "mid": float(Wrel[i_m, 0] / max(Wrel[i_m, -1], 1e-6)),
                 "shroud": float(Wrel[i_s, 0] / max(Wrel[i_s, -1], 1e-6))}
    ddir = doc.get("_design_dir")
    plots = _plot(m, sfrac, Ws, Wp, Wrel, incidence, t_st, beta_b, beta_f, Cm, pts, Path(ddir) / "analysis", (i_h, i_m, i_s)) if bool(g("plots")) and ddir else {}
    rules = [
        check("TF-1", "pressure-side relative velocity stays positive (no blade overload / reverse flow)", min_Wp, 0.0, "min",
              "Stanitz loading on the blade-aligned through-flow (L2.5)", unit="m/s", warn_margin=0.0,
              note="more blades or an earlier splitter, or less turning per unit length"),
        check("TF-2", "suction-side deceleration ratio W_ss,max / W_ss,exit (worst streamline)", max(decel_ratio.values()), 1.6, "max",
              "Dean / Rodgers: suction-surface diffusion <= ~1.6 before separation", warn_margin=0.1,
              note=f"hub {decel_ratio['hub']:.2f}, mid {decel_ratio['mid']:.2f}, shroud {decel_ratio['shroud']:.2f}; unload the inducer (more incidence margin, smoother beta(m))"),
        check("TF-3", "leading-edge incidence spread hub -> shroud", inc_spread, 6.0, "max", "twist matched to the inlet velocity profile", unit="deg",
              note=f"hub {incidence[i_h]:+.1f}, mid {incidence[i_m]:+.1f}, shroud {incidence[i_s]:+.1f} deg"),
        check("TF-4", "exit meridional velocity distortion Cm_shroud / Cm_hub", cm_distortion, 1.5, "max",
              "curvature-driven hub/shroud imbalance feeding the diffuser", hard=False, note="less shroud curvature near the exit (longer axial length)"),
        check("TF-5", "blade loading parameter (W_ss - W_ps) / W_mean, max", loading, 0.9, "max", "Aungier / Stanitz practice 0.7-1.0", hard=False),
    ]
    return dict(n_span=n_span, n_chord=n_chord, incidence_deg=dict(hub=float(incidence[i_h]), mid=float(incidence[i_m]), shroud=float(incidence[i_s]),
                                                                    spread=inc_spread, all=[float(v) for v in incidence]),
                decel_ratio=decel_ratio, diffusion_ratio=diffusion, loading_max=loading, min_pressure_side_W=min_Wp, reverse_flow=reverse,
                exit_Cm_distortion=cm_distortion, exit=dict(Cm_hub=float(Cm[i_h, -1]), Cm_shroud=float(Cm[i_s, -1]), Ct_mean=float(Ct[:, -1].mean()),
                                                            Ct_meanline=Ct2_ml, beta_flow_te_deg=beta2_flow, deviation_te_deg=dev_te),
                streamlines=dict(hub=dict(m=m[i_h].tolist(), W_ss=Ws[i_h].tolist(), W_ps=Wp[i_h].tolist(), W=Wrel[i_h].tolist()),
                                 mid=dict(m=m[i_m].tolist(), W_ss=Ws[i_m].tolist(), W_ps=Wp[i_m].tolist(), W=Wrel[i_m].tolist()),
                                 shroud=dict(m=m[i_s].tolist(), W_ss=Ws[i_s].tolist(), W_ps=Wp[i_s].tolist(), W=Wrel[i_s].tolist())),
                blade_angle_law="cad/impeller.camber_grids (identical)", band="velocities +/-10 % (declared)", plots=plots, _rules=rules)


def _plot(m, sfrac, Ws, Wp, Wrel, incidence, t_st, beta_b, beta_f, Cm, pts, adir: Path, idx) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    adir.mkdir(parents=True, exist_ok=True)
    i_h, i_m, i_s = idx
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.8))
    for i, name, col in ((i_h, "hub", "tab:blue"), (i_m, "mid", "tab:green"), (i_s, "shroud", "tab:red")):
        ax[0].plot(sfrac[i], Ws[i], "-", color=col, label=f"{name} suction"); ax[0].plot(sfrac[i], Wp[i], "--", color=col, label=f"{name} pressure")
    ax[0].axhline(0, color="k", lw=0.6); ax[0].set_xlabel("meridional fraction"); ax[0].set_ylabel("relative velocity [m/s]"); ax[0].set_title("blade loading (Stanitz)")
    ax[0].legend(fontsize=7); ax[0].grid(alpha=.3)
    ax[1].plot(incidence, t_st, "-o", ms=3); ax[1].axvline(0, color="k", lw=0.6); ax[1].set_xlabel("LE incidence [deg]"); ax[1].set_ylabel("span fraction hub -> shroud")
    ax[1].set_title("hub-to-shroud incidence"); ax[1].grid(alpha=.3)
    cf = ax[2].contourf(pts[:, :, 0] * 1e3, pts[:, :, 1] * 1e3, Cm, 20, cmap="viridis")
    ax[2].set_xlabel("x [mm]"); ax[2].set_ylabel("r [mm]"); ax[2].set_title("meridional velocity Cm [m/s]"); ax[2].set_aspect("equal")
    fig.colorbar(cf, ax=ax[2], shrink=0.8)
    fig.suptitle("Impeller through-flow (L2.5): blade-aligned flow, curvature equilibrium, Stanitz loading")
    p = adir / "throughflow.png"; fig.tight_layout(); fig.savefig(p, dpi=110); plt.close(fig)
    return {"throughflow": str(p)}
