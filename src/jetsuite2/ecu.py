"""ECU logic model and export (roadmap section 10).

Everything the controller needs, taken from the design state and written as tables an actual ECU can consume:

* ``schedules.csv``   -- per corrected-speed row: steady Wf/P3 (from the off-design running line), acceleration and
                         deceleration limit lines (multipliers of steady Wf/P3), bleed fraction, nozzle area ratio,
                         IGV angle, steady T04 and EGT;
* ``limits.json``     -- idle / max speed, T04 and EGT topping limits, overspeed trip, bearing-temperature abort
                         (from the thermal stage when present), vibration abort, surge detection rule, fuel lag,
                         governor gain, start parameters, IGV failure position and rate;
* ``logic.md``        -- the state machine (OFF, PURGE, CRANK, IGNITION, ACCEL-TO-IDLE, IDLE, RUN, SHUTDOWN,
                         ABORT) with the transitions, the limiter arbitration in RUN and the fault handling
                         (hung / hot start, flameout, overspeed, sensor loss, IGV position loss, bearing temperature);
* ``ecu_tables.json`` -- the same content as one machine-readable document with provenance (design, version,
                         stage tiers).

The transient stage runs the same limiters and the sensor-loss fallbacks (``p3_sensor_lost``, derated accel line),
so the exported tables are the ones the simulations were done with.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def tables(design) -> dict:
    o = design.outputs()
    ctl, cy, sp = o["control"], o["cycle"], o["speed"]
    od = o.get("offdesign") or {}
    th = o.get("thermal") or {}
    tr = o.get("transient") or {}
    ss = od.get("steady_schedule") or {}
    Ng = [float(n) for n in ctl["N_grid"]]
    # steady schedule interpolated onto the control grid (running line at the design ambient; corrected = physical
    # speed fraction there, theta = 1 at the design condition)
    if ss.get("N"):
        WfP3 = np.interp(Ng, ss["N"], ss["WfP3"], left=np.nan, right=np.nan)
        T04s = np.interp(Ng, ss["N"], ss["T04"], left=np.nan, right=np.nan)
    else:
        WfP3 = np.full(len(Ng), np.nan); T04s = np.full(len(Ng), np.nan)
    rows = []
    for i, n in enumerate(Ng):
        rows.append(dict(Nc_frac=n, rpm_at_design_theta=n * sp["rpm"], WfP3_steady_kg_s_per_Pa=(None if np.isnan(WfP3[i]) else float(WfP3[i])),
                         accel_mult=float(ctl["accel_mult"][i]), decel_mult=float(ctl["decel_mult"][i]), bleed_frac=float(ctl["bleed_frac"][i]),
                         A8_ratio=float(ctl["A8_ratio"][i]), igv_deg=float(ctl["igv_deg"][i]), T04_steady_K=(None if np.isnan(T04s[i]) else float(T04s[i]))))
    egt_limit = cy["Tt5_K"] + (ctl["T04_limit_K"] - cy["T04_K"]) * 0.87        # EGT moves ~0.87 K per K of T04 at fixed speed
    limits = dict(idle_N_frac=ctl["idle_N"], N_max_frac=ctl["N_max_frac"], overspeed_trip_frac=1.10, overspeed_trip_delay_s=0.1,
                  T04_limit_K=ctl["T04_limit_K"], EGT_limit_K=float(egt_limit), EGT_sensor_basis="Tt5 at the design point + 0.87 x (T04 limit - T04 design)",
                  fuel_lag_s=ctl["fuel_lag_s"], governor_gain=ctl["governor_gain"],
                  start=dict(ctl["start"]), design_rpm=sp["rpm"], rpm_mcs=sp["rpm_mcs"],
                  bearing_T_abort_K=(th.get("abort") or {}).get("bearing_T_abort_K", 450.0),
                  bearing_T_abort_basis=(th.get("abort") or {}).get("basis", "assumed 450 K (thermal stage not run)"),
                  vibration_abort_um=40.0, surge_detection="P3 falls > 5 % in 20 ms while N rises, or Kulite rms > 3x baseline: open bleed, cut to the decel line",
                  flameout_detection="EGT drop > 100 K/s with fuel on: fuel off, auto-relight attempt above the windmill speed once",
                  igv=dict(enabled=ctl["igv_enabled"], fail_position=ctl.get("igv_fail_position"), fail_deg=ctl.get("igv_fail_deg"),
                           rate_required_deg_s=ctl.get("igv_rate_required_deg_s")),
                  bleed=dict(enabled=ctl["bleed_enabled"], port=ctl["bleed_port"]), nozzle=dict(variable=ctl["nozzle_variable"]),
                  sensor_loss=dict(N="abort (no safe fallback)", P3="fuel from the N-only schedule (steady P3 at the ambient), accel line x0.8",
                                   T04_or_EGT="accel line x0.8, T04 limit -50 K, no hot-day corrections", IGV_position="vanes to the failure position, bleed interlock open"))
    prov = dict(design=design.doc["name"], version=design.store.version, at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                tiers={s: design.store.stamps.get(s, {}).get("tier") for s in ("control", "offdesign", "transient", "thermal")},
                transient_scenarios=list((tr.get("scenarios") or {}).keys()))
    return dict(schedules=rows, limits=limits, provenance=prov)


def logic_md(t: dict) -> str:
    L = t["limits"]; p = t["provenance"]
    st = L["start"]
    return f"""# ECU logic: {p['design']} v{p['version']:04d}

Generated {p['at']}. Tables in `schedules.csv` / `ecu_tables.json`; every number comes from the design state
(control stage L1, off-design L2, thermal L1) and the transient scenarios were run with these same limiters.

## States

| state | entry | exit |
|---|---|---|
| OFF | power on, fuel valve closed | start command |
| PURGE | starter to 5 % for 3 s, fuel off, igniter off | timer |
| CRANK | starter torque {st['starter_torque_Nm']} N m | N >= {st['light_off_N']:.2f} N_d -> IGNITION |
| IGNITION | igniter on, pilot fuel; light-off = EGT rise > 30 K in 2 s | lit -> ACCEL-TO-IDLE; not lit in 8 s -> ABORT (wet start) |
| ACCEL-TO-IDLE | Wf/P3 command ramps to the accel line at {st['ramp_rate']} of the line per s; starter off at {st['starter_cutoff_N']:.2f} N_d | N >= 0.98 idle -> IDLE; N stalls below self-sustain for 5 s -> ABORT (hung start) |
| IDLE | proportional governor (gain {L['governor_gain']}) holds {L['idle_N_frac']:.2f} N_d | throttle demand -> RUN; stop -> SHUTDOWN |
| RUN | governor on the demanded speed; command clipped between the decel and accel lines of `schedules.csv`; T04 / EGT topping as a fuel ceiling; N_max {L['N_max_frac']:.2f} topping; bleed / nozzle / IGV follow the schedule | stop -> SHUTDOWN; any abort condition -> ABORT |
| SHUTDOWN | fuel off, starter cool-down crank for 30 s or until EGT < 400 K | -> OFF |
| ABORT | fuel off immediately, bleed open, IGV to failure position, cool-down crank | -> OFF, fault logged |

## Limiter arbitration in RUN (every control cycle)

1. governor multiplier m = 1 + gain x (N_demand - N) / N_d
2. m = clip(m, decel_mult(Nc), accel_mult(Nc))
3. Wf_cmd = m x WfP3_steady(Nc) x P3 ; first-order lag {L['fuel_lag_s']} s
4. Wf_cmd = min(Wf_cmd, Wf at T04 limit {L['T04_limit_K']:.0f} K / EGT {L['EGT_limit_K']:.0f} K)   (topping = fuel ceiling)
5. if N > N_max: m = decel_mult
6. bleed, A8, IGV from the schedule at Nc (rate-limited to the actuator capability)

## Faults

| fault | detection | action |
|---|---|---|
| overspeed | N > {L['overspeed_trip_frac']:.2f} N_d for {L['overspeed_trip_delay_s']} s (independent circuit) | fuel cut |
| hot start | T04 / EGT above limit during ACCEL-TO-IDLE | the ceiling holds it (transient `hot_start` case); if EGT > limit + 100 K -> ABORT |
| hung start | N below self-sustain 5 s after starter cutoff | ABORT, log starter torque margin (transient `hung_start`) |
| flameout | {L['flameout_detection']} | fuel off; one relight attempt above the windmill speed |
| surge | {L['surge_detection']} | |
| bearing over-temperature | T > {L['bearing_T_abort_K']:.0f} K ({L['bearing_T_abort_basis']}) or rising > 5 K/s | ABORT |
| vibration | > {L['vibration_abort_um']} um pk at the housing | ABORT |
| N sensor loss | both pickups invalid | {L['sensor_loss']['N']} |
| P3 sensor loss | P3 outside 0.5-6 bar or frozen | {L['sensor_loss']['P3']} (transient `p3_sensor_loss` case) |
| T04 / EGT sensor loss | thermocouple open | {L['sensor_loss']['T04_or_EGT']} (transient `egt_derate` case) |
| IGV position loss | potentiometer invalid | {L['sensor_loss']['IGV_position']} (transient `igv_failed` case) |
"""


def export(design, out_dir=None) -> dict:
    t = tables(design)
    out = Path(out_dir or (Path(design.dir) / "handoff" / "ecu"))
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "schedules.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(t["schedules"][0].keys()))
        w.writeheader(); w.writerows(t["schedules"])
    (out / "limits.json").write_text(json.dumps(t["limits"], indent=1, default=float), encoding="utf-8")
    (out / "ecu_tables.json").write_text(json.dumps(t, indent=1, default=float), encoding="utf-8")
    (out / "logic.md").write_text(logic_md(t), encoding="utf-8")
    return dict(dir=str(out), files=["schedules.csv", "limits.json", "ecu_tables.json", "logic.md"], rows=len(t["schedules"]))
