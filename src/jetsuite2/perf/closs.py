"""Centrifugal compressor stage: mean-line off-design model with the Oh /
Aungier loss set (L2 method).

Given the stage geometry and an operating point (N, mass flow, inlet total
state) it returns the total-total pressure ratio, efficiency, every loss
contribution, incidence angles, choke and stall indicators.  It is the
engine behind the component map, the surge/choke lines and the quality
assessment.

Loss set (Oh, Yoon & Chung 1997 "An optimum set of loss models for
performance prediction of centrifugal compressors", Aungier 2000):

internal (reduce the pressure rise)   parasitic (add to the work input)
  incidence   (Galvas / Conrad)         disc friction   (Daily & Nece)
  blade loading (Coppage)               recirculation   (Oh)
  skin friction (Jansen)                leakage         (Aungier)
  clearance   (Jansen)
  mixing      (Johnston & Dean)
  vaneless diffuser (Stanitz / Coppage friction)
  vaned diffuser incidence + channel (Aungier-type recovery model)
  deswirl / exit dump

Stall indicators: impeller inducer incidence (Rodgers), Coppage diffusion
factor, vaned-diffuser incidence and vaneless-space swirl angle (Senoo).
The surge line is the highest-flow onset of any indicator along a speed line
and carries a stated uncertainty band (see ``SURGE_UNCERTAINTY``).

Validated against the TurboFlow (Oh loss set, independent implementation)
maps of boomsonic_v0 and the JetCat P400 datasheet design point
(``validation/cases.py``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from .. import gas

SURGE_UNCERTAINTY = 0.30   # relative uncertainty on the predicted surge-margin (unvalidated criterion, see docs)


@dataclass
class CompressorGeometry:
    r1h: float; r1s: float; r2: float; b2: float
    beta1b_rms: float          # inducer blade angle at rms radius [deg from axial]
    beta2b: float              # backsweep [deg from radial]
    n_main: int; n_split: int; split_frac: float
    t_le: float; t_te: float   # blade thickness [m]
    clearance: float
    L_ax: float
    r3: float; r4: float; b3: float
    n_vanes: int               # 0 for vaneless
    vane_le_angle: float       # [deg from radial]
    vane_te_angle: float
    vane_throat: float         # [m], per passage width at the throat (vaned)
    roughness: float = 5e-6
    slip_model: str = "wiesner"
    # throat opening / (pitch x cos(beta_LE)): the blade unloads between the leading edge and the
    # throat plane, so the true throat is wider than the LE-normal opening.  1.35 reproduces the
    # 10 % design choke margin TurboFlow computed for the boomsonic_v0 impeller (validation case).
    throat_factor: float = 1.35

    @property
    def z_eff(self):
        return self.n_main + self.n_split * self.split_frac

    @property
    def z_exit(self):
        return self.n_main + self.n_split

    @classmethod
    def from_outputs(cls, c: dict) -> "CompressorGeometry":
        return cls(r1h=c["r1h_m"], r1s=c["r1s_m"], r2=c["r2_m"], b2=c["b2_m"],
                   beta1b_rms=c["blade_angle_le_rms_deg"], beta2b=c["backsweep_deg"],
                   n_main=int(c["n_main"]), n_split=int(c["n_splitter"]), split_frac=c["splitter_length_frac"],
                   t_le=0.5 * c["t_tip_m"], t_te=c["t_tip_m"], clearance=c["tip_clearance_m"], L_ax=c["axial_length_m"],
                   r3=c["r3_m"], r4=c["r4_m"], b3=c["b4_m"], n_vanes=int(c["n_vanes"] or 0),
                   vane_le_angle=c["vane_le_angle_deg"] or 0.0, vane_te_angle=c["vane_te_angle_deg"] or 0.0,
                   vane_throat=c["vane_throat_width_m"] or 0.0)


def slip_factor(g: CompressorGeometry, model: str = "wiesner", phi2: float = 0.28) -> float:
    z = g.z_eff
    b = math.radians(abs(g.beta2b))
    if model == "wiesner":
        return 1.0 - math.sqrt(math.cos(b)) / z ** 0.7
    if model == "stanitz":            # Stanitz (radial blades, extended with backsweep by Stodola-type term)
        return 1.0 - 0.63 * math.pi / z * (1.0 / (1.0 - phi2 * math.tan(b)))
    if model == "stodola":
        return 1.0 - math.pi * math.cos(b) / z
    if model == "busemann":           # Wiesner's fit with the Busemann limit correction for low r1/r2
        sig = 1.0 - math.sqrt(math.cos(b)) / z ** 0.7
        eps_lim = math.exp(-8.16 * math.cos(b) / z)
        r_ratio = g.r1s / g.r2
        if r_ratio > eps_lim:
            sig = sig * (1.0 - ((r_ratio - eps_lim) / (1.0 - eps_lim)) ** 3)
        return sig
    raise ValueError(model)


def inducer_choke_flow(g: CompressorGeometry, C1: float, T1: float, P1: float, omega: float, n_strips: int = 7) -> float:
    """Choking mass flow of the inducer throat, integrated over n annular strips with the
    local relative total state and the local blade angle (tan beta_b proportional to r)."""
    R = gas.R_AIR
    r1rms = math.sqrt(0.5 * (g.r1s ** 2 + g.r1h ** 2))
    tan_b_rms = math.tan(math.radians(g.beta1b_rms))
    edges = np.linspace(g.r1h, g.r1s, n_strips + 1)
    cp1 = float(gas.cp(T1))
    total = 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        r = 0.5 * (a + b)
        A = math.pi * (b ** 2 - a ** 2)
        beta_b = math.atan(tan_b_rms * r / r1rms)
        W1 = math.hypot(C1, omega * r)
        T01r = T1 + W1 ** 2 / (2 * cp1)
        g1r = float(gas.gamma(T01r))
        P01r = P1 * (T01r / T1) ** (g1r / (g1r - 1))
        blk = g.n_main * g.t_le / (2 * math.pi * r * math.cos(beta_b))
        A_th = A * math.cos(beta_b) * max(1 - blk, 0.3) * g.throat_factor
        total += gas.mass_flow_function(T01r, P01r, 1.0, A_th)
    return total


@dataclass
class PointResult:
    ok: bool
    PR_tt: float = float("nan"); eta_tt: float = float("nan"); PR_ts: float = float("nan")
    T02: float = float("nan"); P02: float = float("nan"); P03: float = float("nan")
    W: float = float("nan"); N: float = float("nan")
    incidence: float = float("nan"); incidence_vd: float = float("nan")
    M1s_rel: float = float("nan"); M2: float = float("nan"); M3: float = float("nan"); alpha2: float = float("nan")
    alpha3: float = float("nan"); D_f: float = float("nan"); de_haller: float = float("nan")
    losses: dict = field(default_factory=dict)
    choked: str = ""            # "" / "inducer" / "diffuser"
    stall: str = ""             # "" / "inducer" / "diffuser" / "vaneless" / "loading"
    dh_euler: float = float("nan"); dh_par: float = float("nan"); power: float = float("nan")
    reason: str = ""


def evaluate(g: CompressorGeometry, W: float, omega: float, T01: float, P01: float,
             slip_model: str | None = None) -> PointResult:
    """One operating point.  Returns PointResult(ok=False) when choked."""
    R = gas.R_AIR
    sm = slip_model or g.slip_model
    # ------------------------------------------------------------ inlet (station 1)
    A1 = math.pi * (g.r1s ** 2 - g.r1h ** 2) * 0.98
    try:
        M1 = gas.mach_from_area(W, T01, P01, A1)
    except ValueError:
        return PointResult(ok=False, choked="inducer", reason="inlet annulus choked", W=W)
    T1, P1, g1 = gas.static_from_total(T01, P01, M1)
    rho1 = P1 / (R * T1)
    a1 = math.sqrt(g1 * R * T1)
    C1 = M1 * a1
    r1rms = math.sqrt(0.5 * (g.r1s ** 2 + g.r1h ** 2))
    U1rms, U1s = omega * r1rms, omega * g.r1s
    W1rms, W1s = math.hypot(C1, U1rms), math.hypot(C1, U1s)
    beta1 = math.degrees(math.atan2(U1rms, C1))
    inc = beta1 - g.beta1b_rms
    M1s_rel = W1s / a1
    # inducer throat choke: spanwise integration of the relative-frame choking capacity
    # (blade angle law tan(beta_b) ~ r, i.e. designed for uniform axial inflow)
    W_choke = inducer_choke_flow(g, C1, T1, P1, omega)
    if W >= 0.999 * W_choke:
        return PointResult(ok=False, choked="inducer", reason="inducer throat choked", W=W, M1s_rel=M1s_rel, incidence=inc)

    # ------------------------------------------------------------ impeller exit (station 2)
    U2 = omega * g.r2
    sig = slip_factor(g, sm)
    b2r = math.radians(abs(g.beta2b))
    B_metal = g.z_exit * 0.5 * (g.t_te + g.t_te) / (2 * math.pi * g.r2 * math.cos(b2r))
    # iterate exit density: Cm2 from continuity with losses feeding back through T2/P2
    rho2 = rho1 * 2.0
    cp01 = float(gas.cp(T01))
    h01 = float(gas.h(T01))
    res = None
    for _ in range(60):
        Cm2 = W / (rho2 * 2 * math.pi * g.r2 * g.b2 * (1 - B_metal - 0.06))
        Ct2 = sig * U2 - Cm2 * math.tan(b2r)
        if Ct2 <= 0:
            return PointResult(ok=False, reason="negative exit swirl (flow far beyond design)", W=W, choked="inducer")
        C2 = math.hypot(Cm2, Ct2)
        W2 = math.hypot(Cm2, U2 - Ct2)
        alpha2 = math.degrees(math.atan2(Ct2, Cm2))
        dh_euler = U2 * Ct2
        # ---------------- parasitic work
        mu = 1.458e-6 * T01 ** 1.5 / (T01 + 110.4)
        Re_df = rho2 * U2 * g.r2 / mu
        f_df = 2.67 / Re_df ** 0.5 if Re_df < 3e5 else 0.0622 / Re_df ** 0.2
        dh_df = f_df * rho2 * g.r2 ** 2 * U2 ** 3 / (4 * W)
        # Coppage diffusion factor (Oh et al. eq. for the blade-loading loss)
        D_f = 1 - W2 / W1s + 0.75 * (dh_euler / U2 ** 2) / ((W1s / W2) * ((g.z_eff / math.pi) * (1 - g.r1s / g.r2) + 2 * g.r1s / g.r2))
        D_f = max(D_f, 0.0)
        # Oh recirculation term; alpha2 and D_f capped: the sinh law is meant for near-design swirl
        dh_rc = 8e-5 * math.sinh(3.5 * math.radians(min(alpha2, 75.0)) ** 3) * min(D_f, 0.9) ** 2 * U2 ** 2
        dh_lk = 0.5 * (g.clearance / g.b2) * 0.6 * Ct2 * U2 * 0.3   # Aungier-type leakage work, small
        dh_par = dh_df + dh_rc + dh_lk
        if dh_par > 1.0 * dh_euler:
            return PointResult(ok=False, reason="parasitic work exceeds the Euler work (deep stall region)", W=W)
        # ---------------- internal losses
        dh_inc = 0.6 * W1rms ** 2 * math.sin(math.radians(inc)) ** 2 / 2
        dh_bl = 0.05 * D_f ** 2 * U2 ** 2
        L_b = math.pi / 8 * (2 * g.r2 - (g.r1s + g.r1h) - g.b2 + 2 * g.L_ax) * (2 / (math.cos(b2r) + math.cos(math.radians(g.beta1b_rms))))
        D_hyd = (2 * g.r2 / (g.z_exit / math.pi / math.cos(b2r) + 2 * g.r2 / g.b2)
                 + (g.r1s - g.r1h) * 0.5 / (1.0 + 0.5 * g.z_eff * (g.r1s - g.r1h) / (math.pi * r1rms * math.cos(math.radians(g.beta1b_rms)))))
        W_avg = math.sqrt(0.5 * (W1rms ** 2 + W2 ** 2))
        Re_b = rho1 * W_avg * D_hyd / mu
        C_f = 0.0412 / max(Re_b, 1e4) ** 0.1925 * (1 + 0.5 * (g.roughness / D_hyd) ** 0.2)
        dh_sf = 2 * C_f * L_b / D_hyd * W_avg ** 2
        dh_cl = (0.6 * (g.clearance / g.b2) * Ct2
                 * math.sqrt(max(4 * math.pi / (g.b2 * g.z_exit) * (g.r1s ** 2 - g.r1h ** 2)
                                 / ((g.r2 - g.r1s) * (1 + rho2 / rho1)) * Ct2 * C1, 0.0)))
        eps_w = 0.15
        dh_mix = (1 / (1 + math.tan(math.radians(alpha2)) ** 2)) * ((1 - eps_w - 1.0 * (g.b3 / g.b2)) / (1 - eps_w)) ** 2 * C2 ** 2 / 2
        dh_mix = abs(dh_mix)
        int_imp = dh_inc + dh_bl + dh_sf + dh_cl + dh_mix
        h02 = h01 + dh_euler + dh_par
        T02 = gas.T_from_h(h02)
        h02s = h01 + dh_euler + dh_par - int_imp
        if h02s <= h01:
            return PointResult(ok=False, reason="losses exceed work", W=W)
        T02s = gas.T_from_h(h02s)
        P02 = P01 * math.exp((gas.phi(T02s) - gas.phi(T01)) / R)
        cp2 = float(gas.cp(T02))
        T2 = T02 - C2 ** 2 / (2 * cp2)
        if T2 <= 0:
            return PointResult(ok=False, reason="supersonic exit", W=W)
        g2 = float(gas.gamma(T2))
        P2 = P02 * (T2 / T02) ** (g2 / (g2 - 1))
        rho2_new = P2 / (R * T2)
        if abs(rho2_new - rho2) < 1e-6 * rho2:
            rho2 = rho2_new
            break
        rho2 = 0.5 * (rho2 + rho2_new)
    M2 = C2 / math.sqrt(g2 * R * T2)
    # ------------------------------------------------------------ vaneless space (2 -> 3)
    Ct3 = Ct2 * g.r2 / g.r3
    # continuity with density ~ rho2 (short gap), blockage mixed out
    Cm3 = Cm2 * g.r2 * g.b2 / (g.r3 * g.b3) * (1 - B_metal - 0.06)
    C3 = math.hypot(Cm3, Ct3)
    alpha3 = math.degrees(math.atan2(Ct3, Cm3))
    a_mean = math.radians(0.5 * (alpha2 + alpha3))
    Cf_v = 0.005 * (1.8e5 / max(Re_b, 1e4)) ** 0.2
    dh_vld = Cf_v * (g.r3 - g.r2) / (g.b2 * math.cos(a_mean)) * C2 ** 2 / 2 * 2.0
    stall = ""
    if alpha3 > 78.0:
        stall = "vaneless"
    # ------------------------------------------------------------ vaned diffuser (3 -> 4)
    choked = ""
    inc_vd = float("nan")
    if g.n_vanes > 0:
        inc_vd = alpha3 - g.vane_le_angle
        # throat choke check at the vane throat (total conditions ~ P02 - vaneless loss)
        h03s = h02s - dh_vld
        T03s = gas.T_from_h(h03s)
        P03v = P01 * math.exp((gas.phi(T03s) - gas.phi(T01)) / R)
        A_th_vd = g.n_vanes * g.vane_throat * g.b3 * 0.96
        W_ch_vd = gas.mass_flow_function(T02, P03v, 1.0, A_th_vd)
        if W >= 0.999 * W_ch_vd:
            return PointResult(ok=False, choked="diffuser", reason="vaned diffuser throat choked", W=W,
                               incidence=inc, incidence_vd=inc_vd, M1s_rel=M1s_rel, M2=M2, alpha3=alpha3)
        dh_vd_inc = 0.6 * C3 ** 2 * math.sin(math.radians(inc_vd)) ** 2 / 2
        # channel: static recovery Cp falls with |incidence|; loss = (1 - Cp - (A3/A4)^2) q3
        AR = (2 * math.pi * g.r4 * math.cos(math.radians(g.vane_te_angle))) / (g.n_vanes * g.vane_throat)
        AR = min(max(AR, 1.2), 4.0)
        Cp0 = 0.62 * (1 - 1 / AR ** 2) / (1 - 1 / 2.5 ** 2)
        Cp = Cp0 * max(1.0 - 0.9 * (inc_vd / 12.0) ** 2, 0.2)
        dh_vd_ch = max(1 - Cp - 1 / AR ** 2, 0.05) * C3 ** 2 / 2
        C4 = C3 / AR * 1.05
        if inc_vd > 5.0:
            stall = stall or "diffuser"
    else:
        Ct4 = Ct2 * g.r2 / g.r4
        Cm4 = Cm2 * g.r2 * g.b2 / (g.r4 * g.b3) * (1 - B_metal - 0.06)
        C4 = math.hypot(Cm4, Ct4)
        dh_vd_inc = 0.0
        dh_vd_ch = Cf_v * (g.r4 - g.r3) / (g.b3 * math.cos(a_mean)) * C3 ** 2 / 2 * 2.0
        alpha4 = math.degrees(math.atan2(Ct4, Cm4))
        if alpha4 > 80.0:
            stall = stall or "vaneless"
    dh_exit = 0.15 * C4 ** 2 / 2       # deswirl / dump
    int_total = int_imp + dh_vld + dh_vd_inc + dh_vd_ch + dh_exit
    h03s_all = h01 + dh_euler + dh_par - int_total
    if h03s_all <= h01:
        return PointResult(ok=False, reason="diffuser losses exceed work", W=W)
    T03s = gas.T_from_h(h03s_all)
    P03 = P01 * math.exp((gas.phi(T03s) - gas.phi(T01)) / R)
    PR = P03 / P01
    T03ss = gas.isentropic_T(T01, PR)
    eta = (gas.h(T03ss) - h01) / (h02 - h01)
    # impeller stall indicators: the tolerable positive incidence grows as the inducer relative Mach falls
    # (Rodgers: ~5-6 deg at M1s_rel 1.2+, 12-15 deg at low speed)
    i_stall = 6.0 + 8.0 * min(max((1.2 - M1s_rel) / 0.6, 0.0), 1.0)
    if inc > i_stall:
        stall = "inducer"
    if D_f > 0.72:            # Coppage/Aungier: D_f 0.6 ideal, > ~0.7 stall-prone
        stall = stall or "loading"
    de_haller = W2 / W1rms
    return PointResult(ok=True, PR_tt=PR, eta_tt=float(eta), PR_ts=P2 / P01, T02=T02, P02=P02, P03=P03, W=W,
                       N=omega * 60 / (2 * math.pi), incidence=inc, incidence_vd=inc_vd, M1s_rel=M1s_rel, M2=M2,
                       M3=C3 / math.sqrt(g2 * R * T2), alpha2=alpha2, alpha3=alpha3, D_f=D_f, de_haller=de_haller,
                       losses=dict(incidence=dh_inc, blade_loading=dh_bl, skin_friction=dh_sf, clearance=dh_cl, mixing=dh_mix,
                                   vaneless=dh_vld, vaned_incidence=dh_vd_inc, vaned_channel=dh_vd_ch, exit=dh_exit,
                                   disc_friction=dh_df, recirculation=dh_rc, leakage=dh_lk),
                       choked=choked, stall=stall, dh_euler=dh_euler, dh_par=dh_par, power=W * (h02 - h01))


def speedline(g: CompressorGeometry, omega: float, T01: float, P01: float, n_pts: int = 24,
              slip_model: str | None = None) -> dict:
    """Sweep mass flow from the choke limit down to stall on one speed line.

    Returns dict(N, W, PR, eta, stall_W, choke_W, surge_index, points)."""
    # scan a geometric grid of mass flows from 3 % of the inlet-annulus choke flow: find the valid band
    # [first ok, last ok] and the choke above it
    A1 = math.pi * (g.r1s ** 2 - g.r1h ** 2) * 0.98
    W_ann = gas.mass_flow_function(T01, P01, 1.0, A1)
    grid = 0.03 * W_ann * 1.12 ** np.arange(0, 40)
    last_ok, first_bad_above = None, None
    for w in grid:
        r = evaluate(g, w, omega, T01, P01, slip_model)
        if r.ok:
            last_ok = w
        elif last_ok is not None:
            first_bad_above = w
            break
    if last_ok is None:
        return dict(N=omega * 60 / (2 * math.pi), ok=False, reason="no valid operating point at this speed")
    if first_bad_above is None:
        return dict(N=omega * 60 / (2 * math.pi), ok=False, reason="no choke found")
    W_choke = brentq(lambda w: 1.0 if evaluate(g, w, omega, T01, P01, slip_model).ok else -1.0,
                     last_ok, first_bad_above, xtol=1e-6)
    pts = []
    Ws = np.linspace(0.999 * W_choke, 0.30 * W_choke, n_pts)
    stall_W = None
    for w in Ws:
        r = evaluate(g, w, omega, T01, P01, slip_model)
        if not r.ok:
            continue
        pts.append(r)
        if r.stall and stall_W is None:
            stall_W = w
    if not pts:
        return dict(N=omega * 60 / (2 * math.pi), ok=False, reason="no valid points")
    PRs = [p.PR_tt for p in pts]
    i_peak = int(np.argmax(PRs))
    W_peak = pts[i_peak].W
    # surge = the higher-flow of (first stall indicator, peak PR)
    W_surge = max([w for w in (stall_W, W_peak) if w is not None])
    return dict(N=omega * 60 / (2 * math.pi), ok=True, W=[p.W for p in pts], PR=PRs, eta=[p.eta_tt for p in pts],
                stall=[p.stall for p in pts], incidence=[p.incidence for p in pts], alpha3=[p.alpha3 for p in pts],
                choke_W=W_choke, surge_W=W_surge, peak_PR_W=W_peak, stall_indicator_W=stall_W,
                surge_reason=(next((p.stall for p in pts if p.W <= W_surge and p.stall), "peak-PR")), points=pts)
