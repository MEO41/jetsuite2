# boomsonic-geometry-matched - design report (v2)

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
| efficiencies estimated (c / t) | 0.7944 / 0.8988 |

## Spool speed

7.5e+04 rpm (user); limits: inducer 65848, turbine AN2 58116, turbine disc 52882, bearing DN 1.0119e+05 rpm

## Compressor

| item | value |
|---|---|
| material | Ti-6Al-4V |
| inducer r1h / r1s | 18.14 / 51.84 mm, M1rel 1.331 |
| impeller D2 / b2 / L | 130.1 / 16.17 / 41.64 mm |
| U2 / backsweep / blades | 511 m/s / 15 deg / 12+12 |
| slip / work coefficient | 0.8758 / 0.8008 |
| exducer root / tip thickness | 3.612 / 0.6506 mm |
| diffuser | vaned, r3/r2 1.06, r4 87.83 mm, 19 vanes, M4 0.4955 |
| choke margin | 0.07836 |

## Turbine

| item | value |
|---|---|
| material (rotor / NGV) | IN713LC / IN713LC |
| psi / phi / reaction | 1.2 / 0.65 / 0.4 |
| mean radius / heights | 54 mm; NGV 19.85 mm, rotor 32.29 mm |
| tip diameter / hub-tip | 140.3 mm / 0.5397 |
| counts NGV / rotor | 34 / 28 |
| root stress at MCS / allowable | 569.3 / 436 MPa |

## Combustor

Annular, Ro 86.83 mm, Ri 25.5 mm, liner 139.9 mm long, U_ref 23.72 m/s, residence 2.5 ms, 12 vaporisers, igniter glow-1/4-32.

## Rotor

Bearings 71901C-HC (DN 9.45e+05 at MCS), journal 12 mm, tube 32 x 25.6 mm, span 161.4 mm. Forward criticals: 7817, 10213, 161509 rpm (rigid-body: 7817, 10213); first bending 161509 rpm.

## Envelope and mass

OD 177.7 mm x length 413.2 mm; estimated dry mass 8.6 kg.

| part | material | mass kg |
|---|---|---|
| impeller | Ti-6Al-4V | 1.079 |
| inlet_shroud | Al6061-T6 | 0.198 |
| diffuser | Al2618-T61 | 0.337 |
| outer_casing | AISI321 | 0.947 |
| combustor_liners | IN625 | 0.796 |
| inner_casing | AISI321 | 0.196 |
| ngv_ring | IN713LC | 0.781 |
| turbine_wheel | IN713LC | 1.554 |
| turbine_shroud | AISI321 | 0.193 |
| shaft | AISI4340 | 0.438 |
| bearings | steel/ceramic | 0.020 |
| housings_tunnel | AISI321 | 0.966 |
| nozzle_tailcone | AISI321 | 0.561 |

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
  FAIL SPD-1      inducer shroud relative Mach at design            1.331 <= 1.330                -0.1 %  [fielded micro-turbojet band 1.10-1.33 (boomsonic_v0 A3R.1)]
       -> lower rpm, larger hub/tip ratio or higher inlet Mach margin
  FAIL SPD-2      design rpm vs turbine AN2 limit                 75000.0 <= 58116.4    rpm      -29.1 %  [AN2 with IN713LC allowable 436 MPa at 1030 K, margin 1.25]
       -> lower rpm, stronger turbine material, or lower T04
  FAIL SPD-2b     design rpm vs turbine disc bore-stress limit    75000.0 <= 52881.6    rpm      -41.8 %  [bored IN713LC wheel, allowable 631 MPa at 750 K, k_peak 1.3]
       -> lower rpm, smaller hub/tip target, boreless wheel or stronger material
  ok   SPD-3      design rpm vs bearing DN limit                  75000.0 <= 1.012e+05  rpm      +25.9 %  [bearing 71901C-HC DN 1.5e+06 x 0.85]
  info SPD-4      impeller tip speed allowed by material (info: set by work, see COMP-3)      437.6    -          m/s               [Ti-6Al-4V yield at Tt3]
[compressor]
  FAIL COMP-1     inducer shroud relative Mach                      1.331 <= 1.300                -2.4 %  [fielded micro-turbojet band (boomsonic A3R.1)]
       -> reduce rpm or raise hub/tip ratio
  ok   COMP-2     impeller tip speed U2                             511.0 <= 620.0      m/s      +17.6 %  [Ti impellers ~550-600 m/s, Al ~450-500 (Dixon; Rodgers)]
  ok   COMP-3     exducer root stress at MCS vs allowable (root sized to the limit)      559.5 <= 559.5      MPa       +0.0 %  [Ti-6Al-4V yield at 521 K / SF 1.0]
  ok   COMP-4     impeller material temperature (Tt3)               520.9 <= 673.0      K        +22.6 %  [Ti-6Al-4V T_max]
  ok   COMP-5     exit width ratio b2/D2                            0.124 >= 0.030              +314.3 %  [narrow exits lose efficiency (Rodgers): b2/D2 >= 0.03]
  WARN COMP-6     relative diffusion ratio W1s/W2                   2.584 <= 2.000               -29.2 %  [Dixon & Hall / Rodgers: W1s/W2 <= ~1.8-2.0 for attached flow]
       -> raise phi2 (wider exit), more backsweep, or reduce inducer Mach
  WARN COMP-7     inducer throat choke margin at design             0.078 >= 0.100               -21.6 %  [Rodgers: design at <= 90 % of throat choke flow (boomsonic A3R.5)]
       -> thinner LE, fewer main blades, larger hub/tip or lower inducer relative Mach
  ok   COMP-7b    inducer throat not choked at design               0.078 >= 0                    +7.8 %  [throat mass-flow function]
  WARN COMP-8     radius ratio r2/r1s                               1.255 >= 1.300                -3.5 %  [Aungier: 1.4-2.2 for a radial impeller]
       -> rpm too high for the required work: reduce rpm
  ok   COMP-9     radius ratio r2/r1s upper                         1.255 <= 2.300               +45.4 %  [Aungier: 1.4-2.2 for a radial impeller]
  WARN COMP-10    impeller exit absolute Mach                       1.045 <= 1.100                +5.0 %  [vaned diffuser LE tolerates ~M 1.1 (Japikse)]
  WARN COMP-11    diffuser inlet flow angle from radial            74.178 <= 78.000               +4.9 %  [vaneless stability: alpha < ~78 deg (Senoo)]
       -> more backsweep or higher phi2 to reduce swirl
  FAIL COMP-12    estimated vs assumed stage efficiency |diff|      0.094 <= 0.030              -214.5 %  [consistency: run `jet converge`]
       -> estimate 0.794 vs cycle assumption 0.700
  ok   COMP-13    backsweep angle                                  15.000 <= 45.000              +66.7 %  [manufacturing/loading practice 15-45 deg]
  WARN COMP-14    backsweep angle minimum for stability            15.000 >= 15.000               +0.0 %  [range/stability practice]
  ok   COMP-15    implied diffuser total-pressure loss              0.092 <= 0.120               +23.0 %  [impeller/diffuser split: 3-10 % typical]
[turbine]
  ok   TURB-1     stage loading psi                                 1.200 <= 2.400               +50.0 %  [Smith chart: efficiency falls fast above ~2.2]
  WARN TURB-2     stage loading psi minimum                         1.200 >= 1.200                +0.0 %  [below ~1.2 the annulus becomes very short]
  FAIL TURB-3     rotor-exit hub/tip ratio                          0.540 >= 0.550                -1.9 %  [practice 0.6-0.85 for a single stage]
       -> too long blades: raise psi target or rpm
  ok   TURB-4     rotor-exit hub/tip ratio upper                    0.540 <= 0.880               +38.7 %  [very short blades: clearance losses]
  FAIL TURB-5     blade root stress at MCS x margin vs allowable      711.6 <= 436.0      MPa      -63.2 %  [IN713LC min(yield, creep) at 1030 K; margin 1.25]
       -> lower rpm, shorter blades (higher psi/hub-tip), stronger material or lower T04
  ok   TURB-6     rotor metal temperature vs material limit        1030.0 <= 1223.0     K        +15.8 %  [IN713LC T_max]
  ok   TURB-7     NGV metal temperature vs material limit          1150.0 <= 1223.0     K         +6.0 %  [IN713LC T_max]
  ok   TURB-8     NGV exit Mach                                     0.934 <= 1.050               +11.0 %  [subsonic/transonic NGV practice]
  ok   TURB-9     rotor exit absolute Mach                          0.462 <= 0.600               +23.1 %  [jet-pipe entry Mach; boomsonic R7.1 annulus cap]
  FAIL TURB-10    estimated vs assumed turbine efficiency |diff|      0.149 <= 0.030              -395.9 %  [consistency: run `jet converge`]
       -> estimate 0.899 vs cycle assumption 0.750
  WARN TURB-11    AN2 (rotor annulus x rpm^2) at MCS            6.795e+07 <= 4.500e+07  m2rpm2   -51.0 %  [uncooled cast wheels: JetCat/AMT class 2-3.5e7, ceiling ~4.5e7 m2 rpm2]
  info TURB-12    turbine tip diameter (info)                       140.3    -          mm                [-]
[combustor]
  ok   COMB-1     reference velocity                               23.719 <= 25.000     m/s       +5.1 %  [Lefebvre: annular 15-25 m/s; micro practice ~20]
  ok   COMB-2     reference velocity minimum                       23.719 >= 12.000     m/s      +97.7 %  [low U_ref wastes volume]
  ok   COMB-3     liner residence time                              2.500 >= 2.500      ms        +0.0 %  [vaporiser combustors 4-7 ms (JetCat/AMT class)]
  ok   COMB-4     liner length / height                             3.354 <= 3.600                +6.8 %  [practice 2.5-3.5 (Lefebvre)]
  ok   COMB-5     liner metal temperature margin (T04 vs liner T_max; film-cooled liners run cooler)     1150.0 <= 1403.0     K        +18.0 %  [IN625 T_max + 150 K film credit]
  ok   COMB-6     heat release rate                                 130.3 <= 300.0      MW/m3bar   +56.6 %  [large annular 20-60, micro-turbojet vaporiser combustors up to ~300 MW/(m3 bar)]
  ok   COMB-7     air split sums to 1                               1.000 <= 1.000                +0.0 %  [input check]
  ok   COMB-8     vaporiser fuel loading                            7.576 <= 12.000     kg/h     +36.9 %  [practice 3-12 kg/h per tube]
[layout]
  info LAY-1      engine outer diameter vs limit                    177.7 <= -          mm                [requirements.max_diameter_mm]
  info LAY-2      engine length vs limit                            413.2 <= -          mm                [requirements.max_length_mm]
  ok   LAY-3      bearing span / D2 (rotordynamic sanity)           1.240 <= 2.200               +43.6 %  [long spans lower the bending critical; boomsonic_v0 1.43]
  WARN LAY-4      tail cone shorter than nozzle                     0.117 <= 0.113                -3.3 %  [geometry]
[rotor]
  ok   ROT-1      bearing DN at MCS vs rating                   9.450e+05 <= 1.500e+06  mm.rpm   +37.0 %  [71901C-HC catalogue DN limit]
  ok   ROT-2      bearing temperature rating                        420.0 <= 523.0      K        +19.7 %  [71901C-HC T_max]
  ok   ROT-3      first bending critical / MCS                      2.051 >= 1.250               +64.1 %  [API 684 separation margin practice (25 %)]
  ok   ROT-4      rigid-body criticals below 60 % speed (soft mount)      0.136 <= 0.600               +77.3 %  [traverse rigid modes below idle-to-cruise band]
  ok   ROT-5      journal torsional stress                          115.0 <= 175.3      MPa      +34.4 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-6      tube torsional stress                            10.273 <= 175.3      MPa      +94.1 %  [AISI4340 0.577 Fty / SF 3]
  ok   ROT-7      shaft tunnel fits inside combustor inner casing      0.019 <= 0.023      m        +13.3 %  [layout: tunnel OD + 3 mm gap]
  info ROT-8      bearing L10 life (info)                       4.531e+05    -          h                 [ISO 281 basic rating (no thermal factors)]
[mechanical]
  ok   MECH-1     impeller disc peak stress at MCS vs yield         392.6 <= 573.9      MPa      +31.6 %  [Ti-6Al-4V min-basis yield at 501 K; k_peak 1.3]
  ok   MECH-2     impeller burst speed ratio                        1.338 >= 1.200               +11.5 %  [14 CFR 33.27 style; Robinson k 0.85]
  ok   MECH-3     inducer root radial stress vs yield               213.1 <= 573.9      MPa      +62.9 %  [Ti-6Al-4V yield]
  ok   MECH-4     exducer root stress (from compressor stage, sized to limit) vs allowable      559.5 <= 559.5      MPa       +0.0 %  [compressor.COMP-3]
  FAIL MECH-5     turbine disc peak stress vs bore allowable        873.9 <= 630.8      MPa      -38.5 %  [IN713LC allowable at bore 750 K]
       -> thicker web/hub, lower rpm
  FAIL MECH-6     turbine disc average stress vs rim creep allowable      672.3 <= 615.9      MPa       -9.2 %  [IN713LC allowable at rim 950 K]
  FAIL MECH-7     turbine burst speed ratio                         0.976 >= 1.200               -18.7 %  [14 CFR 33.27 style; Robinson k 0.85]
  FAIL MECH-8     turbine blade root (from turbine stage)           569.3 <= 436.0      MPa      -30.6 %  [turbine.TURB-5 (no margin factor here)]
  ok   MECH-9     impeller clamp load retained hot                34491.5 >= 9182.9     N       +275.6 %  [tie-shaft preload minus thermal relaxation and gas load >= 20 % of preload]
[geometry]
  info GEO-1      dry mass estimate vs limit                        8.599 <= -          kg                [requirements.max_mass_kg]
  info GEO-2      thrust/weight (info)                              5.927    -          -                 [-]
  info GEO-3      flange screws count (info)                       15.000    -                            [ISO 4762 M2]
```