# p500 - test-readiness report (v15)

## Predicted performance (sea-level static bench)

| quantity | prediction | confidence / basis |
|---|---|---|
| max thrust | 512.5 N at N 0.99 (T04-limited) | L2 maps validated vs TurboFlow within 5 %; surge line +/-30 % |
| TSFC at max | 0.1179 kg/N/h | cycle + loss models; fleet datasheets within ~10 % |
| T04 at max / EGT | 1150 / 1004 K | L2; EGT sensor sees T5 +/- pattern factor |
| idle | N 0.4, thrust 28.4 N, SM -0.17 | L2; low-speed map extrapolated below N 0.4 (L1) |
| spool speed at max | 72500 rpm design, 76125 MCS | limits: turbine_disc |
| start | light-off 3.45 s, self-sustain 7.75 s, idle 15.7 s, T04 peak 1002 K | L2 quasi-steady; starter torque assumed |
| slam accel idle->95 % | 8.35 s, SM min -0.0819 | L2 |

## Operating limits

* T04 limiter 1200 K; N max 1.05 x design; accel limiter 1.3 x steady Wf/P3; decel floor 0.45.
* Cleared envelope: 95/96 grid points with SM >= floor; worst SM 0.07715 at 9000.0 m / M 0.8 / dT 0.0 K.
* Bench: sea level static only; ambient temperature offset 0 K assumed.

## Expected failure modes and precursors

| failure mode | predicted margin | precursor to watch |
|---|---|---|
| compressor surge (low speed / slam accel) | SM min -0.1653 on the running line; -0.08191 during accel | P3 oscillation, thrust drop, EGT rise; audible chuffing |
| turbine over-temperature | T04 limiter 1200 K; hot-start peak 1088 K | EGT above the limiter, slow acceleration, discolouration of the NGV |
| rotor critical / vibration | criticals 23844, 29174 rpm; G2.5 amplitude 1.32 um | vibration peak while traversing rigid modes; growth with time = unbalance change |
| bearing distress | DN 1.14e+06, L10 295 h | bearing housing temperature > 450 K, rising vibration, metal in the oil |
| combustor blow-out (lean, decel) | LBO margin idle 1.721 | EGT drop > 100 K/s with fuel on; relight needed |
| blade resonance | 0 crossings in range | vibration at vane-passing orders; dwell restrictions |
| impeller rub | worst-case clearance remaining 0.093 mm | P3 loss, vibration, witness marks on the shroud |

## Abort criteria

* EGT > 1250 K
* N > 1.07 N_design
* vibration > 40 um pk at the housing
* P3 falls while N rises (surge)
* bearing temperature > 450 K or rising > 5 K/s
* fuel pressure loss or flame-out (EGT drop > 100 K/s)
* any thrust-frame anomaly

## Instrumentation plan

| measurement | sensor | location | range | expected | tolerance | closes |
|---|---|---|---|---|---|---|
| spool speed N | optical / magnetic pickup on the shaft nut | impeller nose | 0-150 krpm | 72500 rpm at max | +/-0.5 % | all speed-referenced predictions |
| thrust | load cell in the thrust frame | engine mount | 0-750 N | 533 N at max | +/-2 % | cycle + nozzle model |
| fuel flow | turbine or Coriolis flowmeter | pump outlet | 0-4 kg/h | 63.43 kg/h at max | +/-1.5 % | TSFC, eta_b |
| EGT (T5) | 4 x K thermocouples, circumferentially averaged | jet pipe x = 212 mm | 0-1300 K | 1029 K at max | +/-161 K (pattern factor) | turbine efficiency, T04 back-calculation |
| P3 (compressor exit total) | pitot rake at the deswirl exit | x = 56 mm | 0-6 bar abs | 3.97 bar at max | +/-1 % | compressor map, running line |
| T3 | K thermocouple | deswirl exit | 300-600 K | 461 K | +/-3 K | compressor efficiency |
| P2 / T2 (inlet) | static taps + thermocouple in the bellmouth | inlet throat | 0.8-1.1 bar | ambient minus bellmouth depression | +/-0.2 % | airflow (bellmouth calibration) |
| airflow | calibrated bellmouth (dP) | inlet | 0-1.13 kg/s | 0.867 kg/s at design | +/-2 % | compressor map flow scale |
| vibration | 2 x accelerometers (radial, 90 deg apart) | front bearing housing | 0-50 g | < 10 g rms | - | rotordynamics (criticals, unbalance response) |
| bearing temperature | thermocouple on the outer ring | front and rear bearing housings | 300-500 K | < 420 K | +/-5 K | bearing thermal model, lubrication |
| oil / lubrication flow | flow switch | oil-mist line | - | per bearing spec | - | lubrication assumptions |

## Test procedure (virtual bench run)

* t = 0 s: start (target N 0.50)
* t = 20 s: idle (target N 0.50)
* t = 30 s: step 0.42 (target N 0.42)
* t = 38 s: step 0.60 (target N 0.60)
* t = 46 s: step 0.80 (target N 0.80)
* t = 54 s: step 0.90 (target N 0.90)
* t = 62 s: step 1.00 (target N 1.00)
* t = 70 s: step 0.90 (target N 0.90)
* t = 78 s: step 0.70 (target N 0.70)
* t = 86 s: step 0.42 (target N 0.42)
* t = 94 s: endurance max (target N 1.00)
* t = 102 s: endurance idle (target N 0.50)
* t = 110 s: endurance max (target N 1.00)
* t = 118 s: endurance idle (target N 0.50)
* t = 126 s: shutdown (target N 0.00)

Predicted data products: designs\p500\analysis\testbench_log.csv, designs\p500\analysis\testbench_run.png

## Confidence

* Cycle and sizing: L1 correlations, validated against the boomsonic_v0 tool chain (3-5 %) and fleet datasheets.
* Maps and matching: L2 mean-line loss models, validated vs independent code (PR within 5 %, efficiency 1-5 pts); surge line +/-30 %.
* Stresses and life: closed-form with conceptual factors; factor-of-3 life scatter; FE hand-off available (`jet export fea`).
* Numbers with an L3 tag come from ingested solver/test results (see `jet status`).