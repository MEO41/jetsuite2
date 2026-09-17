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

    def point(self, N_frac, beta, igv=0.0):
        if N_frac >= self.N_min:
            return self.cmap.point(N_frac, beta, igv)
        w, pr, eta = self.cmap.point(self.N_min, beta, igv)
        s = max(N_frac / self.N_min, 0.02)
        return w * s, 1.0 + (pr - 1.0) * s * s, max(eta * (0.5 + 0.5 * s), 0.3)

    def surge_margin(self, N_frac, W_corr, PR, igv=0.0):
        if N_frac >= self.N_min:
            return self.cmap.surge_margin(N_frac, W_corr, PR, igv)
        w0, pr0, _ = self.point(N_frac, 0.0, igv)
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


def controller_from_schedules(sch) -> Control:
    """Control object (limiter constants) from the control-stage schedules."""
    return Control(accel_limit=float(sch.accel(1.0)), decel_limit=float(sch.decel(1.0)), T04_limit=sch.T04_limit,
                   N_max_frac=sch.N_max_frac, idle_frac=sch.idle_N, fuel_ramp_s=sch.fuel_lag, light_off_N_frac=sch.light_off_N,
                   starter_torque_Nm=sch.starter_torque, starter_cutoff_frac=sch.starter_cutoff_N, self_sustain_frac=0.22)


def simulate(E: matching.EngineModel, amb, ctrl: Control, schedule: dict, N0_frac: float, target_frac,
             t_end: float, dt: float = 0.01, starter: bool = False, fuel_on: bool = True, governor_fail: bool = False,
             x0=None, p3_sensor_lost: bool = False, accel_derate: float = 1.0) -> dict:
    """Integrate the rotor from N0 toward target_frac (a number or a function of time).

    The fuel command runs through the controller: proportional governor on speed error,
    clipped between the deceleration and acceleration limit lines of the control stage
    (functions of corrected speed), a start ramp, the T04 topping limiter and the
    overspeed trip.  Bleed, nozzle area and IGV follow their schedules inside
    ``matching.evaluate``.  Everything is at fixed ambient conditions."""
    cmap_ext = LowSpeedMap(E.cmap)
    E_ext = matching.EngineModel(**{**E.__dict__, "cmap": cmap_ext})
    sch = E.sched if E.sched is not None else None
    Ns, WfP3s = np.array(schedule["N"]), np.array(schedule["WfP3"])
    # steady P3 vs N (the ECU's N-only fallback when the P3 sensor is lost): Wf / (Wf/P3) from the schedule
    P3s = np.array([wf / max(wp, 1e-12) for wf, wp in zip(schedule.get("Wf", []), schedule["WfP3"])]) if schedule.get("Wf") else None
    ramp_level = 0.0   # start ramp: fraction of the accel line reached so far
    held_prev = False  # previous step held an unconverged state
    x_lim_prev = None  # warm start for the T04-ceiling solve
    N = N0_frac * E.N_design
    Wf_cmd_lag = 0.0
    t = 0.0
    hist = dict(t=[], N_frac=[], T04=[], EGT=[], Wf=[], Fn=[], SM=[], P3=[], W=[], T_metal=[], P_excess=[], lim=[])
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
        # proportional governor on speed error, expressed as a Wf/P3 multiplier, clipped by the limit lines
        err = tf - Nf
        k_gov = sch.gain if sch is not None else 8.0
        acc_lim = (sch.accel(Nf) if sch is not None else ctrl.accel_limit)
        acc_lim = 1.0 + (acc_lim - 1.0) * accel_derate                 # sensor-loss derate of the accel line
        dec_lim = sch.decel(Nf) if sch is not None else ctrl.decel_limit
        mult = 1.0 + k_gov * err
        mult = min(max(mult, dec_lim), acc_lim)
        if starter and lit and sch is not None and ramp_level < 1.0:
            # start ramp: the command rises toward the accel line at the scheduled rate
            ramp_level = min(ramp_level + sch.start_ramp_rate * dt, 1.0)
            mult = min(mult, max(dec_lim, ramp_level * acc_lim))
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
            if p3_sensor_lost and P3s is not None and len(P3s):
                P3_prev = float(np.interp(Nf, Ns, P3s))                 # ECU fallback: scheduled P3, not the measured one
            Wf_cmd = mult * WfP3_ss * P3_prev
        Wf_cmd_lag += (Wf_cmd - Wf_cmd_lag) * min(dt / ctrl.fuel_ramp_s, 1.0)
        Wf = max(Wf_cmd_lag, 1e-5)
        # ---- quasi-steady components at (N, Wf)
        lim_state = 0     # 0 none, 1 fuel capped by the T04 loop, 2 fallback command cut, 3 held (unconverged)
        if lit and Wf > 1e-4:
            # ---- T04 topping limiter as a fuel ceiling on the command (the T04 loop has authority every step,
            # including while the fuel-driven solve is in the unconverged low-speed region)
            r_lim = None
            r_try = None
            # ceiling first, warm-started from the previous step's ceiling solution (a few Newton steps); the residual
            # scan only when the warm start fails.  Its x also seeds the fuel-driven solve, which is what keeps the
            # fuel-driven solve cheap in the start region.
            # the ceiling cannot bind within one step when the last converged point sits more than 15 % below the limit
            # (fuel lag 0.3 s vs dt) and the command is not at the accel line; skip the solve there
            far_below = (r_prev is not None and not held_prev and r_prev.get("T04", 0.0) < 0.85 * ctrl.T04_limit and mult < 0.999 * acc_lim)
            if not governor_fail and not far_below:
                x0_lim = [x_lim_prev[0], x_lim_prev[1], ctrl.T04_limit] if x_lim_prev is not None else [x[0], x[1], ctrl.T04_limit]
                r_lim = matching.solve_point(E_ext, amb, N, T04=ctrl.T04_limit, x0=x0_lim)
                if not r_lim["converged"]:
                    r_lim = matching.solve_point(E_ext, amb, N, T04=ctrl.T04_limit, x0=[x[0], x[1], ctrl.T04_limit], scan=True)
                if r_lim["converged"]:
                    x_lim_prev = r_lim["x"]
                else:
                    r_lim = None
            if r_lim is not None and Wf >= r_lim["Wf"]:
                r = r_lim
                Wf = r["Wf"]
                Wf_cmd_lag = Wf                      # anti-windup: the command cannot exceed the ceiling
                x = r["x"]
                lim_state = 1
            else:
                # the limit solution (same N, higher T04) is the best neighbour for the fuel-driven solve
                if r_try is not None and r_try["converged"] and r_lim is None:
                    r = r_try                                     # already solved, below the limiter's reach
                else:
                    r = _lowspeed_point(E_ext, amb, N, Wf, [r_lim["x"][0], r_lim["x"][1], x[2]] if r_lim is not None else x)
                if not r["converged"] and len(schedule.get("x", [])) > 0:
                    # retry from the steady-schedule state nearest this speed (the held x may be stale)
                    j = int(np.argmin(np.abs(Ns - Nf)))
                    r_try = _lowspeed_point(E_ext, amb, N, Wf, list(schedule["x"][j]))
                    if r_try["converged"]:
                        r = r_try
                if r["converged"]:
                    x = r["x"]
                elif r_prev is not None and hist["T04"] and hist["T04"][-1] > amb.T0 + 100:
                    # unconverged quasi-steady solve: hold the last converged state for this step and freeze the
                    # command at the held fuel (no wind-up while the model cannot follow)
                    r = dict(r_prev)
                    Wf_cmd_lag = min(Wf_cmd_lag, r["Wf"] * 1.05)
                    lim_state = 3
                # a-posteriori guard (governor-failure case has no limiter): cut the command if still over the limit
                if r["T04"] > ctrl.T04_limit and not governor_fail:
                    Wf_cmd_lag *= max(0.7, 1.0 - 2.0 * (r["T04"] - ctrl.T04_limit) / ctrl.T04_limit)
                    lim_state = 2
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
        hist["lim"].append(lim_state if lit else -1)
        held_prev = lit and lim_state == 3
        if "self_sustain_s" not in events and lit and P_start == 0.0 and P_excess > 0 and Nf >= ctrl.self_sustain_frac:
            events["self_sustain_s"] = t
        t += dt
    return dict(hist=hist, events=events, final_N_frac=N / E.N_design, x=x)
