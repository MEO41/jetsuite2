# Cold-flow compressor rig: p500 v0048

Generated 2026-09-16T19:41:07+00:00. Compressor-only test article for a measured surge line, choke flow and efficiency of this design's compressor.

## Test article

- Impeller: D2 131.4 mm, inducer tip r 42.0 mm, b2 7.69 mm, 8 + 8 blades, backsweep 30.0 deg, Ti-6Al-4V, tip clearance 0.26 mm (impeller.step (same file as the engine)).
- Diffuser: vaned, r4 90.7 mm, 11 vanes, LE angle 75.6065148561954 deg, throat 13.85 mm (diffuser.step).
- IGV: fitted, 17 vanes, settings [0.0, 12.5, 25.0] deg; manual indexed ring on the rig (0 / half / full setting), position read by potentiometer
- engine deswirl cascade replaced by a plenum collector (r = 1.6 r4) with 4 static taps; exit to the throttle.
- Bearings: 71902C-HC; engine front bearing pair on a rig shaft; rear support replaced by the drive coupling.

## Drive

electric (PMSM) with VFD, or a cold-air turbine if > 60 kW: 252.2 kW, 79750 rpm max, 19.97 N m at design; inline strain-gauge torque meter, 0.5 % FS; quill shaft, torsionally soft. compressor power at design 151.6 kW; sized with 25 % margin at 110 % speed.

## Instrumentation

| measurement | sensor | range | accuracy | closes |
|---|---|---|---|---|
| inlet total pressure / temperature | 4 Pt probes + 2 PT100 in the bellmouth | 0.7-1.1 bar, 260-330 K | 0.1 % / 0.3 K | corrected flow and speed |
| mass flow | calibrated bellmouth or upstream venturi (dP) | 0-1.13 kg/s | 0.5 % | every map point |
| impeller exit static pressure | 4 x Kulite fast statics at r = 1.03 r2, 20 kHz | 0-7.6 bar | 0.5 % | stall precursors (rotating stall), surge onset, diffuser inlet Mach |
| diffuser exit total pressure / temperature | 3 x 5-element Pt rakes + 3 TC rakes at r4 | 0-7.6 bar, 300-507 K | 0.2 % / 0.5 K | stage PR, isentropic efficiency (torque cross-check) |
| collector static pressure | 4 static taps | 0-7.6 bar | 0.2 % | back-pressure control |
| spool speed | 60-tooth wheel + magnetic pickup | 0-83375 rpm | 0.05 % | corrected speed |
| shaft torque | inline strain-gauge torque meter, 0.5 % FS | 0-29.95 N m | 0.5 % | power-based efficiency |
| tip clearance | 2 capacitive probes over the exducer | 0-1 mm | 10 um | clearance effect on efficiency and surge (MFG-2) |
| casing vibration | 2 accelerometers (radial, axial) | 0-50 g, 20 kHz | - | surge trip, rotor health |
| throttle position | motorised butterfly / cone valve with encoder | 0-100 % | 0.1 % | operating point control |

## Run matrix (predicted values from the L2 map; the band is the rig-calibrated +/- SM band in flow)

| N/N_d | rpm | W_corr choke | W_corr surge (predicted) | band | PR at surge | IGV settings |
|---|---|---|---|---|---|---|
| 0.40 | 29000 | 0.330 | 0.253 | 0.233-0.272 | 1.25 | [0.0, 12.5, 25.0] |
| 0.50 | 36250 | 0.378 | 0.315 | 0.291-0.339 | 1.44 | [0.0, 12.5, 25.0] |
| 0.60 | 43500 | 0.444 | 0.370 | 0.341-0.398 | 1.76 | [0.0, 12.5, 25.0] |
| 0.70 | 50750 | 0.531 | 0.460 | 0.425-0.495 | 2.14 | [0.0, 12.5, 25.0] |
| 0.80 | 58000 | 0.645 | 0.559 | 0.516-0.602 | 2.70 | [0.0, 12.5, 25.0] |
| 0.90 | 65250 | 0.792 | 0.659 | 0.609-0.710 | 3.53 | [0.0, 12.5, 25.0] |
| 1.00 | 72500 | 0.974 | 0.811 | 0.749-0.873 | 4.59 | [0.0, 12.5, 25.0] |
| 1.05 | 76125 | 1.077 | 0.933 | 0.861-1.004 | 5.09 | [0.0, 12.5, 25.0] |
| 1.10 | 79750 | 1.151 | 1.073 | 0.991-1.156 | 5.55 | [0.0, 12.5, 25.0] |

Procedure per line: open throttle to choke, record 8 points closing toward surge; last 3 points at 2 % flow steps inside the predicted band

## Safety

- surge_detection: Kulite rms > 3 x baseline or collector pressure drop > 5 % in 20 ms -> throttle opens fully (< 100 ms actuator)
- overspeed: trip at 112 % design speed
- vibration: trip at 20 g casing
- temperature: trip at 507 K diffuser exit
- max_surge_cycles: stop the line after 3 surge events; inspect the exducer

## What the rig closes

Replaces: compressor_map.lines[*].surge_W_corr (measured); compressor_map.lines[*].choke_W_corr; design-point eta (torque and rake)

Shrinks: rig band 0.077 -> read-off band ~0.02 (this compressor, no transcription unknowns); IGV extrapolation term -> measured pre-swirl effect

Ingest: stage `maps`, fields surge_W_corr per line, choke_W_corr, eta_design, tier L3 (jet ingest handoff/compressor_rig/ingest_template.json)
