"""Steady-state component matching (off-design cycle) on the component maps.

Unknowns at a given spool speed N and flight condition: the compressor
operating point on its speed line (beta), the turbine pressure ratio and the
turbine inlet temperature (fuel is the control).  Residuals: shaft work
balance, turbine flow compatibility and nozzle continuity.  Solved with a
damped Newton (scipy ``fsolve``) from a warm start along the running line.

Also provides the inverse problem (find N for a target T4 or thrust) used by
the envelope sweep and the transient model (which supplies dN/dt from the
power imbalance instead of the work-balance residual).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import fsolve, brentq

from .. import gas_fast as gas          # tabulated thermo: same polynomials, ~30x faster in the matching loops
from .maps import CompressorMap, TurbineMap, corr_flow, phys_flow, T_REF, P_REF
from ..stages.common import isa


@dataclass
class EngineModel:
    """Everything the matching needs, frozen from the design state."""
    cmap: CompressorMap
    tmap: TurbineMap
    N_design: float          # rpm
    T01_design: float; P01_design: float
    T04_design: float; P04_design: float
    A8: float                # effective nozzle throat area [m2]
    eta_b: float; dp_b: float; dp_jp: float; eta_mech: float; bleed: float; P_off: float
    intake_rec: float; nozzle_Cv: float; LHV: float
    W_design: float; T04_max: float
    I_rotor: float = 1e-3    # kg m2 (transient only)

    @classmethod
    def from_design(cls, design) -> "EngineModel":
        o = design.outputs()
        mp = o["maps"]
        cy = o["cycle"]
        ci = design.doc["inputs"]["cycle"]
        ro = o.get("rotor", {})
        I = (ro.get("Ip_impeller", 0) + ro.get("Ip_turbine", 0)) * 1.05 + 0.2e-3 * (ro.get("Ip_impeller", 0) > 0)
        return cls(cmap=CompressorMap(mp["compressor_map"]), tmap=TurbineMap(mp["turbine_map"]),
                   N_design=o["speed"]["rpm"], T01_design=cy["Tt2_K"], P01_design=cy["Pt2_Pa"],
                   T04_design=cy["T04_K"], P04_design=cy["Pt4_Pa"], A8=cy["A8_eff_m2"],
                   eta_b=float(ci.get("eta_b", 0.97)), dp_b=float(ci.get("dp_burner", 0.05)), dp_jp=float(ci.get("dp_jetpipe", 0.02)),
                   eta_mech=float(ci.get("eta_mech", 0.99)), bleed=float(ci.get("bleed_frac", 0.01)),
                   P_off=float(ci.get("power_offtake_W", 100.0)), intake_rec=float(ci.get("intake_recovery", 0.98)),
                   nozzle_Cv=float(ci.get("nozzle_Cv", 0.98)), LHV=float(ci.get("fuel_LHV_J_per_kg", gas.LHV_KEROSENE)),
                   W_design=cy["W_kg_s"], T04_max=cy["T04_K"], I_rotor=max(I, 1e-5))


@dataclass
class Ambient:
    T0: float; P0: float; M0: float
    @classmethod
    def at(cls, altitude_m: float, mach: float, dT: float = 0.0):
        T, P, _ = isa(altitude_m, dT)
        return cls(T, P, mach)

    def ram(self, rec: float):
        a0 = gas.a_sound(self.T0)
        V0 = self.M0 * a0
        Tt = gas.T_from_h(gas.h(self.T0) + 0.5 * V0 * V0)
        Pt = self.P0 * math.exp((gas.phi(Tt) - gas.phi(self.T0)) / gas.R_AIR)
        if self.M0 > 1.0:
            g = 1.4
            pi_ns = ((((g + 1) * self.M0 ** 2) / ((g - 1) * self.M0 ** 2 + 2)) ** (g / (g - 1))
                     * ((g + 1) / (2 * g * self.M0 ** 2 - (g - 1))) ** (1 / (g - 1)))
            rec *= pi_ns
        return Tt, Pt * rec, V0


def _nozzle(W8, T08, P08, P0, A8, Cv, far):
    """Convergent nozzle: returns (P8, V8, T8, choked, W_capacity_at_P0)."""
    g8 = float(gas.gamma(T08, far))
    pr_crit = (2.0 / (g8 + 1.0)) ** (g8 / (g8 - 1.0))
    if P08 / P0 * pr_crit >= 1.0:
        T8, P8, g8 = gas.static_from_total(T08, P08, 1.0, far)
        V8 = math.sqrt(g8 * gas.R_AIR * T8)
        Wcap = gas.mass_flow_function(T08, P08, 1.0, A8, far)
        return P8, Cv * V8, T8, True, Wcap
    P8 = P0
    T8s = gas.isentropic_T(T08, P8 / P08, far)
    V8 = math.sqrt(max(2.0 * (gas.h(T08, far) - gas.h(T8s, far)), 0.0))
    M8 = V8 / gas.a_sound(T8s, far)
    Wcap = gas.mass_flow_function(T08, P08, max(M8, 1e-3), A8, far)
    return P8, Cv * V8, T8s, False, Wcap


def evaluate(E: EngineModel, amb: Ambient, N: float, beta: float, PR_t: float, T04: float) -> dict:
    """Cycle at given unknowns; returns the residual vector and all quantities."""
    Tt2, Pt2, V0 = amb.ram(E.intake_rec)
    theta, delta = Tt2 / T_REF, Pt2 / P_REF
    Nc_frac = (N / math.sqrt(theta)) / E.cmap.Nc_design
    Wc, PR_c, eta_c = E.cmap.point(Nc_frac, beta)
    PR_c = max(PR_c, 1.0005)
    W = phys_flow(Wc, Tt2, Pt2)
    eta_c = min(max(eta_c, 0.2), 0.95)
    Pt3 = Pt2 * PR_c
    T3s = gas.isentropic_T(Tt2, PR_c)
    dh_c = (gas.h(T3s) - gas.h(Tt2)) / eta_c
    Tt3 = gas.T_from_h(gas.h(Tt2) + dh_c)
    W3 = W * (1 - E.bleed)
    Pt4 = Pt3 * (1 - E.dp_b)
    T04 = min(max(T04, Tt3 + 30.0), 2200.0)     # physically admissible turbine inlet temperature
    PR_t = min(max(PR_t, 1.05), 6.0)
    far = gas.far_for_T04(Tt3, T04, E.eta_b, E.LHV)
    W4 = W3 * (1 + far)
    Wf = W3 * far
    # turbine
    theta_t, delta_t = T04 / E.tmap.m["T04_design"], Pt4 / E.tmap.m["P04_design"]
    Nt_frac = (N / math.sqrt(theta_t)) / (E.N_design)     # tmap N_frac is N/sqrt(T04/T04_design) / N_design
    Wct, eta_t, PR_tt = E.tmap.point(Nt_frac, PR_t)
    W4_map = Wct * math.sqrt(T_REF / E.tmap.m["T04_design"]) / (P_REF / E.tmap.m["P04_design"])   # physical at the map reference
    W4_map = W4_map * delta_t / math.sqrt(theta_t)        # physical at the actual T04, Pt4 (W ~ P/sqrt(T))
    eta_t = min(max(eta_t, 0.2), 0.95)
    Pt5 = Pt4 / PR_tt
    T5s = gas.isentropic_T(T04, 1 / PR_tt, far)
    dh_t = eta_t * (gas.h(T04, far) - gas.h(T5s, far))
    Tt5 = gas.T_from_h(gas.h(T04, far) - dh_t, far)
    P_turb = W4 * dh_t
    P_comp = W * dh_c / E.eta_mech + E.P_off * min(N / E.N_design, 1.2)   # accessory load grows with speed
    Pt8 = Pt5 * (1 - E.dp_jp)
    P8, V8, T8, choked, Wcap = _nozzle(W4, Tt5, Pt8, amb.P0, E.A8, E.nozzle_Cv, far)
    A8_needed = W4 / (P8 / (gas.R_AIR * T8) * max(V8 / E.nozzle_Cv, 1.0))
    Fg = W4 * V8 + (P8 - amb.P0) * E.A8
    Fn = Fg - W * V0
    res = np.array([(P_turb - P_comp) / max(P_comp, 1.0),          # work balance
                    (W4_map - W4) / max(W4, 1e-6),                  # turbine flow compatibility
                    (A8_needed - E.A8) / E.A8])                     # nozzle continuity
    return dict(res=res, W=W, W_corr=Wc, Nc_frac=Nc_frac, PR_c=PR_c, eta_c=eta_c, Tt2=Tt2, Pt2=Pt2, Tt3=Tt3, Pt3=Pt3,
                T04=T04, Pt4=Pt4, far=far, Wf=Wf, W4=W4, PR_t=PR_t, PR_tt=PR_tt, eta_t=eta_t, Tt5=Tt5, Pt5=Pt5,
                P_turb=P_turb, P_comp=P_comp, Fn=Fn, Fg=Fg, V8=V8, choked=choked, N=N, beta=beta, TSFC=Wf / max(Fn, 1e-6),
                SM=E.cmap.surge_margin(Nc_frac, Wc, PR_c), V0=V0, EGT=Tt5, dh_c=dh_c)


def solve_point(E: EngineModel, amb: Ambient, N: float, T04: float | None = None, Wf: float | None = None,
                x0=None) -> dict:
    """Steady state at spool speed N with T04 given, or Wf given (then T04 is solved)."""
    T04_fixed = T04
    if x0 is None:
        x0 = [0.5, math.log(2.0), T04_fixed or 1000.0]
    if T04_fixed is not None:
        # with T04 fixed the work balance is dropped (quasi-steady point for the transient model):
        # two unknowns (beta, ln PR_t), two residuals (turbine flow, nozzle continuity)
        def wrap2(x):
            r = evaluate(E, amb, N, x[0], math.exp(min(max(x[1], -1.0), 3.0)), T04_fixed)
            return [r["res"][1], r["res"][2]]
        x, info, ier, msg = fsolve(wrap2, x0[:2], full_output=True, xtol=1e-9, maxfev=300)
        x[1] = min(max(x[1], -1.0), 3.0)
        r = evaluate(E, amb, N, x[0], math.exp(x[1]), T04_fixed)
        r["converged"] = ier == 1 and float(np.max(np.abs(wrap2(x)))) < 1e-5
        r["x"] = [float(x[0]), float(x[1]), float(T04_fixed)]
        return r
    def wrap(x):
        beta, lnPR, t4 = x
        r = evaluate(E, amb, N, beta, math.exp(min(max(lnPR, -1.0), 3.0)), t4)
        return list(r["res"]) if Wf is None else [r["res"][0], r["res"][1], (r["Wf"] - Wf) / max(Wf, 1e-6)]
    x, info, ier, msg = fsolve(wrap, x0, full_output=True, xtol=1e-9, maxfev=400)
    beta, lnPR, t4 = x
    r = evaluate(E, amb, N, beta, math.exp(lnPR), t4)
    r["converged"] = ier == 1 and float(np.max(np.abs(wrap(x)))) < 1e-5
    r["x"] = [float(v) for v in x]
    return r


def solve_steady(E: EngineModel, amb: Ambient, N: float, x0=None) -> dict:
    """Steady state at speed N: T04 is the unknown (fuel is the control)."""
    def wrap(x):
        beta, lnPR, t4 = x
        r = evaluate(E, amb, N, beta, math.exp(min(max(lnPR, -1.0), 3.0)), t4)
        return list(r["res"])
    if x0 is None:
        x0 = [0.5, math.log(2.0), 900.0]
    x, info, ier, msg = fsolve(wrap, x0, full_output=True, xtol=1e-9, maxfev=600)
    beta, lnPR, t4 = x
    r = evaluate(E, amb, N, beta, math.exp(lnPR), t4)
    r["converged"] = ier == 1 and float(np.max(np.abs(r["res"]))) < 1e-5
    r["x"] = [float(v) for v in x]
    return r


def solve_steady_robust(E: EngineModel, amb: Ambient, N: float, x0=None) -> dict:
    """solve_steady with a coarse residual scan for the starting point when the warm start fails."""
    if x0 is not None:
        r = solve_steady(E, amb, N, x0)
        if r["converged"]:
            return r
    best = None
    for beta in np.linspace(-0.2, 0.9, 12):
        for PRt in (1.2, 1.35, 1.5, 1.7, 2.0, 2.4, 2.9, 3.5):
            for T4 in (600.0, 750.0, 900.0, 1050.0, 1200.0):
                try:
                    rr = evaluate(E, amb, N, beta, PRt, T4)
                except Exception:  # noqa: BLE001
                    continue
                n = float(np.max(np.abs(rr["res"])))
                if np.isfinite(n) and (best is None or n < best[0]):
                    best = (n, beta, PRt, T4)
    if best is None:
        r = solve_steady(E, amb, N, x0)
        return r
    r = solve_steady(E, amb, N, [best[1], math.log(best[2]), best[3]])
    return r


def running_line(E: EngineModel, amb: Ambient, N_fracs, T04_max: float | None = None) -> list[dict]:
    """Steady-state running line from low to high speed with warm starts and a scan fallback."""
    pts = []
    x0 = None
    for f in N_fracs:
        r = solve_steady_robust(E, amb, f * E.N_design, x0)
        r["N_frac"] = f
        pts.append(r)
        if r["converged"]:
            x0 = r["x"]
    return pts


def max_power_point(E: EngineModel, amb: Ambient, T04_max: float, N_max_frac: float = 1.05, x0=None) -> dict:
    """Highest thrust subject to T04 <= T04_max and N <= N_max: find N where T04(N) = T04_max."""
    def t4_of(f):
        r = solve_steady_robust(E, amb, f * E.N_design, x0)
        return r["T04"] if r["converged"] else float("nan"), r
    lo, hi = 0.6, N_max_frac
    t_hi, r_hi = t4_of(hi)
    if not math.isnan(t_hi) and t_hi <= T04_max:
        r_hi["limit"] = "N_max"
        return r_hi
    t_lo, r_lo = t4_of(lo)
    if math.isnan(t_lo):
        lo = 0.8
        t_lo, r_lo = t4_of(lo)
    if math.isnan(t_lo) or math.isnan(t_hi):
        r = r_hi if not math.isnan(t_hi) else r_lo
        r["limit"] = "N_max (low-speed bracket unconverged)" if not math.isnan(t_hi) else "unconverged"
        return r
    if t_lo >= T04_max:
        r_lo["limit"] = "T04 (at the bracket floor)"
        return r_lo
    f = brentq(lambda x: t4_of(x)[0] - T04_max, lo, hi, xtol=1e-4)
    _, r = t4_of(f)
    r["limit"] = "T04"
    return r
