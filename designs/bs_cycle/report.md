# boomsonic-cycle-matched - design report (v2)

Overall rule verdict: **fail**

## Requirements and cycle

| item | value |
|---|---|
| thrust | 500 N at 5000 m, M 1.02 |
| OPR / T04 | 4 / 1150 K |
| airflow / fuel flow | 1.409 kg/s / 0.02525 kg/s |
| TSFC | 0.1818 kg/(N h) |
| Tt3 / Tt5 | 520.9 / 968.1 K |
| turbine PR / NPR | 2.662 / 2.629 (choked) |
| efficiencies assumed (c / t) | 0.7 / 0.75 |
| efficiencies estimated (c / t) | 0.7632 / 0.8726 |

## Spool speed

4.95e+04 rpm (auto (binding: turbine_disc)); limits: inducer 65848, turbine AN2 58116, turbine disc 51115, bearing DN 60714 rpm

## Compressor

| item | value |
|---|---|
| material | Ti-6Al-4V |
| inducer r1h / r1s | 19.47 / 55.62 mm, M1rel 0.9632 |
| impeller D2 / b2 / L | 216 / 7.437 / 69.13 mm |
| U2 / backsweep / blades | 559.9 m/s / 30 deg / 7+7 |
| slip / work coefficient | 0.8285 / 0.6668 |
| exducer root / tip thickness | 1.752 / 1.08 mm |
| diffuser | vaned, r3/r2 1.08, r4 149.1 mm, 9 vanes, M4 0.4226 |
| choke margin | 0.1122 |

## Turbine

| item | value |
|---|---|
| material (rotor / NGV) | IN713LC / IN713LC |
| psi / phi / reaction | 1.8 / 0.65 / 0.4 |
| mean radius / heights | 66.8 mm; NGV 19.29 mm, rotor 31.34 mm |
| tip diameter / hub-tip | 164.9 mm / 0.62 |
| counts NGV / rotor | 19 / 24 |
| root stress at MCS / allowable | 297.7 / 436 MPa |

## Combustor

Annular, Ro 148.1 mm, Ri 88.84 mm, liner 112.8 mm long, U_ref 11.65 m/s, residence 4.106 ms, 16 vaporisers, igniter glow-1/4-32.

## Rotor

Bearings 71904C-HC (DN 1.04e+06 at MCS), journal 20 mm, tube 48 x 34.56 mm, span 133.3 mm. Forward criticals: 11862, 16255 rpm (rigid-body: 11862, 16255); first bending above scan ceiling 129938 rpm.

## Envelope and mass

OD 300.1 mm x length 497.2 mm; estimated dry mass 17 kg.

| part | material | mass kg |
|---|---|---|
| impeller | Ti-6Al-4V | 3.482 |
| inlet_shroud | Al6061-T6 | 0.482 |
| diffuser | Al2618-T61 | 0.690 |
| outer_casing | AISI321 | 1.594 |
| combustor_liners | IN625 | 1.464 |
| inner_casing | AISI321 | 0.662 |
| ngv_ring | IN713LC | 0.672 |
| turbine_wheel | IN713LC | 2.398 |
| turbine_shroud | AISI321 | 0.220 |
| shaft | AISI4340 | 1.151 |
| bearings | steel/ceramic | 0.066 |
| housings_tunnel | AISI321 | 2.180 |
| nozzle_tailcone | AISI321 | 0.971 |

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
  info CYC-5      compressor exit temperature vs aluminium impeller limit (info)      520.9    -          K                 [materials.T_max]
  info CYC-6      nozzle pressure ratio                             2.629    -          -                 [-]
  ok   CYC-7      fuel-air ratio below 60 % stoichiometric          0.018 <= 0.041               +55.8 %  [combustor: overall phi < 0.6]
[speed]
  ok   SPD-1      inducer shroud relative Mach at design            0.963 <= 1.300               +25.9 %  [fielded micro-turbojet band 1.10-1.33 (boomsonic_v0 A3R.1)]
  ok   SPD-2      design rpm vs turbine AN2 limit                 49500.0 <= 58116.4    rpm      +14.8 %  [AN2 with IN713LC allowable 436 MPa at 1030 K, margin 1.25]
  ok   SPD-2b     design rpm vs turbine disc bore-stress limit    49500.0 <= 51114.8    rpm       +3.2 %  [bored IN713LC wheel, allowable 631 MPa at 750 K, k_peak 1.3]
  ok   SPD-3      design rpm vs bearing DN limit                  49500.0 <= 60714.3    rpm      +18.5 %  [bearing 71904C-HC DN 1.5e+06 x 0.85]
  info SPD-4      impeller tip speed allowed by material (info: set by work, see COMP-3)      437.6    -          m/s               [Ti-6Al-4V yield at Tt3]
[compressor]
  ok   COMP-1     inducer shroud relative Mach                      0.963 <= 1.300               +25.9 %  [fielded micro-turbojet band (boomsonic A3R.1)]
  ok   COMP-2     impeller tip speed U2                             559.9 <= 620.0      m/s       +9.7 %  [Ti impellers ~550-600 m/s, Al ~450-500 (Dixon; Rodgers)]
  ok   COMP-3     exducer root stress at MCS vs allowable (root sized to the limit)      559.5 <= 559.5      MPa       +0.0 %  [Ti-6Al-4V yield at 521 K / SF 1.0]
  ok   COMP-4     impeller material temperature (Tt3)               520.9 <= 673.0      K        +22.6 %  [Ti-6Al-4V T_max]
  ok   COMP-5     exit width ratio b2/D2                            0.034 >= 0.030               +14.8 %  [narrow exits lose efficiency (Rodgers): b2/D2 >= 0.03]
  ok   COMP-6     relative diffusion ratio W1s/W2                   1.362 <= 2.000               +31.9 %  [Dixon & Hall / Rodgers: W1s/W2 <= ~1.8-2.0 for attached flow]
  ok   COMP-7     inducer throat choke margin at design             0.112 >= 0.100               +12.2 %  [Rodgers: design at <= 90 % of throat choke flow (boomsonic A3R.5)]
  ok   COMP-7b    inducer throat not choked at design               0.112 >= 0                   +11.2 %  [throat mass-flow function]
  ok   COMP-8     radius ratio r2/r1s                               1.942 >= 1.300               +49.4 %  [Aungier: 1.4-2.2 for a radial impeller]
  ok   COMP-9     radius ratio r2/r1s upper                         1.942 <= 2.300               +15.6 %  [Aungier: 1.4-2.2 for a radial impeller]
  ok   COMP-10    impeller exit absolute Mach                       0.964 <= 1.100               +12.4 %  [vaned diffuser LE tolerates ~M 1.1 (Japikse)]
  ok   COMP-11    diffuser inlet flow angle from radial            69.166 <= 78.000              +11.3 %  [vaneless stability: alpha < ~78 deg (Senoo)]
  FAIL COMP-12    estimated vs assumed stage efficiency |diff|      0.063 <= 0.030              -110.7 %  [consistency: run `jet converge`]
       -> estimate 0.763 vs cycle assumption 0.700
  ok   COMP-13    backsweep angle                                  30.000 <= 45.000              +33.3 %  [manufacturing/loading practice 15-45 deg]
  ok   COMP-14    backsweep angle minimum for stability            30.000 >= 15.000             +100.0 %  [range/stability practice]
  ok   COMP-15    implied diffuser total-pressure loss              0.092 <= 0.120               +23.0 %  [impeller/diffuser split: 3-10 % typical]
[turbine]
  ok   TURB-1     stage loading psi                                 1.800 <= 2.400               +25.0 %  [Smith chart: efficiency falls fast above ~2.2]
  ok   TURB-2     stage loading psi minimum                         1.800 >= 1.200               +50.0 %  [below ~1.2 the annulus becomes very short]
  ok   TURB-3     rotor-exit hub/tip ratio                          0.620 >= 0.550               +12.7 %  [practice 0.6-0.85 for a single stage]
  ok   TURB-4     rotor-exit hub/tip ratio upper                    0.620 <= 0.880               +29.5 %  [very short blades: clearance losses]
  ok   TURB-5     blade root stress at MCS x margin vs allowable      372.1 <= 436.0      MPa      +14.7 %  [IN713LC min(yield, creep) at 1030 K; margin 1.25]
  ok   TURB-6     rotor metal temperature vs material limit        1030.0 <= 1223.0     K        +15.8 %  [IN713LC T_max]
  ok   TURB-7     NGV metal temperature vs material limit          1150.0 <= 1223.0     K         +6.0 %  [IN713LC T_max]
  ok   TURB-8     NGV exit Mach                                     0.911 <= 1.050               +13.2 %  [subsonic/transonic NGV practice]
  ok   TURB-9     rotor exit absolute Mach                          0.414 <= 0.600               +31.0 %  [jet-pipe entry Mach; boomsonic R7.1 annulus cap]
  FAIL TURB-10    estimated vs assumed turbine efficiency |diff|      0.123 <= 0.030              -308.6 %  [consistency: run `jet converge`]
       -> estimate 0.873 vs cycle assumption 0.750
  ok   TURB-11    AN2 (rotor annulus x rpm^2) at MCS            3.554e+07 <= 4.500e+07  m2rpm2   +21.0 %  [uncooled cast wheels: JetCat/AMT class 2-3.5e7, ceiling ~4.5e7 m2 rpm2]
  info TURB-12    turbine tip diameter (info)                       164.9    -          mm                [-]
[combustor]
  ok   COMB-1     reference velocity                               11.645 <= 25.000     m/s      +53.4 %  [Lefebvre: annular 15-25 m/s; micro practice ~20]
  WARN COMB-2     reference velocity minimum                       11.645 >= 12.000     m/s       -3.0 %  [low U_ref wastes volume]
  ok   COMB-3     liner residence time                              4.106 >= 2.500      ms       +64.2 %  [vaporiser combustors 4-7 ms (JetCat/AMT class)]
  ok   COMB-4     liner length / height                             2.800 <= 3.600               +22.2 %  [practice 2.5-3.5 (Lefebvre)]
  ok   COMB-5     liner metal temperature margin (T04 vs liner T_max; film-cooled liners run cooler)     1150.0 <= 1403.0     K        +18.0 %  [IN625 T_max + 150 K film credit]
  ok   COMB-6     heat release rate                                79.321 <= 300.0      MW/m3bar   +73.6 %  [large annular 20-60, micro-turbojet vaporiser combustors up to ~300 MW/(m3 bar)]
  ok   COMB-7     air split sums to 1                               1.000 <= 1.000                +0.0 %  [input check]
  ok   COMB-8     vaporiser fuel loading                            5.682 <= 12.000     kg/h     +52.6 %  [practice 3-12 kg/h per tube]
[layout]
  info LAY-1      engine outer diameter vs limit                    300.1 <= -          mm                [requirements.max_diameter_mm]
  info LAY-2      engine length vs limit                            497.2 <= -          mm                [requirements.max_length_mm]
  ok   LAY-3      bearing span / D2 (rotordynamic sanity)           0.617 <= 2.200               +72.0 %  [long spans lower the bending critical; boomsonic_v0 1.43]
  ok   LAY-4      tail cone shorter than nozzle                     0.157 <= 0.174                +9.8 %  [geometry]
[rotor]
  ok   ROT-1      bearing DN at MCS vs rating                   1.040e+06 <= 1.500e+06  mm.rpm   +30.7 %  [71904C-HC catalogue DN limit]
  ok   ROT-2      bearing temperature rating                        420.0 <= 523.0      K        +19.7 %  [71904C-HC T_max]
  ok   ROT-3      first bending critical / MCS                      2.500 >= 1.250              +100.0 %  [API 684 separation margin practice (25 %)]
  ok   ROT-4      rigid-body criticals below 60 % speed (soft mount)      0.328 <= 0.600               +45.3 %  [traverse rigid modes below idle-to-cruise band]
  ok   ROT-5      journal torsional stress                         37.642 <= 175.3      MPa      +78.5 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-6      tube torsional stress                             3.724 <= 175.3      MPa      +97.9 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-7      shaft tunnel fits inside combustor inner casing      0.028 <= 0.086      m        +68.0 %  [layout: tunnel OD + 3 mm gap]
  info ROT-8      bearing L10 life (info)                       5.181e+05    -          h                 [ISO 281 basic rating (no thermal factors)]
[mechanical]
  ok   MECH-1     impeller disc peak stress at MCS vs yield         474.1 <= 573.9      MPa      +17.4 %  [Ti-6Al-4V min-basis yield at 501 K; k_peak 1.6]
  ok   MECH-2     impeller burst speed ratio                        1.351 >= 1.200               +12.6 %  [14 CFR 33.27 style; Robinson k 0.85]
  ok   MECH-3     inducer root radial stress vs yield               106.9 <= 573.9      MPa      +81.4 %  [Ti-6Al-4V yield]
  ok   MECH-4     exducer root stress (from compressor stage, sized to limit) vs allowable      559.5 <= 559.5      MPa       +0.0 %  [compressor.COMP-3]
  ok   MECH-5     turbine disc peak stress vs bore allowable        559.8 <= 630.8      MPa      +11.3 %  [IN713LC allowable at bore 750 K]
  ok   MECH-6     turbine disc average stress vs rim creep allowable      430.6 <= 615.9      MPa      +30.1 %  [IN713LC allowable at rim 950 K]
  WARN MECH-7     turbine burst speed ratio                         1.219 >= 1.200                +1.6 %  [14 CFR 33.27 style; Robinson k 0.85]
  ok   MECH-8     turbine blade root (from turbine stage)           297.7 <= 436.0      MPa      +31.7 %  [turbine.TURB-5 (no margin factor here)]
  ok   MECH-9     impeller clamp load retained hot                95543.9 >= 25508.0    N       +274.6 %  [tie-shaft preload minus thermal relaxation and gas load >= 20 % of preload]
[geometry]
  info GEO-1      dry mass estimate vs limit                       17.042 <= -          kg                [requirements.max_mass_kg]
  info GEO-2      thrust/weight (info)                              2.991    -          -                 [-]
  info GEO-3      flange screws count (info)                       25.000    -                            [ISO 4762 M2.5]
```