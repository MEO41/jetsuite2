# boomsonic-converged - design report (v3)

Overall rule verdict: **warn**

## Requirements and cycle

| item | value |
|---|---|
| thrust | 500 N at 5000 m, M 1.02 |
| OPR / T04 | 4 / 1150 K |
| airflow / fuel flow | 1.147 kg/s / 0.02138 kg/s |
| TSFC | 0.1539 kg/(N h) |
| Tt3 / Tt5 | 494 / 992 K |
| turbine PR / NPR | 2.032 / 3.444 (choked) |
| efficiencies assumed (c / t) | 0.8032 / 0.8736 |
| efficiencies estimated (c / t) | 0.8068 / 0.8758 |

## Spool speed

6.2e+04 rpm (auto (binding: turbine_disc)); limits: inducer 72976, turbine AN2 73210, turbine disc 64390, bearing DN 80952 rpm

## Compressor

| item | value |
|---|---|
| material | Ti-6Al-4V |
| inducer r1h / r1s | 17.16 / 49.02 mm, M1rel 1.057 |
| impeller D2 / b2 / L | 159.2 / 8.473 / 50.95 mm |
| U2 / backsweep / blades | 516.8 m/s / 30 deg / 8+8 |
| slip / work coefficient | 0.8438 / 0.6821 |
| exducer root / tip thickness | 2.031 / 0.796 mm |
| diffuser | vaned, r3/r2 1.08, r4 109.9 mm, 11 vanes, M4 0.4135 |
| choke margin | 0.08828 |

## Turbine

| item | value |
|---|---|
| material (rotor / NGV) | IN713LC / IN713LC |
| psi / phi / reaction | 1.58 / 0.65 / 0.4 |
| mean radius / heights | 53.14 mm; NGV 18.83 mm, rotor 24.93 mm |
| tip diameter / hub-tip | 131.2 mm / 0.62 |
| counts NGV / rotor | 16 / 25 |
| root stress at MCS / allowable | 295.5 / 436 MPa |

## Combustor

Annular, Ro 108.9 mm, Ri 59.83 mm, liner 93.34 mm long, U_ref 15.26 m/s, residence 2.5 ms, 16 vaporisers, igniter glow-1/4-32.

## Rotor

Bearings 71903C-HC (DN 1.11e+06 at MCS), journal 17 mm, tube 40.8 x 29.38 mm, span 112.4 mm. Forward criticals: 17799, 23056 rpm (rigid-body: 17799, 23056); first bending above scan ceiling 162750 rpm.

## Envelope and mass

OD 221.7 mm x length 398 mm; estimated dry mass 9.35 kg.

| part | material | mass kg |
|---|---|---|
| impeller | Ti-6Al-4V | 1.501 |
| inlet_shroud | Al6061-T6 | 0.271 |
| diffuser | Al2618-T61 | 0.409 |
| outer_casing | AISI321 | 0.970 |
| combustor_liners | IN625 | 0.864 |
| inner_casing | AISI321 | 0.346 |
| ngv_ring | IN713LC | 0.520 |
| turbine_wheel | IN713LC | 1.153 |
| turbine_shroud | AISI321 | 0.145 |
| shaft | AISI4340 | 0.689 |
| bearings | steel/ceramic | 0.032 |
| housings_tunnel | AISI321 | 1.262 |
| nozzle_tailcone | AISI321 | 0.615 |

## Design rules

```
[requirements]
  ok   REQ-1      thrust target inside supported range              500.0 <= 1000.0     N        +50.0 %  [brief: 100-1000 N]
  ok   REQ-2      thrust target above minimum                       500.0 >= 100.0      N       +400.0 %  [brief: 100-1000 N]
  WARN REQ-3      design Mach subsonic (pitot intake model)         1.020 <= 1.000                -2.0 %  [intake model: normal shock + duct]
       -> supersonic design points use a normal-shock recovery; check intake separately
[cycle]
  ok   CYC-1      OPR within single-stage centrifugal practice      4.000 <= 5.000               +20.0 %  [Dixon & Hall ch.7; micro-turbojet fleet 2.5-4.5]
  ok   CYC-2      OPR above useful minimum                          4.000 >= 2.200               +81.8 %  [cycle: specific thrust collapses below ~2.2]
  ok   CYC-3      T04 within uncooled cast-wheel practice          1150.0 <= 1250.0               +8.0 %  [IN-713LC/MAR-M247 uncooled rotor practice (JetCat/AMT class 1050-1200 K)]
  ok   CYC-4      T04 above combustor stability floor              1150.0 >= 950.0               +21.1 %  [lean stability at idle/design]
  info CYC-5      compressor exit temperature vs aluminium impeller limit (info)      494.0    -          K                 [materials.T_max]
  info CYC-6      nozzle pressure ratio                             3.444    -          -                 [-]
  ok   CYC-7      fuel-air ratio below 60 % stoichiometric          0.019 <= 0.041               +54.0 %  [combustor: overall phi < 0.6]
[speed]
  ok   SPD-1      inducer shroud relative Mach at design            1.057 <= 1.300               +18.7 %  [fielded micro-turbojet band 1.10-1.33 (boomsonic_v0 A3R.1)]
  ok   SPD-2      design rpm vs turbine AN2 limit                 62000.0 <= 73210.3    rpm      +15.3 %  [AN2 with IN713LC allowable 436 MPa at 1030 K, margin 1.25]
  ok   SPD-2b     design rpm vs turbine disc bore-stress limit    62000.0 <= 64390.3    rpm       +3.7 %  [bored IN713LC wheel, allowable 631 MPa at 750 K, k_peak 1.3]
  ok   SPD-3      design rpm vs bearing DN limit                  62000.0 <= 80952.4    rpm      +23.4 %  [bearing 71902C-HC DN 1.5e+06 x 0.85]
  info SPD-4      impeller tip speed allowed by material (info: set by work, see COMP-3)      445.1    -          m/s               [Ti-6Al-4V yield at Tt3]
[compressor]
  ok   COMP-1     inducer shroud relative Mach                      1.057 <= 1.300               +18.7 %  [fielded micro-turbojet band (boomsonic A3R.1)]
  ok   COMP-2     impeller tip speed U2                             516.8 <= 620.0      m/s      +16.6 %  [Ti impellers ~550-600 m/s, Al ~450-500 (Dixon; Rodgers)]
  ok   COMP-3     exducer root stress at MCS vs allowable (root sized to the limit)      578.9 <= 578.9      MPa       +0.0 %  [Ti-6Al-4V yield at 494 K / SF 1.0]
  ok   COMP-4     impeller material temperature (Tt3)               494.0 <= 673.0      K        +26.6 %  [Ti-6Al-4V T_max]
  ok   COMP-5     exit width ratio b2/D2                            0.053 >= 0.030               +77.4 %  [narrow exits lose efficiency (Rodgers): b2/D2 >= 0.03]
  ok   COMP-6     relative diffusion ratio W1s/W2                   1.659 <= 2.000               +17.0 %  [Dixon & Hall / Rodgers: W1s/W2 <= ~1.8-2.0 for attached flow]
  WARN COMP-7     inducer throat choke margin at design             0.088 >= 0.100               -11.7 %  [Rodgers: design at <= 90 % of throat choke flow (boomsonic A3R.5)]
       -> thinner LE, fewer main blades, larger hub/tip or lower inducer relative Mach
  ok   COMP-7b    inducer throat not choked at design               0.088 >= 0                    +8.8 %  [throat mass-flow function]
  ok   COMP-8     radius ratio r2/r1s                               1.624 >= 1.300               +24.9 %  [Aungier: 1.4-2.2 for a radial impeller]
  ok   COMP-9     radius ratio r2/r1s upper                         1.624 <= 2.300               +29.4 %  [Aungier: 1.4-2.2 for a radial impeller]
  ok   COMP-10    impeller exit absolute Mach                       0.926 <= 1.100               +15.8 %  [vaned diffuser LE tolerates ~M 1.1 (Japikse)]
  ok   COMP-11    diffuser inlet flow angle from radial            69.977 <= 78.000              +10.3 %  [vaneless stability: alpha < ~78 deg (Senoo)]
  ok   COMP-12    estimated vs assumed stage efficiency |diff|      0.004 <= 0.030               +88.1 %  [consistency: run `jet converge`]
  ok   COMP-13    backsweep angle                                  30.000 <= 45.000              +33.3 %  [manufacturing/loading practice 15-45 deg]
  ok   COMP-14    backsweep angle minimum for stability            30.000 >= 15.000             +100.0 %  [range/stability practice]
  ok   COMP-15    implied diffuser total-pressure loss              0.081 <= 0.120               +32.4 %  [impeller/diffuser split: 3-10 % typical]
[turbine]
  ok   TURB-1     stage loading psi                                 1.580 <= 2.400               +34.2 %  [Smith chart: efficiency falls fast above ~2.2]
  ok   TURB-2     stage loading psi minimum                         1.580 >= 1.200               +31.7 %  [below ~1.2 the annulus becomes very short]
  ok   TURB-3     rotor-exit hub/tip ratio                          0.620 >= 0.550               +12.7 %  [practice 0.6-0.85 for a single stage]
  ok   TURB-4     rotor-exit hub/tip ratio upper                    0.620 <= 0.880               +29.5 %  [very short blades: clearance losses]
  ok   TURB-5     blade root stress at MCS x margin vs allowable      369.4 <= 436.0      MPa      +15.3 %  [IN713LC min(yield, creep) at 1030 K; margin 1.25]
  ok   TURB-6     rotor metal temperature vs material limit        1030.0 <= 1223.0     K        +15.8 %  [IN713LC T_max]
  ok   TURB-7     NGV metal temperature vs material limit          1150.0 <= 1223.0     K         +6.0 %  [IN713LC T_max]
  ok   TURB-8     NGV exit Mach                                     0.846 <= 1.050               +19.5 %  [subsonic/transonic NGV practice]
  ok   TURB-9     rotor exit absolute Mach                          0.385 <= 0.600               +35.9 %  [jet-pipe entry Mach; boomsonic R7.1 annulus cap]
  ok   TURB-10    estimated vs assumed turbine efficiency |diff|      0.002 <= 0.030               +92.5 %  [consistency: run `jet converge`]
  ok   TURB-11    AN2 (rotor annulus x rpm^2) at MCS            3.527e+07 <= 4.500e+07  m2rpm2   +21.6 %  [uncooled cast wheels: JetCat/AMT class 2-3.5e7, ceiling ~4.5e7 m2 rpm2]
  info TURB-12    turbine tip diameter (info)                       131.2    -          mm                [-]
[combustor]
  ok   COMB-1     reference velocity                               15.259 <= 25.000     m/s      +39.0 %  [Lefebvre: annular 15-25 m/s; micro practice ~20]
  ok   COMB-2     reference velocity minimum                       15.259 >= 12.000     m/s      +27.2 %  [low U_ref wastes volume]
  ok   COMB-3     liner residence time                              2.500 >= 2.500      ms        +0.0 %  [vaporiser combustors 4-7 ms (JetCat/AMT class)]
  ok   COMB-4     liner length / height                             2.800 <= 3.600               +22.2 %  [practice 2.5-3.5 (Lefebvre)]
  ok   COMB-5     liner metal temperature margin (T04 vs liner T_max; film-cooled liners run cooler)     1150.0 <= 1403.0     K        +18.0 %  [IN625 T_max + 150 K film credit]
  ok   COMB-6     heat release rate                                 137.7 <= 300.0      MW/m3bar   +54.1 %  [large annular 20-60, micro-turbojet vaporiser combustors up to ~300 MW/(m3 bar)]
  ok   COMB-7     air split sums to 1                               1.000 <= 1.000                +0.0 %  [input check]
  ok   COMB-8     vaporiser fuel loading                            4.811 <= 12.000     kg/h     +59.9 %  [practice 3-12 kg/h per tube]
[layout]
  info LAY-1      engine outer diameter vs limit                    221.7 <= -          mm                [requirements.max_diameter_mm]
  info LAY-2      engine length vs limit                            398.0 <= -          mm                [requirements.max_length_mm]
  ok   LAY-3      bearing span / D2 (rotordynamic sanity)           0.706 <= 2.200               +67.9 %  [long spans lower the bending critical; boomsonic_v0 1.43]
  ok   LAY-4      tail cone shorter than nozzle                     0.125 <= 0.139               +10.1 %  [geometry]
[rotor]
  ok   ROT-1      bearing DN at MCS vs rating                   1.107e+06 <= 1.500e+06  mm.rpm   +26.2 %  [71903C-HC catalogue DN limit]
  ok   ROT-2      bearing temperature rating                        420.0 <= 523.0      K        +19.7 %  [71903C-HC T_max]
  ok   ROT-3      first bending critical / MCS                      2.500 >= 1.250              +100.0 %  [API 684 separation margin practice (25 %)]
  ok   ROT-4      rigid-body criticals below 60 % speed (soft mount)      0.372 <= 0.600               +38.0 %  [traverse rigid modes below idle-to-cruise band]
  ok   ROT-5      journal torsional stress                         34.730 <= 175.3      MPa      +80.2 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-6      tube torsional stress                             3.436 <= 175.3      MPa      +98.0 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-7      shaft tunnel fits inside combustor inner casing      0.024 <= 0.057      m        +57.9 %  [layout: tunnel OD + 3 mm gap]
  info ROT-8      bearing L10 life (info)                       1.528e+06    -          h                 [ISO 281 basic rating (no thermal factors)]
[mechanical]
  ok   MECH-1     impeller disc peak stress at MCS vs yield         426.1 <= 593.3      MPa      +28.2 %  [Ti-6Al-4V min-basis yield at 474 K; k_peak 1.6]
  ok   MECH-2     impeller burst speed ratio                        1.456 >= 1.200               +21.4 %  [14 CFR 33.27 style; Robinson k 0.85]
  ok   MECH-3     inducer root radial stress vs yield               130.2 <= 593.3      MPa      +78.0 %  [Ti-6Al-4V yield]
  ok   MECH-4     exducer root stress (from compressor stage, sized to limit) vs allowable      578.9 <= 578.9      MPa       +0.0 %  [compressor.COMP-3]
  ok   MECH-5     turbine disc peak stress vs bore allowable        531.6 <= 630.8      MPa      +15.7 %  [IN713LC allowable at bore 750 K]
  ok   MECH-6     turbine disc average stress vs rim creep allowable      408.9 <= 615.9      MPa      +33.6 %  [IN713LC allowable at rim 950 K]
  WARN MECH-7     turbine burst speed ratio                         1.251 >= 1.200                +4.2 %  [14 CFR 33.27 style; Robinson k 0.85]
  ok   MECH-8     turbine blade root (from turbine stage)           295.5 <= 436.0      MPa      +32.2 %  [turbine.TURB-5 (no margin factor here)]
  ok   MECH-9     impeller clamp load retained hot                72145.5 >= 18429.5    N       +291.5 %  [tie-shaft preload minus thermal relaxation and gas load >= 20 % of preload]
[geometry]
  info GEO-1      dry mass estimate vs limit                        9.353 <= -          kg                [requirements.max_mass_kg]
  info GEO-2      thrust/weight (info)                              5.449    -          -                 [-]
  info GEO-3      flange screws count (info)                       18.000    -                            [ISO 4762 M2]
```