# Compare: before L3 (v0048)  vs  after L3 (v0053)

Frozen versions: A -, B -.

## Headline

| quantity | before L3 (v0048) | after L3 (v0053) | delta |
|---|---|---|---|
| thrust N | 500 | 500 | +0 |
| airflow kg/s | 0.867 | 0.867 | +0.000 |
| OPR | 4.00 | 4.00 | +0.00 |
| T04 K | 1150 | 1150 | +0 |
| TSFC kg/N/h | 0.1192 | 0.1192 | +0.0000 |
| rpm | 72500 | 72500 | +0 |
| D2 mm | 131.4 | 131.4 | +0.0 |
| turbine tip mm | 112.6 | 112.6 | +0.0 |
| OD mm | 183.3 | 183.3 | +0.0 |
| length mm | 379 | 379 | +0 |
| mass kg | 6.66 | 6.66 | +0.00 |
| idle SM | 0.300 | 0.300 | +0.000 |
| SM min (running line) | 0.069 | 0.069 | +0.000 |
| max thrust N | 494 | 494 | +0 |
| slam accel t95 s | 7.10 | 7.10 | +0.00 |
| slam accel SM min | 0.171 | 0.171 | +0.000 |
| start T04 peak K | 1200 | 1200 | +0 |
| hot start T04 peak K | 1200 | 1200 | +0 |
| turbine bore LCF cycles (with thermal) | 460 | 43 | -418 |
| envelope worst SM | -0.046 | -0.046 | +0.000 |

## Inputs that differ

(none)

### Overrides (ingested L3) that differ

| path | A | B |
|---|---|---|
| overrides.life.sigma_bore_total_Pa.at | None | 2026-09-17T00:34:00 |
| overrides.life.sigma_bore_total_Pa.source | None | CalculiX 2.21 axisymmetric CAX4 disc, 2379 elements, 2026-09-16T21:34:00+00:00; peak taken >= 1 mm from the unfilleted re-entrant corners (singular there) |
| overrides.life.sigma_bore_total_Pa.tier | None | L3 |
| overrides.life.sigma_bore_total_Pa.value | None | 1281428675.674246 |
| overrides.mechanical.impeller.sigma_peak_Pa.at | None | 2026-09-17T00:33:55 |
| overrides.mechanical.impeller.sigma_peak_Pa.source | None | CalculiX 2.21 axisymmetric CAX4 impeller hub, 7921 elements, blades as smeared traction, 2026-09-16T21:33:55+00:00; peak >= 1 mm from re-entrant corners |
| overrides.mechanical.impeller.sigma_peak_Pa.tier | None | L3 |
| overrides.mechanical.impeller.sigma_peak_Pa.value | None | 738527191.8898699 |
| overrides.mechanical.turbine.sigma_avg_Pa.at | None | 2026-09-17T00:34:00 |
| overrides.mechanical.turbine.sigma_avg_Pa.source | None | CalculiX 2.21 axisymmetric CAX4 disc, 2379 elements, 2026-09-16T21:34:00+00:00 |
| overrides.mechanical.turbine.sigma_avg_Pa.tier | None | L3 |
| overrides.mechanical.turbine.sigma_avg_Pa.value | None | 398434122.13309824 |
| overrides.mechanical.turbine.sigma_peak_Pa.at | None | 2026-09-17T00:34:00 |
| overrides.mechanical.turbine.sigma_peak_Pa.source | None | CalculiX 2.21 axisymmetric CAX4 disc, 2379 elements, 2026-09-16T21:34:00+00:00 |
| overrides.mechanical.turbine.sigma_peak_Pa.tier | None | L3 |
| overrides.mechanical.turbine.sigma_peak_Pa.value | None | 967096370.3611842 |

## Surge margins with their band (SAE SM, absolute)

| rule | A | band A (dominant) | A with band | B | band B (dominant) | B with band | limit |
|---|---|---|---|---|---|---|---|
| MAP-1 | 0.173 | +/-0.077 (rig) | +0.096 FAIL | 0.173 | +/-0.077 (rig) | +0.096 FAIL | 0.150 |
| OD-1 | 0.069 | +/-0.077 (rig) | -0.008 FAIL | 0.069 | +/-0.077 (rig) | -0.008 FAIL | 0.100 |
| OD-4 | 0.300 | +/-0.159 (igv extrapolation) | +0.141 pass | 0.300 | +/-0.159 (igv extrapolation) | +0.141 pass | 0.080 |
| ENV-2 | -0.046 | +/-0.077 (rig) | -0.123 FAIL | -0.046 | +/-0.077 (rig) | -0.123 FAIL | 0.080 |
| TRN-4 | 0.171 | +/-0.082 (rig) | +0.089 pass | 0.171 | +/-0.082 (rig) | +0.089 pass | 0.050 |

## Running line

| N/N_d | SM A | SM B | thrust A | thrust B | PR A | PR B | B schedule |
|---|---|---|---|---|---|---|---|
| 0.40 | 0.300 | 0.300 | 22 | 22 | 1.22 | 1.22 | bleed 0.15, igv 25.00 |
| 0.45 | 0.366 | 0.366 | 29 | 29 | 1.29 | 1.29 | bleed 0.15, igv 25.00 |
| 0.50 | 0.412 | 0.412 | 37 | 37 | 1.36 | 1.36 | bleed 0.12, igv 25.00 |
| 0.55 | 0.415 | 0.415 | 51 | 51 | 1.48 | 1.48 | bleed 0.09, igv 20.83 |
| 0.60 | 0.433 | 0.433 | 65 | 65 | 1.59 | 1.59 | bleed 0.07, igv 16.67 |
| 0.65 | 0.453 | 0.453 | 88 | 88 | 1.76 | 1.76 | bleed 0.04, igv 12.50 |
| 0.70 | 0.390 | 0.390 | 113 | 113 | 1.95 | 1.95 | bleed 0.01, igv 8.33 |
| 0.75 | 0.321 | 0.321 | 151 | 151 | 2.20 | 2.20 | bleed 0.00, igv 4.17 |
| 0.80 | 0.237 | 0.237 | 197 | 197 | 2.48 | 2.48 | igv 0.00 |
| 0.85 | 0.254 | 0.254 | 262 | 262 | 2.84 | 2.84 |  |
| 0.90 | 0.271 | 0.271 | 323 | 323 | 3.19 | 3.19 |  |
| 0.95 | 0.242 | 0.242 | 415 | 415 | 3.69 | 3.69 |  |
| 1.00 | 0.194 | 0.194 | 524 | 524 | 4.23 | 4.23 |  |
| 1.05 | 0.069 | 0.069 | 664 | 664 | 4.93 | 4.93 |  |

## Rules that changed

| rule | stage | A value (verdict) | B value (verdict) | margin A -> B | tier |
|---|---|---|---|---|---|
| LIFE-2 turbine disc rim creep life / scatter | life | 17271802.984 (pass) | 17308655.517 (pass) | +34543506.0% -> +34617211.0% | L1 |
| LIFE-3 impeller bore LCF cycles / scatter | life | 2763794.748 (pass) | 343.313 (fail) | +552658.9% -> -31.3% | L1 |
| LIFE-4 turbine bore LCF cycles incl. start thermal stress / scatter | life | 153.498 (fail) | 14.224 (fail) | -69.3% -> -97.2% | L1 |
| MECH-1 impeller disc peak stress at MCS vs yield | mechanical | 405.429 (pass) | 738.527 (fail) | +34.3% -> -19.7% | L1 |
| MECH-5 turbine disc peak stress vs bore allowable | mechanical | 518.100 (pass) | 967.096 (fail) | +17.9% -> -53.3% | L1 |
| MECH-6 turbine disc average stress vs rim creep allowable | mechanical | 398.539 (pass) | 398.434 (pass) | +35.3% -> +35.3% | L1 |
| MECH-7 turbine burst speed ratio | mechanical | 1.267 (pass) | 1.267 (pass) | +5.6% -> +5.6% | L1 |

Verdict counts: A {'pass': 118, 'warn': 12, 'info': 10, 'fail': 4}; B {'pass': 115, 'warn': 12, 'info': 10, 'fail': 7}.
