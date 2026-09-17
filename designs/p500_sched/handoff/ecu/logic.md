# ECU logic: p500 v0055

Generated 2026-09-17T06:33:31+00:00. Tables in `schedules.csv` / `ecu_tables.json`; every number comes from the design state
(control stage L1, off-design L2, thermal L1) and the transient scenarios were run with these same limiters.

## States

| state | entry | exit |
|---|---|---|
| OFF | power on, fuel valve closed | start command |
| PURGE | starter to 5 % for 3 s, fuel off, igniter off | timer |
| CRANK | starter torque 0.5 N m | N >= 0.10 N_d -> IGNITION |
| IGNITION | igniter on, pilot fuel; light-off = EGT rise > 30 K in 2 s | lit -> ACCEL-TO-IDLE; not lit in 8 s -> ABORT (wet start) |
| ACCEL-TO-IDLE | Wf/P3 command ramps to the accel line at 0.25 of the line per s; starter off at 0.35 N_d | N >= 0.98 idle -> IDLE; N stalls below self-sustain for 5 s -> ABORT (hung start) |
| IDLE | proportional governor (gain 8.0) holds 0.50 N_d | throttle demand -> RUN; stop -> SHUTDOWN |
| RUN | governor on the demanded speed; command clipped between the decel and accel lines of `schedules.csv`; T04 / EGT topping as a fuel ceiling; N_max 1.05 topping; bleed / nozzle / IGV follow the schedule | stop -> SHUTDOWN; any abort condition -> ABORT |
| SHUTDOWN | fuel off, starter cool-down crank for 30 s or until EGT < 400 K | -> OFF |
| ABORT | fuel off immediately, bleed open, IGV to failure position, cool-down crank | -> OFF, fault logged |

## Limiter arbitration in RUN (every control cycle)

1. governor multiplier m = 1 + gain x (N_demand - N) / N_d
2. m = clip(m, decel_mult(Nc), accel_mult(Nc))
3. Wf_cmd = m x WfP3_steady(Nc) x P3 ; first-order lag 0.3 s
4. Wf_cmd = min(Wf_cmd, Wf at T04 limit 1200 K / EGT 1047 K)   (topping = fuel ceiling)
5. if N > N_max: m = decel_mult
6. bleed, A8, IGV from the schedule at Nc (rate-limited to the actuator capability)

## Faults

| fault | detection | action |
|---|---|---|
| overspeed | N > 1.10 N_d for 0.1 s (independent circuit) | fuel cut |
| hot start | T04 / EGT above limit during ACCEL-TO-IDLE | the ceiling holds it (transient `hot_start` case); if EGT > limit + 100 K -> ABORT |
| hung start | N below self-sustain 5 s after starter cutoff | ABORT, log starter torque margin (transient `hung_start`) |
| flameout | EGT drop > 100 K/s with fuel on: fuel off, auto-relight attempt above the windmill speed once | fuel off; one relight attempt above the windmill speed |
| surge | P3 falls > 5 % in 20 ms while N rises, or Kulite rms > 3x baseline: open bleed, cut to the decel line | |
| bearing over-temperature | T > 389 K (predicted bearing T + margin) or rising > 5 K/s | ABORT |
| vibration | > 40.0 um pk at the housing | ABORT |
| N sensor loss | both pickups invalid | abort (no safe fallback) |
| P3 sensor loss | P3 outside 0.5-6 bar or frozen | fuel from the N-only schedule (steady P3 at the ambient), accel line x0.8 (transient `p3_sensor_loss` case) |
| T04 / EGT sensor loss | thermocouple open | accel line x0.8, T04 limit -50 K, no hot-day corrections (transient `egt_derate` case) |
| IGV position loss | potentiometer invalid | vanes to the failure position, bleed interlock open (transient `igv_failed` case) |
