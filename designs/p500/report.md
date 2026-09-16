# p500 - design report (v15)

Overall rule verdict: **fail**. Fidelity tier of every claim is listed per stage at the end; L1 = correlation / mean-line sizing, L2 = mean-line loss models and FE beam rotordynamics, L3 = ingested solver or test results.

## Requirements and cycle

| item | value |
|---|---|
| thrust | 500 N at 0 m, M 0 |
| OPR / T04 | 4 / 1150 K |
| airflow / fuel flow | 0.8674 kg/s / 0.01655 kg/s |
| TSFC | 0.1192 kg/(N h) |
| Tt3 / Tt5 | 461.1 / 1003 K |
| turbine PR / NPR | 1.928 / 1.893 (choked) |
| efficiencies assumed (c / t) | 0.8046 / 0.8733 |
| efficiencies estimated L1 (c / t) | 0.8069 / 0.8751 |

## Spool speed

7.25e+04 rpm (auto (binding: turbine_disc)); limits: inducer 81563, turbine AN2 85202, turbine disc 74937, bearing DN 80952 rpm

## Compressor

| item | value |
|---|---|
| material | Ti-6Al-4V |
| inducer r1h / r1s | 14.71 / 42.02 mm, M1rel 1.095 |
| impeller D2 / b2 / L | 131.4 / 7.694 / 42.05 mm |
| U2 / backsweep / blades | 498.8 m/s / 30 deg / 8+8 |
| slip / work coefficient | 0.8438 / 0.6821 |
| exducer root / tip thickness | 1.772 / 0.657 mm |
| diffuser | vaned, r3/r2 1.08, r4 90.66 mm, 11 vanes, throat M 0.7 |
| choke margin | 0.486 |

## Turbine

| item | value |
|---|---|
| material (rotor / NGV) | IN713LC / IN713LC |
| psi / phi / reaction | 1.46 / 0.65 / 0.4 |
| mean radius / heights | 45.61 mm; NGV 16.54 mm, rotor 21.4 mm |
| tip diameter / hub-tip | 112.6 mm / 0.62 |
| counts NGV / rotor | 16 / 25 |
| root stress at MCS / allowable | 297.8 / 436 MPa |

## Combustor

Annular, Ro 89.66 mm, Ri 41.21 mm, liner 92.25 mm long, U_ref 14.36 m/s, residence 2.5 ms, 14 vaporisers, igniter glow-1/4-32.

## Rotor

Bearings 71902C-HC (DN 1.14e+06 at MCS), journal 15 mm, tube 36 x 25.92 mm, span 108.1 mm. Forward criticals: 23844, 29174 rpm (rigid-body: 23844, 29174); first bending above scan ceiling 190312 rpm.

Rotordynamics campaign (L2): max synchronous amplitude at G2.5 1.32 um, AF 3.31; exducer f1 1.931e+04 Hz, turbine blade f1 6519 Hz; resonance crossings in range: 0.


## Life (L1, factor-of-3 scatter applied in the verdicts)

Creep: blade 3.35e+06 h, disc rim 5.18e+07 h over the mission. LCF: impeller bore 8.29e+06 cycles, turbine bore 460 cycles (start thermal dT 293 K). Bearing L10 295 h (oil-mist). Containment: fragment 1.15e+04 J vs casing 1 mm (needs 7.3 mm).

## Manufacturability (L1)

Tip clearance stack-up: impeller worst case 0.17 mm (RSS 0.074) against 0.26 mm nominal; turbine 0.24 / 0.25 mm. Balance G2.5: 0.306 g mm per plane. Impeller (billet-5axis): min passage 12.3 mm, wrap 70.7 deg; flags: none. BOM 20 lines, ~6337 EUR, lead 10 weeks.

## Envelope and mass

OD 183.3 mm x length 350.3 mm; estimated dry mass 6.44 kg.

| part | material | mass kg |
|---|---|---|
| impeller | Ti-6Al-4V | 0.854 |
| inlet_shroud | Al6061-T6 | 0.186 |
| diffuser | Al2618-T61 | 0.286 |
| outer_casing | AISI321 | 0.770 |
| combustor_liners | IN625 | 0.652 |
| inner_casing | AISI321 | 0.223 |
| ngv_ring | IN713LC | 0.378 |
| turbine_wheel | IN713LC | 0.707 |
| turbine_shroud | AISI321 | 0.111 |
| shaft | AISI4340 | 0.498 |
| bearings | steel/ceramic | 0.028 |
| housings_tunnel | AISI321 | 0.884 |
| nozzle_tailcone | AISI321 | 0.453 |

## Open risks and unresolved items

* [L2] **MAP-6** compressor loss-model PR at design vs cycle OPR |diff|/OPR: 0.07941 vs 0.06  -> warn. loss model PR 4.318 vs cycle OPR 4.000
* [L2] **OD-1** minimum surge margin along the running line: -0.1653 vs 0.1  -> fail. lower the running line (larger nozzle), more backsweep, or a bleed / variable geometry
* [L2] **OD-4** idle surge margin: -0.1653 vs 0.08  -> warn. 
* [L2] **ENV-2** worst-case surge margin over the envelope: 0.07715 vs 0.08  -> fail. hot-day / high-Mach corners load the compressor: consider a variable nozzle or bleed
* [L2] **TRN-3** slam acceleration idle -> 95 % time: 8.35 vs 6 s -> warn. raise the accel limiter (watch SM)
* [L2] **TRN-4** minimum surge margin during the slam acceleration: -0.08191 vs 0.05  -> fail. lower accel_limit or add bleed
* [L2] **TRN-8** hung start with half starter torque avoided: 0 vs 1  -> warn. starter torque margin is thin
* [L2] **TRN-9** overspeed on governor failure (peak N / design): 1.116 vs 1.15  -> warn. 
* [L1] **LIFE-4** turbine bore LCF cycles incl. start thermal stress / scatter: 153.4 vs 500  -> fail. slower start, thicker hub, or boreless wheel
* [L1] **LIFE-7** casing wall vs containment thickness (1/3 disc fragment at burst): 1 vs 7.261 mm -> warn. a containment ring around the turbine plane is the usual answer
* [L1] **MFG-2** turbine tip clearance remaining at worst-case stack-up: 0.01 vs 0.05 mm -> fail. 
* [L1] **MFG-6** impeller blade wrap / pitch (axial-view overlap): 1.572 vs 1.6  -> warn. 
* Surge line: predicted by stall indicators with +/-30 % uncertainty on the margin; no validated vaned-diffuser stall method exists at this fidelity.
* Efficiency correlations, stress concentration factors and life constants are conceptual-level; the UQ study quantifies their effect.

## Fidelity tiers

| stage | kind | tier | last run | overrides (ingested) |
|---|---|---|---|---|
| requirements | core | L0 | 2026-09-16T16:23:23 | - |
| cycle | core | L1 | 2026-09-16T16:23:23 | - |
| speed | core | L1 | 2026-09-16T16:23:23 | - |
| compressor | core | L1 | 2026-09-16T16:23:23 | - |
| turbine | core | L1 | 2026-09-16T16:23:23 | - |
| combustor | core | L1 | 2026-09-16T16:23:23 | - |
| layout | core | L0 | 2026-09-16T16:23:23 | - |
| rotor | core | L2 | 2026-09-16T16:23:24 | - |
| mechanical | core | L1 | 2026-09-16T16:23:24 | - |
| geometry | core | L0 | 2026-09-16T16:23:24 | - |
| maps | analysis | L2 | 2026-09-16T16:47:01 | - |
| offdesign | analysis | L2 | 2026-09-16T16:47:03 | - |
| assess | analysis | L2 | 2026-09-16T16:47:11 | - |
| transient | analysis | L2 | 2026-09-16T17:00:14 | - |
| combustor1d | analysis | L2 | 2026-09-16T17:00:36 | - |
| envelope | analysis | L2 | 2026-09-16T16:50:36 | - |
| life | analysis | L1 | 2026-09-16T17:00:14 | - |
| rotordyn | analysis | L2 | 2026-09-16T16:57:19 | - |
| manufacturing | analysis | L1 | 2026-09-16T17:00:16 | - |
| testbench | analysis | L2 | 2026-09-16T16:58:14 (stale) | - |

## Design rules

```
[requirements]
  ok   REQ-1      thrust target inside supported range              500.0 <= 1000.0     N        +50.0 %  [brief: 100-1000 N]
  ok   REQ-2      thrust target above minimum                       500.0 >= 100.0      N       +400.0 %  [brief: 100-1000 N]
  ok   REQ-3      design Mach subsonic (pitot intake model)             0 <= 1.000              +100.0 %  [intake model: normal shock + duct]
[cycle]
  ok   CYC-1      OPR within single-stage centrifugal practice      4.000 <= 5.000               +20.0 %  [Dixon & Hall ch.7; micro-turbojet fleet 2.5-4.5]
  ok   CYC-2      OPR above useful minimum                          4.000 >= 2.200               +81.8 %  [cycle: specific thrust collapses below ~2.2]
  ok   CYC-3      T04 within uncooled cast-wheel practice          1150.0 <= 1250.0               +8.0 %  [IN-713LC/MAR-M247 uncooled rotor practice (JetCat/AMT class 1050-1200 K)]
  ok   CYC-4      T04 above combustor stability floor              1150.0 >= 950.0               +21.1 %  [lean stability at idle/design]
  info CYC-5      compressor exit temperature vs aluminium impeller limit (info)      461.1    -          K                 [materials.T_max]
  info CYC-6      nozzle pressure ratio                             1.893    -          -                 [-]
  ok   CYC-7      fuel-air ratio below 60 % stoichiometric          0.019 <= 0.041               +53.0 %  [combustor: overall phi < 0.6]
[speed]
  ok   SPD-1      inducer shroud relative Mach at design            1.095 <= 1.300               +15.8 %  [fielded micro-turbojet band 1.10-1.33 (boomsonic_v0 A3R.1)]
  ok   SPD-2      design rpm vs turbine AN2 limit                 72500.0 <= 85201.8    rpm      +14.9 %  [AN2 with IN713LC allowable 436 MPa at 1030 K, margin 1.25]
  ok   SPD-2b     design rpm vs turbine disc bore-stress limit    72500.0 <= 74937.1    rpm       +3.3 %  [bored IN713LC wheel, allowable 631 MPa at 750 K, k_peak 1.3]
  ok   SPD-3      design rpm vs bearing DN limit                  72500.0 <= 80952.4    rpm      +10.4 %  [bearing 71902C-HC DN 1.5e+06 x 0.85]
  info SPD-4      impeller tip speed allowed by material (info: set by work, see COMP-3)      454.1    -          m/s               [Ti-6Al-4V yield at Tt3]
[compressor]
  ok   COMP-1     inducer shroud relative Mach                      1.095 <= 1.300               +15.8 %  [fielded micro-turbojet band (boomsonic A3R.1)]
  ok   COMP-2     impeller tip speed U2                             498.8 <= 620.0      m/s      +19.5 %  [Ti impellers ~550-600 m/s, Al ~450-500 (Dixon; Rodgers)]
  ok   COMP-3     exducer root stress at MCS vs allowable (root sized to the limit)      602.6 <= 602.6      MPa       +0.0 %  [Ti-6Al-4V yield at 461 K / SF 1.0]
  ok   COMP-4     impeller material temperature (Tt3)               461.1 <= 673.0      K        +31.5 %  [Ti-6Al-4V T_max]
  ok   COMP-5     exit width ratio b2/D2                            0.059 >= 0.030               +95.2 %  [narrow exits lose efficiency (Rodgers): b2/D2 >= 0.03]
  ok   COMP-6     relative diffusion ratio W1s/W2                   1.717 <= 2.000               +14.1 %  [Dixon & Hall / Rodgers: W1s/W2 <= ~1.8-2.0 for attached flow]
  ok   COMP-7     inducer throat choke margin at design             0.486 >= 0.100              +386.0 %  [Rodgers: design at <= 90 % of throat choke flow (boomsonic A3R.5)]
  ok   COMP-7b    inducer throat not choked at design               0.486 >= 0                   +48.6 %  [throat mass-flow function]
  ok   COMP-8     radius ratio r2/r1s                               1.563 >= 1.300               +20.3 %  [Aungier: 1.4-2.2 for a radial impeller]
  ok   COMP-9     radius ratio r2/r1s upper                         1.563 <= 2.300               +32.0 %  [Aungier: 1.4-2.2 for a radial impeller]
  ok   COMP-10    impeller exit absolute Mach                       0.925 <= 1.100               +15.9 %  [vaned diffuser LE tolerates ~M 1.1 (Japikse)]
  ok   COMP-11    diffuser inlet flow angle from radial            70.022 <= 78.000              +10.2 %  [vaneless stability: alpha < ~78 deg (Senoo)]
  ok   COMP-12    estimated vs assumed stage efficiency |diff|      0.002 <= 0.030               +92.2 %  [consistency: run `jet converge`]
  ok   COMP-13    backsweep angle                                  30.000 <= 45.000              +33.3 %  [manufacturing/loading practice 15-45 deg]
  ok   COMP-14    backsweep angle minimum for stability            30.000 >= 15.000             +100.0 %  [range/stability practice]
  ok   COMP-15    implied diffuser total-pressure loss              0.081 <= 0.120               +32.5 %  [impeller/diffuser split: 3-10 % typical]
[turbine]
  ok   TURB-1     stage loading psi                                 1.460 <= 2.400               +39.2 %  [Smith chart: efficiency falls fast above ~2.2]
  ok   TURB-2     stage loading psi minimum                         1.460 >= 1.200               +21.7 %  [below ~1.2 the annulus becomes very short]
  ok   TURB-3     rotor-exit hub/tip ratio                          0.620 >= 0.550               +12.7 %  [practice 0.6-0.85 for a single stage]
  ok   TURB-4     rotor-exit hub/tip ratio upper                    0.620 <= 0.880               +29.5 %  [very short blades: clearance losses]
  ok   TURB-5     blade root stress at MCS x margin vs allowable      372.2 <= 436.0      MPa      +14.6 %  [IN713LC min(yield, creep) at 1030 K; margin 1.25]
  ok   TURB-6     rotor metal temperature vs material limit        1030.0 <= 1223.0     K        +15.8 %  [IN713LC T_max]
  ok   TURB-7     NGV metal temperature vs material limit          1150.0 <= 1223.0     K         +6.0 %  [IN713LC T_max]
  ok   TURB-8     NGV exit Mach                                     0.816 <= 1.050               +22.2 %  [subsonic/transonic NGV practice]
  ok   TURB-9     rotor exit absolute Mach                          0.376 <= 0.600               +37.3 %  [jet-pipe entry Mach; boomsonic R7.1 annulus cap]
  ok   TURB-10    estimated vs assumed turbine efficiency |diff|      0.002 <= 0.030               +94.0 %  [consistency: run `jet converge`]
  ok   TURB-11    AN2 (rotor annulus x rpm^2) at MCS            3.554e+07 <= 4.500e+07  m2rpm2   +21.0 %  [uncooled cast wheels: JetCat/AMT class 2-3.5e7, ceiling ~4.5e7 m2 rpm2]
  info TURB-12    turbine tip diameter (info)                       112.6    -          mm                [-]
[combustor]
  ok   COMB-1     reference velocity                               14.363 <= 25.000     m/s      +42.5 %  [Lefebvre: annular 15-25 m/s; micro practice ~20]
  ok   COMB-2     reference velocity minimum                       14.363 >= 12.000     m/s      +19.7 %  [low U_ref wastes volume]
  ok   COMB-3     liner residence time                              2.500 >= 2.500      ms        +0.0 %  [vaporiser combustors 4-7 ms (JetCat/AMT class)]
  ok   COMB-4     liner length / height                             2.800 <= 3.600               +22.2 %  [practice 2.5-3.5 (Lefebvre)]
  ok   COMB-5     liner metal temperature margin (T04 vs liner T_max; film-cooled liners run cooler)     1150.0 <= 1403.0     K        +18.0 %  [IN625 T_max + 150 K film credit]
  ok   COMB-6     heat release rate                                 143.8 <= 300.0      MW/m3bar   +52.1 %  [large annular 20-60, micro-turbojet vaporiser combustors up to ~300 MW/(m3 bar)]
  ok   COMB-7     air split sums to 1                               1.000 <= 1.000                +0.0 %  [input check]
  ok   COMB-8     vaporiser fuel loading                            4.257 <= 12.000     kg/h     +64.5 %  [practice 3-12 kg/h per tube]
[layout]
  info LAY-1      engine outer diameter vs limit                    183.3 <= -          mm                [requirements.max_diameter_mm]
  info LAY-2      engine length vs limit                            350.3 <= -          mm                [requirements.max_length_mm]
  ok   LAY-3      bearing span / D2 (rotordynamic sanity)           0.822 <= 2.200               +62.6 %  [long spans lower the bending critical; boomsonic_v0 1.43]
  ok   LAY-4      tail cone shorter than nozzle                     0.107 <= 0.119                +9.9 %  [geometry]
[rotor]
  ok   ROT-1      bearing DN at MCS vs rating                   1.142e+06 <= 1.500e+06  mm.rpm   +23.9 %  [71902C-HC catalogue DN limit]
  ok   ROT-2      bearing temperature rating                        420.0 <= 523.0      K        +19.7 %  [71902C-HC T_max]
  ok   ROT-3      first bending critical / MCS                      2.500 >= 1.250              +100.0 %  [API 684 separation margin practice (25 %)]
  ok   ROT-4      rigid-body criticals below 60 % speed (soft mount)      0.402 <= 0.600               +32.9 %  [traverse rigid modes below idle-to-cruise band]
  ok   ROT-5      journal torsional stress                         30.459 <= 175.3      MPa      +82.6 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-6      tube torsional stress                             3.013 <= 175.3      MPa      +98.3 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-7      shaft tunnel fits inside combustor inner casing      0.022 <= 0.038      m        +43.7 %  [layout: tunnel OD + 3 mm gap]
  info ROT-8      bearing L10 life (info)                       6.251e+06    -          h                 [ISO 281 basic rating (no thermal factors)]
[mechanical]
  ok   MECH-1     impeller disc peak stress at MCS vs yield         405.4 <= 617.0      MPa      +34.3 %  [Ti-6Al-4V min-basis yield at 441 K; k_peak 1.6]
  ok   MECH-2     impeller burst speed ratio                        1.531 >= 1.200               +27.6 %  [14 CFR 33.27 style; Robinson k 0.85]
  ok   MECH-3     inducer root radial stress vs yield               130.9 <= 617.0      MPa      +78.8 %  [Ti-6Al-4V yield]
  ok   MECH-4     exducer root stress (from compressor stage, sized to limit) vs allowable      602.6 <= 602.6      MPa       +0.0 %  [compressor.COMP-3]
  ok   MECH-5     turbine disc peak stress vs bore allowable        518.1 <= 630.8      MPa      +17.9 %  [IN713LC allowable at bore 750 K]
  ok   MECH-6     turbine disc average stress vs rim creep allowable      398.5 <= 615.9      MPa      +35.3 %  [IN713LC allowable at rim 950 K]
  ok   MECH-7     turbine burst speed ratio                         1.267 >= 1.200                +5.6 %  [14 CFR 33.27 style; Robinson k 0.85]
  ok   MECH-8     turbine blade root (from turbine stage)           297.8 <= 436.0      MPa      +31.7 %  [turbine.TURB-5 (no margin factor here)]
  ok   MECH-9     impeller clamp load retained hot                58970.5 >= 14348.3    N       +311.0 %  [tie-shaft preload minus thermal relaxation and gas load >= 20 % of preload]
[geometry]
  info GEO-1      dry mass estimate vs limit                        6.442 <= -          kg                [requirements.max_mass_kg]
  info GEO-2      thrust/weight (info)                              7.912    -          -                 [-]
  info GEO-3      flange screws count (info)                       15.000    -                            [ISO 4762 M2]
[assess]
  ok   ASS-1      compressor quality score (mean of items)          0.843 >= 0.750               +12.4 %  [assessment items AQ-C*]
  ok   ASS-2      diffuser quality score                            1.000 >= 0.750               +33.3 %  [AQ-D*]
  ok   ASS-3      turbine quality score                             0.981 >= 0.750               +30.7 %  [AQ-T*]
[combustor1d]
  ok   C1D-1      primary-zone equivalence ratio                    1.201 <= 1.400               +14.2 %  [Lefebvre: primary zone phi 0.8-1.4 for vaporiser combustors]
  ok   C1D-1b     primary-zone equivalence ratio minimum            1.201 >= 0.800               +50.1 %  [Lefebvre: phi_pz >= 0.8 for stability]
  ok   C1D-2      primary-zone Damkohler number (residence/chemical)     25.445 >= 5.000              +408.9 %  [Da >> 1 required for stable combustion (global kinetics; order of magnitude)]
  ok   C1D-3      combustion efficiency (Lefebvre theta correlation)      0.985 >= 0.980                +0.5 %  [theta correlation calibrated on the fleet (+/-2 pts)]
  ok   C1D-4      lean blow-out margin at design (phi_pz / phi_LBO)      2.402 >= 1.500               +60.2 %  [Lefebvre stability loop]
  ok   C1D-5      lean blow-out margin at idle                      1.721 >= 1.200               +43.4 %  [Lefebvre stability loop at the idle point]
  ok   C1D-6      pattern factor into the turbine                   0.270 <= 0.300               +10.1 %  [Lefebvre: PF 0.2-0.35 for short annular liners]
  ok   C1D-7      liner wall temperature vs material limit          978.0 <= 1253.0     K        +21.9 %  [IN625 T_max; radiation/convection/film balance]
  ok   C1D-8      altitude relight index (phi_LBO windmilling / phi_LBO design)      1.103 <= 2.500               +55.9 %  [Lefebvre loading at 6000 m, N 0.12]
[maps]
  ok   MAP-1      design-point surge margin (loss-model map, SAE definition)      0.211 >= 0.150               +40.8 %  [stall indicators in perf.closs; uncertainty +/-30 % of the margin]
  ok   MAP-2      design-point choke margin (flow to choke / design flow - 1)      0.124 >= 0.080               +55.5 %  [inducer / diffuser throat choke on the design speed line]
  ok   MAP-3      L2 loss-model compressor efficiency vs L1 estimate |diff|      0.031 <= 0.040               +22.4 %  [consistency between fidelity tiers]
  ok   MAP-4      L2 loss-model turbine efficiency vs L1 estimate |diff|      0.038 <= 0.050               +24.3 %  [consistency between fidelity tiers]
  ok   MAP-5      design-point vaned-diffuser incidence             2.000 <= 4.000               +50.0 %  [vane stall onset ~ +4-6 deg (Japikse)]
  WARN MAP-6      compressor loss-model PR at design vs cycle OPR |diff|/OPR      0.079 <= 0.060               -32.3 %  [the sized geometry should deliver the cycle pressure ratio within the loss-model accuracy]
       -> loss model PR 4.318 vs cycle OPR 4.000
[offdesign]
  FAIL OD-1       minimum surge margin along the running line      -0.165 >= 0.100              -265.3 %  [SAE margin from the L2 map at N 0.40; surge line uncertainty +/-30 %]
       -> lower the running line (larger nozzle), more backsweep, or a bleed / variable geometry
  ok   OD-2       max-thrust point recovers the design thrust       1.025 >= 0.950                +7.9 %  [map-based matching vs design-point cycle (consistency)]
  ok   OD-3       idle speed fraction                               0.400 >= 0.350               +14.3 %  [micro-turbojet idle 30-40 % (JetCat 33-35 %)]
  WARN OD-4       idle surge margin                                -0.165 >= 0.080              -306.6 %  [low-speed operability (boomsonic_v0 risk 4.2)]
[envelope]
  ok   ENV-1      fraction of envelope grid points cleared (converged, SM >= floor)      0.990 >= 0.900               +10.0 %  [SM floor 0.08; L2 maps]
  FAIL ENV-2      worst-case surge margin over the envelope         0.077 >= 0.080                -3.6 %  [at alt 9000.0 m, M 0.8, dT 0.0 K]
       -> hot-day / high-Mach corners load the compressor: consider a variable nozzle or bleed
  ok   ENV-3      sea-level static max thrust vs design thrust      1.025 >= 0.950                +7.9 %  [envelope max-power point at SLS (T04- or N-limited)]
[transient]
  ok   TRN-1      start reaches idle                                1.000 >= 1.000                +0.0 %  [start sequence simulation]
  ok   TRN-2      start light-off to self-sustain time              4.300 <= 8.000      s        +46.3 %  [micro-turbojet practice 3-8 s]
  WARN TRN-3      slam acceleration idle -> 95 % time               8.350 <= 6.000      s        -39.2 %  [class practice 3-6 s (JetCat ~4 s)]
       -> raise the accel limiter (watch SM)
  FAIL TRN-4      minimum surge margin during the slam acceleration     -0.082 >= 0.050              -263.8 %  [transient excursion toward surge; surge line uncertainty +/-30 %]
       -> lower accel_limit or add bleed
  ok   TRN-5      T04 peak during acceleration vs limit            1200.0 <= 1200.0     K         +0.0 %  [over-temperature limiter (the limiter holds the peak at the limit)]
  ok   TRN-6      deceleration 100 % -> idle time                   2.600 <= 8.000      s        +67.5 %  [class practice]
  ok   TRN-7      hot start T04 peak (schedule x1.5)               1088.0 <= 1300.0     K        +16.3 %  [abnormal case: rich start]
  WARN TRN-8      hung start with half starter torque avoided           0 >= 1.000              -100.0 %  [abnormal case]
       -> starter torque margin is thin
  WARN TRN-9      overspeed on governor failure (peak N / design)      1.116 <= 1.150                +3.0 %  [burst margin 1.2 x MCS must cover the overspeed reached before the fuel cut]
[life]
  ok   LIFE-1     turbine blade creep life over the mission / scatter  1.117e+06 >= 50.000     h      +2233160.2 %  [Larson-Miller from the IN713LC creep table (C 20.0), Robinson damage]
  ok   LIFE-2     turbine disc rim creep life / scatter         1.727e+07 >= 50.000     h      +34543506.0 %  [as LIFE-1]
  ok   LIFE-3     impeller bore LCF cycles / scatter            2.764e+06 >= 500.0             +552658.9 %  [Manson universal slopes, Ti-6Al-4V]
  FAIL LIFE-4     turbine bore LCF cycles incl. start thermal stress / scatter      153.4 >= 500.0               -69.3 %  [Manson universal slopes, IN713LC; thermal dT_max 293 K]
       -> slower start, thicker hub, or boreless wheel
  ok   LIFE-5     bearing L10 life (ISO 281, lubrication/temperature factors)      294.6 >= 200.0      h        +47.3 %  [71902C-HC C 4.0 kN, P_eq 358 N, oil-mist]
  ok   LIFE-6     bearing DN with the lubrication method            1.000 >= 1.000                +0.0 %  [catalogue DN x lubrication factor]
  WARN LIFE-7     casing wall vs containment thickness (1/3 disc fragment at burst)      1.000 >= 7.261      mm       -86.2 %  [energy balance, AISI321 UTS at 700 K, k 3 (conceptual)]
       -> a containment ring around the turbine plane is the usual answer
[rotordyn]
  ok   RD-1       first forward bending critical / MCS (nominal support)      2.500 >= 1.250              +100.0 %  [API 684 separation margin]
  ok   RD-2       max synchronous vibration amplitude at G2.5 residual unbalance      1.321 <= 25.000     um       +94.7 %  [ISO 1940 G2.5; 25 um pk at the wheels is a common limit for tip clearance/seal rub]
  ok   RD-3       amplification factor at the first response peak      3.313 <= 8.000               +58.6 %  [API 684: AF < 8 for a well-damped critical]
  ok   RD-4       blade resonance crossings within the operating range          0 <= 0                    +0.0 %  [Campbell: exducer vs diffuser vane passing, turbine blade vs NGV passing]
  ok   RD-5       blade resonance within +/-10 % of the design speed          0 <= 0                    +0.0 %  [no crossing at the dwell speed]
  ok   RD-6       max bearing dynamic load at G2.5 / static capacity C0      0.005 <= 0.100               +94.7 %  [dynamic load should stay a small fraction of C0]
[manufacturing]
  ok   MFG-1      impeller tip clearance remaining at worst-case stack-up      0.093 >= 0.050      mm       +85.6 %  [tolerance chain (worst case)]
  FAIL MFG-2      turbine tip clearance remaining at worst-case stack-up      0.010 >= 0.050      mm       -80.0 %  [tolerance chain incl. thermal growth]
  ok   MFG-3      impeller efficiency scatter from clearance tolerance (RSS)      0.003 <= 0.010               +71.1 %  [0.3 x d(clr)/b2]
  ok   MFG-4      balancing: required residual per plane vs achievable      0.306 >= 0.050      g mm    +512.9 %  [ISO 21940 G2.5 at 72500 rpm: 0.306 g mm per plane]
  ok   MFG-5      minimum impeller passage width vs cutter         12.261 >= 3.000      mm      +308.7 %  [5-axis cutter access]
  WARN MFG-6      impeller blade wrap / pitch (axial-view overlap)      1.572 <= 1.600                +1.8 %  [flank-milling reach]
  ok   MFG-7      impeller features flagged                             0 <= 0                    +0.0 %  [machinability screen]
  ok   MFG-8      turbine casting features flagged                      0 <= 0                    +0.0 %  [investment-casting screen]
  ok   MFG-9      exducer root stress vs process-adjusted allowable      602.6 <= 602.6      MPa       +0.0 %  [billet-5axis: allowable x 1.0 (root sized to the limit)]
  ok   MFG-10     turbine root stress vs process-adjusted allowable      297.8 <= 370.6      MPa      +19.7 %  [investment-cast: allowable x 0.85]
[testbench]
  ok   TB-1       virtual run completed without abort                   0 <= 0                    +0.0 %  [abort criteria]
  ok   TB-2       max thrust reached on the bench vs design         1.066 >= 0.950               +12.2 %  [throttle step to 100 %]
```