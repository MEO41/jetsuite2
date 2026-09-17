"""Stage 11 (core) - control and variable geometry as design objects.

Everything the off-design, envelope, transient and test-bench stages need to
run *through* a controller rather than around one:

* handling-bleed valve: fraction of compressor-exit flow dumped overboard as a
  function of corrected speed (closed above ``bleed_close_N``), with the port
  location on the casing for the geometry sheet;
* variable exhaust nozzle: A8 / A8_design schedule vs corrected speed;
* variable inlet guide vanes (optional): pre-swirl angle vs corrected speed;
* fuel schedule: acceleration and deceleration limit lines as Wf/P3 multipliers
  of the steady running-line schedule, idle governor speed, max-speed and
  max-T04 topping limiters, fuel-system lag;
* start schedule: light-off speed, starter cutoff, and the Wf/P3 ramp rate.

All schedules are tabulated vs corrected speed fraction and read by the
performance stages through ``perf.control.Schedules``; changing any of them
invalidates every analysis that consumed it.  Rules check the schedules
against practice (bleed fraction, nozzle range, IGV range, limiter ordering).
"""
from __future__ import annotations

import math

import numpy as np

from ..rules import check
from .common import inp, out

TIER = "L1"
CORE = True

DEFAULTS = {
    "bleed_enabled": False,
    "bleed_max_frac": 0.10,          # fraction of compressor flow dumped at full opening
    "bleed_close_N": 0.72,           # corrected speed fraction above which the valve is closed
    "bleed_open_N": 0.45,            # fully open at and below this speed
    "bleed_port": "diffuser_exit",   # diffuser_exit | deswirl_exit
    "nozzle_variable": False,
    "nozzle_A8_low_speed": 1.15,     # A8/A8_design at and below nozzle_open_N (opening lowers the running line)
    "nozzle_open_N": 0.5,
    "nozzle_close_N": 0.85,
    "igv_enabled": False,
    "igv_max_deg": 25.0,             # pre-swirl at and below igv_open_N (positive = with rotation, unloads the impeller)
    "igv_open_N": 0.5,
    "igv_close_N": 0.8,
    "igv_fail_position": "open",       # open (0 deg, no pre-swirl) | closed (igv_max_deg): where a failed actuator leaves the vanes
    "igv_rate_capability_deg_s": 30.0, # actuator slew capability
    "accel_limit_line": [[0.3, 1.5], [0.5, 1.4], [0.7, 1.3], [0.9, 1.25], [1.05, 1.15]],   # [Nc, Wf/P3 multiplier of steady]
    "decel_limit_line": [[0.3, 0.55], [0.6, 0.5], [1.05, 0.45]],
    "idle_N": 0.5,
    "N_max_frac": 1.05,
    "T04_limit_K": 1200.0,
    "fuel_lag_s": 0.3,
    "governor_gain": 8.0,
    "start_light_off_N": 0.10,
    "start_starter_cutoff_N": 0.35,
    "start_ramp_rate": 0.25,         # Wf/P3 command ramp during start, fraction of the accel line per second
    "start_starter_torque_Nm": 0.5,
    "_doc": {
        "bleed_enabled": "handling bleed valve fitted", "bleed_max_frac": "bleed fraction of compressor flow when fully open",
        "bleed_close_N": "corrected speed fraction above which the bleed is closed", "bleed_open_N": "fully open at/below this speed",
        "bleed_port": "port location for the geometry sheet", "nozzle_variable": "variable exhaust nozzle fitted",
        "nozzle_A8_low_speed": "A8/A8_design at low speed", "nozzle_open_N": "fully open at/below", "nozzle_close_N": "design area at/above",
        "igv_enabled": "variable inlet guide vanes fitted", "igv_max_deg": "pre-swirl angle at low speed [deg]",
        "igv_open_N": "max pre-swirl at/below", "igv_close_N": "zero pre-swirl at/above",
        "igv_fail_position": "vane position after an actuator failure: open (0 deg) or closed (igv_max_deg)",
        "igv_rate_capability_deg_s": "IGV actuator slew rate capability [deg/s]",
        "accel_limit_line": "acceleration limit: [[Nc, Wf/P3 multiplier of the steady schedule], ...]",
        "decel_limit_line": "deceleration limit: [[Nc, multiplier], ...] (lean blow-out protection)",
        "idle_N": "idle governor speed / design", "N_max_frac": "max-speed topping limiter / design", "T04_limit_K": "max-T04 topping limiter",
        "fuel_lag_s": "fuel system first-order lag", "governor_gain": "proportional speed governor gain (Wf/P3 multiplier per unit speed error)",
        "start_light_off_N": "ignition speed / design", "start_starter_cutoff_N": "starter cutoff speed / design",
        "start_ramp_rate": "start fuel ramp: fraction of the accel line per second (F3 lever)", "start_starter_torque_Nm": "starter motor torque",
    },
}

READS = ["inputs.control.*", "outputs.cycle.A8_geo_m2", "outputs.cycle.W_kg_s", "outputs.compressor.r4_m",
         "outputs.layout.x_deswirl_end_m", "outputs.layout.x_impeller_exit_m", "outputs.layout.envelope_radius_m"]

N_GRID = [0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1]


def _ramp(N, N_open, N_close, v_open, v_close):
    if N <= N_open:
        return v_open
    if N >= N_close:
        return v_close
    return v_open + (v_close - v_open) * (N - N_open) / (N_close - N_open)


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "control", k, DEFAULTS[k])  # noqa: E731
    be, nv, ig = bool(g("bleed_enabled")), bool(g("nozzle_variable")), bool(g("igv_enabled"))
    bleed = [_ramp(N, float(g("bleed_open_N")), float(g("bleed_close_N")), float(g("bleed_max_frac")), 0.0) if be else 0.0 for N in N_GRID]
    a8 = [_ramp(N, float(g("nozzle_open_N")), float(g("nozzle_close_N")), float(g("nozzle_A8_low_speed")), 1.0) if nv else 1.0 for N in N_GRID]
    igv = [_ramp(N, float(g("igv_open_N")), float(g("igv_close_N")), float(g("igv_max_deg")), 0.0) if ig else 0.0 for N in N_GRID]
    acc = [[float(a), float(b)] for a, b in g("accel_limit_line")]
    dec = [[float(a), float(b)] for a, b in g("decel_limit_line")]
    acc_grid = [float(np.interp(N, [p[0] for p in acc], [p[1] for p in acc])) for N in N_GRID]
    dec_grid = [float(np.interp(N, [p[0] for p in dec], [p[1] for p in dec])) for N in N_GRID]
    # bleed port location for the geometry sheet
    lay = out(doc, "layout")
    port_x = lay["x_deswirl_end_m"] if g("bleed_port") == "deswirl_exit" else lay["x_impeller_exit_m"] + 0.5 * (lay["x_deswirl_end_m"] - lay["x_impeller_exit_m"])
    port_r = lay["envelope_radius_m"]
    W = out(doc, "cycle", "W_kg_s")
    # port sized for the max bleed at ~0.8 of the low-speed compressor-exit density/velocity: d = sqrt(4 A / pi), A from W_bleed = rho V A with V ~ 120 m/s, rho ~ 2.5
    W_b = float(g("bleed_max_frac")) * W * 0.55
    A_port = W_b / (2.5 * 120.0) if be else 0.0
    d_port = math.sqrt(4 * A_port / math.pi) if A_port > 0 else 0.0
    # IGV actuation: the schedule slope in corrected speed times the fastest speed change of the class (95 % in ~4 s)
    igv_slope = (float(g("igv_max_deg")) / max(float(g("igv_close_N")) - float(g("igv_open_N")), 1e-6)) if ig else 0.0
    igv_rate_req = igv_slope * (0.95 - float(g("idle_N"))) / 4.0
    fail_pos = str(g("igv_fail_position")).lower()
    rules = [
        check("CTL-8", "IGV actuation rate required vs capability", igv_rate_req, float(g("igv_rate_capability_deg_s")), "max",
              "schedule slope x fastest class acceleration (idle -> 95 % in 4 s)", unit="deg/s", hard=False,
              note="a slower schedule (wider igv_open_N..igv_close_N) or a faster actuator"),
        check("CTL-9", "IGV failure position defined (open = 0 deg, closed = max)", 1.0 if fail_pos in ("open", "closed") else 0.0, 1.0, "min",
              "a failed actuator must leave the vanes at a known position; the transient stage runs the failed case", warn_margin=0.0),
        check("CTL-1", "bleed fraction at full opening", float(g("bleed_max_frac")) if be else 0.0, 0.15, "max",
              "handling bleeds 5-15 % (Saravanamuttoo)", note="larger bleeds cost too much low-speed thrust"),
        check("CTL-2", "variable nozzle area range A8_low / A8_design", float(g("nozzle_A8_low_speed")) if nv else 1.0, 1.35, "max",
              "translating-plug / iris practice 1.0-1.3", hard=False),
        check("CTL-3", "IGV pre-swirl range", float(g("igv_max_deg")) if ig else 0.0, 40.0, "max", "IGV practice <= 30-40 deg", hard=False),
        check("CTL-4", "accel line above decel line everywhere", min(a - d for a, d in zip(acc_grid, dec_grid)), 0.3, "min",
              "limiter ordering: accel multiplier - decel multiplier >= 0.3", warn_margin=0.0),
        check("CTL-5", "accel limiter at design speed", acc_grid[N_GRID.index(1.0)], 1.35, "max", "practice: 1.1-1.3 x steady Wf/P3 near max", hard=False),
        check("CTL-6", "idle governor speed", float(g("idle_N")), 0.35, "min", "micro-turbojet idle 30-50 %", hard=False),
        check("CTL-7", "start ramp rate (fraction of accel line per s)", float(g("start_ramp_rate")), 1.0, "max",
              "faster ramps raise the start T04 peak and the disc thermal gradient (F3)", hard=False),
    ]
    return dict(N_grid=N_GRID, bleed_frac=bleed, A8_ratio=a8, igv_deg=igv, accel_mult=acc_grid, decel_mult=dec_grid,
                bleed_enabled=be, nozzle_variable=nv, igv_enabled=ig, idle_N=float(g("idle_N")), N_max_frac=float(g("N_max_frac")),
                T04_limit_K=float(g("T04_limit_K")), fuel_lag_s=float(g("fuel_lag_s")), governor_gain=float(g("governor_gain")),
                start=dict(light_off_N=float(g("start_light_off_N")), starter_cutoff_N=float(g("start_starter_cutoff_N")),
                           ramp_rate=float(g("start_ramp_rate")), starter_torque_Nm=float(g("start_starter_torque_Nm"))),
                bleed_port=dict(location=str(g("bleed_port")), x_m=port_x, r_m=port_r, d_m=d_port, W_max_kg_s=W_b),
                igv_settings=sorted(set([0.0] + ([float(g("igv_max_deg")) * f for f in (0.5, 1.0)] if ig else []))),
                igv_fail_position=fail_pos, igv_fail_deg=(0.0 if fail_pos == "open" else float(g("igv_max_deg"))) if ig else 0.0,
                igv_rate_required_deg_s=igv_rate_req,
                _rules=rules)
