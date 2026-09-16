"""Transient engine model: rotor dynamics on the component maps.

    I omega dN/dt = P_turbine - P_compressor - P_parasitic (+ P_starter)

At every step the compressor point and the turbine pressure ratio come from
the quasi-steady flow-compatibility equations with the *commanded fuel flow*
(T04 follows from the energy balance); the work imbalance accelerates the
rotor.  Below the lowest mapped speed line the compressor map is extended
with a similarity scaling (PR-1 ~ N^2, W ~ N, efficiency falling), which is
enough for the start sequence to be represented but is flagged as such.

Fuel control: a Wf/P3 acceleration limiter and a lean deceleration floor,
both expressed as fractions of the steady running-line schedule, with a T04
limiter and an N governor on top.  Heat soak: first-order metal temperature
lag (informational).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import fsolve

from .. import gas
from . import matching
from .maps import phys_flow, T_REF, P_REF


@dataclass
class Control:
    accel_limit: float = 1.6        # max Wf/P3 relative to the steady-state schedule at that speed
    decel_limit: float = 0.45       # min Wf/P3 relative to steady schedule (lean blow-out protection)
    T04_limit: float = 1200.0       # over-temperature limit [K]
    N_max_frac: float = 1.05
    idle_frac: float = 0.42
    fuel_ramp_s: float = 0.3        # commanded fuel first-order lag [s] (pump / manifold)
    light_off_N_frac: float = 0.10
    starter_torque_Nm: float = 0.5
    starter_cutoff_frac: float = 0.35
    self_sustain_frac: float = 0.22


def _lowspeed_point(E: matching.EngineModel, amb, N, Wf, x0):
    """Quasi-steady component matching at fixed fuel flow.

    Solved as an outer secant on T04 around the 2-equation flow-compatibility problem
    (turbine flow, nozzle continuity) at fixed T04 -- far more robust than a 3-unknown
    Newton in the low-speed / start region."""
    t4 = float(x0[2]) if x0 is not None else 800.0
    x = list(x0) if x0 is not None else [0.4, math.log(1.5), t4]
    prev = None
    r = None
    for it in range(8):
        r = matching.solve_point(E, amb, N, T04=t4, x0=[x[0], x[1], t4])
        if not r["converged"]:
            r = matching.solve_point(E, amb, N, T04=t4, x0=[0.4, math.log(1.4), t4])
        err = (r["Wf"] - Wf) / max(Wf, 1e-6)
        if abs(err) < 1e-3:
            break
        # secant / fixed-slope update: Wf ~ (T04 - Tt3) -> dT04 = -err * (T04 - Tt3)
        if prev is not None and abs(err - prev[1]) > 1e-9:
            t4_new = t4 - err * (t4 - prev[0]) / (err - prev[1])
        else:
            t4_new = t4 - err * max(t4 - r["Tt3"], 50.0)
        prev = (t4, err)
        t4 = float(min(max(t4_new, r["Tt3"] + 30.0), 2200.0))
        x = [r["x"][0], r["x"][1], t4]
    r["converged"] = bool(r["converged"] and abs((r["Wf"] - Wf) / max(Wf, 1e-6)) < 0.05)
    r["x"] = [float(r["x"][0]), float(r["x"][1]), float(t4)]
    return r


class LowSpeedMap:
    """Extends the compressor map below its lowest speed line by similarity."""

    def __init__(self, cmap):
        self.cmap = cmap
        self.N_min = float(cmap.N.min())

    def point(self, N_frac, beta):
        if N_frac >= self.N_min:
            return self.cmap.point(N_frac, beta)
        w, pr, eta = self.cmap.point(self.N_min, beta)
        s = max(N_frac / self.N_min, 0.02)
        return w * s, 1.0 + (pr - 1.0) * s * s, max(eta * (0.5 + 0.5 * s), 0.3)

    def surge_margin(self, N_frac, W_corr, PR):
        if N_frac >= self.N_min:
            return self.cmap.surge_margin(N_frac, W_corr, PR)
        w0, pr0, _ = self.point(N_frac, 0.0)
        return (pr0 * W_corr) / (PR * w0) - 1.0

    @property
    def Nc_design(self):
        return self.cmap.Nc_design


def steady_schedule(E: matching.EngineModel, amb, N_fracs) -> dict:
    """Wf/P3 and T04 along the steady running line (the control-law reference)."""
    line = matching.running_line(E, amb, N_fracs)
    ok = [p for p in line if p["converged"]]
    return dict(N=[p["N"] / E.N_design for p in ok], WfP3=[p["Wf"] / p["Pt3"] for p in ok],
                T04=[p["T04"] for p in ok], Wf=[p["Wf"] for p in ok], x=[p["x"] for p in ok])


def simulate(E: matching.EngineModel, amb, ctrl: Control, schedule: dict, N0_frac: float, target_frac,
             t_end: float, dt: float = 0.01, starter: bool = False, fuel_on: bool = True, governor_fail: bool = False,
             x0=None) -> dict:
    """Integrate the rotor from N0 toward target_frac (a number or a function of time).

    Returns time histories and events.  Everything is at fixed ambient conditions."""
    cmap_ext = LowSpeedMap(E.cmap)
    E_ext = matching.EngineModel(**{**E.__dict__, "cmap": cmap_ext})
    Ns, WfP3s = np.array(schedule["N"]), np.array(schedule["WfP3"])
    N = N0_frac * E.N_design
    Wf_cmd_lag = 0.0
    t = 0.0
    hist = dict(t=[], N_frac=[], T04=[], EGT=[], Wf=[], Fn=[], SM=[], P3=[], W=[], T_metal=[], P_excess=[])
    events = {}
    lit = fuel_on and N0_frac >= ctrl.light_off_N_frac
    T_metal = amb.T0
    x = x0 or [0.4, math.log(1.6), 700.0]
    r_prev = None
    while t <= t_end:
        tf = target_frac(t) if callable(target_frac) else target_frac
        Nf = N / E.N_design
        # ---- control law: fuel command from the target speed with accel / decel limiters
        WfP3_ss = float(np.interp(Nf, Ns, WfP3s))
        # proportional governor on speed error, expressed as a Wf/P3 multiplier
        err = tf - Nf
        k_gov = 8.0
        mult = 1.0 + k_gov * err
        mult = min(max(mult, ctrl.decel_limit), ctrl.accel_limit)
        if governor_fail:
            mult = ctrl.accel_limit
            # independent overspeed trip: fuel cut 0.1 s after N exceeds 1.10 x design
            if Nf > 1.10:
                events.setdefault("overspeed_trip_s", t)
            if "overspeed_trip_s" in events and t >= events["overspeed_trip_s"] + 0.1:
                lit = False
                fuel_on = False
        if not lit:
            if fuel_on and Nf >= ctrl.light_off_N_frac:
                lit = True
                events.setdefault("light_off_s", t)
            mult = 0.0
        # quasi-steady point at the previous fuel to get P3
        Wf_cmd = 0.0
        if lit:
            # need P3: use the last solved point if available
            P3_prev = hist["P3"][-1] if hist["P3"] else amb.P0 * (1.0 + 0.5 * Nf)
            Wf_cmd = mult * WfP3_ss * P3_prev
        Wf_cmd_lag += (Wf_cmd - Wf_cmd_lag) * min(dt / ctrl.fuel_ramp_s, 1.0)
        Wf = max(Wf_cmd_lag, 1e-5)
        # ---- quasi-steady components at (N, Wf)
        if lit and Wf > 1e-4:
            r = _lowspeed_point(E_ext, amb, N, Wf, x)
            if r["converged"]:
                x = r["x"]
            elif r_prev is not None and hist["T04"] and hist["T04"][-1] > amb.T0 + 100:
                # unconverged quasi-steady solve: hold the last converged state for this step
                r = dict(r_prev)
            # T04 limiter: if over limit, reduce fuel to the limit (one re-solve; fallback: cut the command)
            if r["T04"] > ctrl.T04_limit and not governor_fail:
                r2 = matching.solve_point(E_ext, amb, N, T04=ctrl.T04_limit, x0=x)
                if r2["converged"]:
                    r = r2
                    Wf = r["Wf"]
                    Wf_cmd_lag = Wf
                else:
                    Wf_cmd_lag *= max(0.7, 1.0 - 2.0 * (r["T04"] - ctrl.T04_limit) / ctrl.T04_limit)
        else:
            # motoring: no combustion, compressor driven by the starter only
            r = matching.evaluate(E_ext, amb, N, 0.5, 1.2, max(amb.T0 + 40.0, 1.0))
            r["T04"], r["EGT"], r["Wf"] = r["Tt3"], r["Tt3"], 0.0
            r["P_turb"] = 0.0
            r["Fn"] = 0.0
        # ---- power balance and rotor acceleration
        omega = N * 2 * math.pi / 60
        P_start = ctrl.starter_torque_Nm * omega if (starter and Nf < ctrl.starter_cutoff_frac) else 0.0
        P_par = 0.002 * E.P_off + 50.0 * (Nf ** 2) * 10   # bearing / windage (small)
        P_excess = r["P_turb"] - r["P_comp"] + P_start - P_par
        dN = P_excess / (E.I_rotor * max(omega, 1.0)) * 60 / (2 * math.pi) * dt
        N = max(N + dN, 0.02 * E.N_design)
        if governor_fail is False and N > ctrl.N_max_frac * E.N_design:
            N = ctrl.N_max_frac * E.N_design
        T_metal += (r["EGT"] * 0.6 + r["Tt3"] * 0.4 - T_metal) * dt / 8.0
        r_prev = r
        hist["t"].append(t); hist["N_frac"].append(N / E.N_design); hist["T04"].append(r["T04"]); hist["EGT"].append(r["EGT"])
        hist["Wf"].append(r["Wf"]); hist["Fn"].append(r["Fn"]); hist["SM"].append(r.get("SM", float("nan")))
        hist["P3"].append(r["Pt3"]); hist["W"].append(r["W"]); hist["T_metal"].append(T_metal); hist["P_excess"].append(P_excess)
        if "self_sustain_s" not in events and lit and P_start == 0.0 and P_excess > 0 and Nf >= ctrl.self_sustain_frac:
            events["self_sustain_s"] = t
        t += dt
    return dict(hist=hist, events=events, final_N_frac=N / E.N_design, x=x)
