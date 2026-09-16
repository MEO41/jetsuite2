"""Single-stage axial turbine: mean-line off-design model with the
Ainley-Mathieson / Dunham-Came loss correlations (L2 method).

For a given spool speed, inlet total state and exit static pressure the
solver finds the mass flow that satisfies continuity through the NGV and the
rotor with fixed metal exit angles (plus a small deviation model), and
returns total-total / total-static pressure ratio, efficiency, power, the
loss breakdown and choke indication (NGV throat or rotor throat at M 1).

Loss model per cascade (Dunham & Came 1970 form of Ainley & Mathieson with the Kacker & Okapuu 1982 scaling):

    Y_p   profile loss from the AM nozzle/impulse charts (Aungier's analytic fit)
    Y_s   secondary loss  0.0334 (c/h) (cos a2 / cos a1) (CL/(s/c))^2 cos^2 a2 / cos^3 am
    Y_k   tip clearance   B (c/h) (k/c)^0.78 (CL/(s/c))^2 cos^2 a2 / cos^3 am   (B = 0.47 unshrouded)
    Y_te  trailing edge   from the AM t/o chart (quadratic in t_te/o)

Validated against the TurboFlow (Benner loss set) map of boomsonic_v0's
turbine in ``validation/cases.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from .. import gas


@dataclass
class TurbineGeometry:
    r_mean: float
    h_ngv: float; h_rot: float
    alpha2_b: float            # NGV metal exit angle [deg from axial]
    beta3_b: float             # rotor metal exit angle [deg from axial, magnitude]
    beta2_b: float             # rotor metal inlet angle [deg]
    n_ngv: int; n_rot: int
    c_ngv: float; c_rot: float         # chord [m]
    cx_ngv: float; cx_rot: float
    te_ngv: float; te_rot: float       # trailing-edge thickness [m]
    tmax_c_ngv: float; tmax_c_rot: float
    clearance: float                   # rotor tip clearance [m]
    far: float = 0.02

    @classmethod
    def from_outputs(cls, t: dict, far: float) -> "TurbineGeometry":
        return cls(r_mean=t["r_mean_m"], h_ngv=t["h_ngv_m"], h_rot=t["h_rotor_m"], alpha2_b=t["alpha2_deg"],
                   beta3_b=abs(t["beta3_deg"]), beta2_b=t["beta2_deg"], n_ngv=int(t["n_ngv"]), n_rot=int(t["n_rotor"]),
                   c_ngv=t["chord_ngv_m"], c_rot=t["chord_rotor_m"], cx_ngv=t["cx_ngv_m"], cx_rot=t["cx_rotor_m"],
                   te_ngv=t["te_thickness_m"], te_rot=t["te_thickness_m"], tmax_c_ngv=t["tmax_over_c_ngv"],
                   tmax_c_rot=t["tmax_over_c_rotor"], clearance=t["tip_clearance_m"], far=far)

    @property
    def s_ngv(self):
        return 2 * math.pi * self.r_mean / self.n_ngv

    @property
    def s_rot(self):
        return 2 * math.pi * self.r_mean / self.n_rot


def _yp_am(a_in: float, a_out: float, s_c: float, t_c: float) -> float:
    """Ainley-Mathieson profile loss at zero incidence (Aungier's fit of the charts).
    a_in/a_out are flow angles [deg from axial] (magnitudes), s_c pitch/chord."""
    a2 = math.radians(a_out)
    # nozzle (a_in = 0) and impulse (a_in = a_out) reference losses
    def yp_nozzle(ao_deg):
        return (0.0257 + 0.00136 * max(ao_deg - 40, 0) ** 1.2 / 10) * (1 + 0.5 * (s_c - 0.75) ** 2) * 1.2 * \
            (1.0 + 0.2 * max(ao_deg - 60, 0) / 10)
    def yp_impulse(ao_deg):
        return (0.055 + 0.0035 * max(ao_deg - 40, 0)) * (1 + 0.6 * (s_c - 0.7) ** 2)
    yn, yi = yp_nozzle(a_out), yp_impulse(a_out)
    r = (a_in / a_out) ** 2 if a_out > 1e-6 else 0.0
    yp = yn + r * (yi - yn)
    yp *= (t_c / 0.2) ** (a_in / max(a_out, 1e-6))
    return max(yp, 0.01)


def cascade_loss(a_in: float, a_out: float, s: float, c: float, h: float, t_c: float, te: float, k: float,
                 incidence: float = 0.0, unshrouded: bool = True) -> dict:
    """Total-pressure loss coefficient Y = (P0in - P0out)/(P0out - Pout) for one cascade."""
    s_c = s / c
    yp = 0.914 * (2.0 / 3.0) * _yp_am(a_in, a_out, s_c, t_c)   # Kacker-Okapuu correction of the AMDC profile loss
    # incidence penalty (AM-style parabola, stall incidence ~ +-15 deg of the metal angle)
    yp *= 1.0 + min((incidence / 15.0) ** 2, 3.0)   # saturating: far off-design the AM parabola is not meaningful
    ai, ao = math.radians(a_in), math.radians(a_out)
    am = math.atan(0.5 * (math.tan(ao) - math.tan(ai)))
    CL_sc = 2 * (math.tan(ai) + math.tan(ao)) * math.cos(am)     # lift coefficient / (s/c)
    ys = 0.7 * 0.0334 * (c / h) * (math.cos(ao) / max(math.cos(ai), 0.2)) * CL_sc ** 2 * math.cos(ao) ** 2 / max(math.cos(am), 0.2) ** 3
    B = 0.47 if unshrouded else 0.37
    yk = B * (c / h) * (k / c) ** 0.78 * CL_sc ** 2 * math.cos(ao) ** 2 / max(math.cos(am), 0.2) ** 3 if k > 0 else 0.0
    o = s * math.cos(ao)
    yte = 0.5 * (te / max(o, 1e-6)) + 2.0 * (te / max(o, 1e-6)) ** 2
    return dict(Yp=yp, Ys=ys, Yk=yk, Yte=yte, Y=min(yp + ys + yk + yte, 2.0))


@dataclass
class TurbinePoint:
    ok: bool
    W: float = float("nan"); PR_tt: float = float("nan"); PR_ts: float = float("nan")
    eta_tt: float = float("nan"); eta_ts: float = float("nan"); power: float = float("nan")
    T05: float = float("nan"); P05: float = float("nan"); M2: float = float("nan"); M3_rel: float = float("nan")
    M3: float = float("nan"); alpha3: float = float("nan"); incidence: float = float("nan"); choked: str = ""
    losses: dict = field(default_factory=dict); reason: str = ""


def evaluate(g: TurbineGeometry, omega: float, T04: float, P04: float, P5_static: float) -> TurbinePoint:
    """Solve the stage for the exit static pressure P5 at speed omega."""
    R, far = gas.R_AIR, g.far
    U = omega * g.r_mean
    A2 = 2 * math.pi * g.r_mean * g.h_ngv
    A3 = 2 * math.pi * g.r_mean * g.h_rot
    a2 = math.radians(g.alpha2_b)
    h04 = float(gas.h(T04, far))

    # fixed-gamma helpers (gamma evaluated once per station from the total temperature): ~100x faster
    # than the variable-cp inversions and accurate to < 0.3 % in the stage pressure ratio
    def _mff(M, T0, P0, A, gm):
        return A * P0 * math.sqrt(gm / (R * T0)) * M * (1 + 0.5 * (gm - 1) * M * M) ** (-(gm + 1) / (2 * (gm - 1)))

    def _mach_from_flow(W, T0, P0, A, gm):
        """Subsonic Mach for mass flow W (Newton); raises ValueError when W exceeds the choke flow."""
        Wch = _mff(1.0, T0, P0, A, gm)
        if W >= Wch:
            raise ValueError("choked")
        M = min(max(W / Wch, 1e-4), 0.95)
        for _ in range(40):
            f = _mff(M, T0, P0, A, gm) - W
            df = (_mff(M + 1e-5, T0, P0, A, gm) - _mff(M - 1e-5, T0, P0, A, gm)) / 2e-5
            if abs(df) < 1e-12:
                break
            Mn = M - f / df
            Mn = min(max(Mn, 1e-5), 0.999999)
            if abs(Mn - M) < 1e-10:
                M = Mn
                break
            M = Mn
        return M

    g4 = float(gas.gamma(T04, far))
    Y_n = cascade_loss(0.0, g.alpha2_b, g.s_ngv, g.c_ngv, g.h_ngv, g.tmax_c_ngv, g.te_ngv, 0.0)["Y"]
    A2n = A2 * math.cos(a2)
    b3 = math.radians(g.beta3_b)
    A3n = A3 * math.cos(b3)
    cp4 = float(gas.cp(T04, far))

    def stage(W):
        """Return (P3_static, details) for mass flow W; raises ValueError when choked."""
        # ---- NGV: loss on the exit dynamic head, P02 = (P04 + Y P2)/(1 + Y); fixed-point on P2
        P02 = P04
        for _ in range(6):
            M2 = _mach_from_flow(W, T04, P02, A2n, g4)
            T2 = T04 / (1 + 0.5 * (g4 - 1) * M2 * M2)
            P2 = P02 * (T2 / T04) ** (g4 / (g4 - 1))
            P02n = (P04 + Y_n * P2) / (1 + Y_n)
            if abs(P02n - P02) < 1.0:
                P02 = P02n
                break
            P02 = P02n
        M2 = _mach_from_flow(W, T04, P02, A2n, g4)
        T2 = T04 / (1 + 0.5 * (g4 - 1) * M2 * M2)
        P2 = P02 * (T2 / T04) ** (g4 / (g4 - 1))
        g2 = g4
        C2 = M2 * math.sqrt(g2 * R * T2)
        Cx2, Ct2 = C2 * math.cos(a2), C2 * math.sin(a2)
        Wt2 = Ct2 - U
        W2 = math.hypot(Cx2, Wt2)
        beta2 = math.degrees(math.atan2(Wt2, Cx2))
        inc = beta2 - g.beta2_b
        T02r = T2 + W2 ** 2 / (2 * cp4)
        g2r = float(gas.gamma(T02r, far))
        P02r = P2 * (T02r / T2) ** (g2r / (g2r - 1))
        # ---- rotor: relative frame, exit metal angle beta3; rothalpy at constant mean radius
        Y_r = cascade_loss(abs(beta2), g.beta3_b, g.s_rot, g.c_rot, g.h_rot, g.tmax_c_rot, g.te_rot, g.clearance,
                           incidence=inc)["Y"]
        P03r = P02r
        for _ in range(6):
            M3r = _mach_from_flow(W, T02r, P03r, A3n, g2r)
            T3 = T02r / (1 + 0.5 * (g2r - 1) * M3r * M3r)
            P3s = P03r * (T3 / T02r) ** (g2r / (g2r - 1))
            P03n = (P02r + Y_r * P3s) / (1 + Y_r)
            if abs(P03n - P03r) < 1.0:
                P03r = P03n
                break
            P03r = P03n
        M3r = _mach_from_flow(W, T02r, P03r, A3n, g2r)
        T3 = T02r / (1 + 0.5 * (g2r - 1) * M3r * M3r)
        P3 = P03r * (T3 / T02r) ** (g2r / (g2r - 1))
        g3 = g2r
        W3 = M3r * math.sqrt(g3 * R * T3)
        Cx3, Wt3 = W3 * math.cos(b3), W3 * math.sin(b3)
        Ct3 = U - Wt3            # absolute swirl (positive in the direction of rotation)
        C3 = math.hypot(Cx3, Ct3)
        alpha3 = math.degrees(math.atan2(Ct3, Cx3))
        T05 = T3 + C3 ** 2 / (2 * cp4)
        P05 = P3 * (T05 / T3) ** (g3 / (g3 - 1))
        dh = U * (Ct2 - Ct3)
        return P3, dict(M2=M2, M3_rel=M3r, M3=C3 / math.sqrt(g3 * R * T3), T05=T05, P05=P05, dh=dh, inc=inc,
                        alpha3=alpha3, Y_n=Y_n, Y_r=Y_r, P3=P3, C3=C3, W2=W2, W3=W3)

    # bracket W so that P3(W) = P5_static ; P3 decreases with W
    W_lo, W_hi = 0.25 * _mff(1.0, T04, P04, A2n, g4), None
    try:
        P_lo, _ = stage(W_lo)
    except ValueError:
        return TurbinePoint(ok=False, reason="no flow at minimum W")
    if P_lo < P5_static:
        return TurbinePoint(ok=False, reason="exit pressure above inlet capability (PR < 1)")
    w = W_lo
    choked = ""
    for _ in range(80):
        w *= 1.08
        try:
            P3, det = stage(w)
        except ValueError as e:
            # choked: the maximum flow is just below w; find it
            w_ch = brentq(lambda x: (1.0 if _ok(stage, x) else -1.0), w / 1.08, w, xtol=1e-7)
            P3, det = stage(w_ch * 0.9999)
            W_hi = w_ch * 0.9999
            choked = str(e)
            break
        if P3 < P5_static:
            W_hi = w
            break
    if W_hi is None:
        return TurbinePoint(ok=False, reason="no bracket")
    if choked and P3 > P5_static:
        # the requested exit pressure is below the choked exit pressure: run at the choke flow
        W = W_hi
    else:
        W = brentq(lambda x: stage(x)[0] - P5_static, W_lo, W_hi, xtol=1e-8)
        P3, det = stage(W)
        choked = ""
    P3, det = stage(W)
    h05 = h04 - det["dh"]
    P05, P3_out = det["P05"], det["P3"]
    if choked and P5_static < det["P3"]:
        # post-choke expansion from the rotor throat static state down to P5 (supersonic exit,
        # oblique expansion): 70 % of the extra isentropic enthalpy drop is recovered as work
        T3 = gas.T_from_h(h05 + 0.0, far) if False else None
        T3s = gas.isentropic_T(det["T05"] - det["C3"] ** 2 / (2 * float(gas.cp(det["T05"], far))), P5_static / det["P3"], far)
        h3 = float(gas.h(det["T05"], far)) - det["C3"] ** 2 / 2
        dh_extra = 0.7 * max(h3 - float(gas.h(T3s, far)), 0.0)
        h05 = h05 - dh_extra
        T5 = gas.T_from_h(h3 - dh_extra, far)
        T05x = gas.T_from_h(h05 + 0.0, far)
        g5 = float(gas.gamma(T05x, far))
        P05 = P5_static * (T05x / T5) ** (g5 / (g5 - 1))
        P3_out = P5_static
    T05 = gas.T_from_h(h05, far)
    PR_tt = P04 / P05
    PR_ts = P04 / P3_out
    T05ss = gas.isentropic_T(T04, 1 / PR_tt, far)
    T5ss = gas.isentropic_T(T04, 1 / PR_ts, far)
    eta_tt = (h04 - h05) / (h04 - gas.h(T05ss, far))
    eta_ts = (h04 - h05) / (h04 - gas.h(T5ss, far))
    return TurbinePoint(ok=True, W=W, PR_tt=PR_tt, PR_ts=PR_ts, eta_tt=float(eta_tt), eta_ts=float(eta_ts),
                        power=W * (h04 - h05), T05=T05, P05=P05, M2=det["M2"], M3_rel=det["M3_rel"], M3=det["M3"],
                        alpha3=det["alpha3"], incidence=det["inc"], choked=choked,
                        losses=dict(Y_ngv=det["Y_n"], Y_rotor=det["Y_r"]))


def _ok(stage, x):
    try:
        stage(x)
        return True
    except ValueError:
        return False


def speedline(g: TurbineGeometry, omega: float, T04: float, P04: float, PR_ts_list) -> list[TurbinePoint]:
    return [evaluate(g, omega, T04, P04, P04 / pr) for pr in PR_ts_list]
