# Design rules

Generated from a 500 N sea-level-static design; limits that depend on inputs (materials, margins) show the values for that design. `kind` max: value must stay below the limit; min: above. Soft rules produce warnings, never failures.


## requirements

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| REQ-1 | thrust target inside supported range | max | 1000 | N | brief: 100-1000 N | above 1000 N a single centrifugal stage needs OPR/size outside the calibrated range |
| REQ-2 | thrust target above minimum | min | 100 | N | brief: 100-1000 N |  |
| REQ-3 | design Mach subsonic (pitot intake model) | max | 1 |  | intake model: normal shock + duct | supersonic design points use a normal-shock recovery; check intake separately |

## cycle

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| CYC-1 | OPR within single-stage centrifugal practice | max | 5 |  | Dixon & Hall ch.7; micro-turbojet fleet 2.5-4.5 | above ~5 a single backswept impeller needs U2 > 600 m/s |
| CYC-2 | OPR above useful minimum | min | 2.2 |  | cycle: specific thrust collapses below ~2.2 |  |
| CYC-3 | T04 within uncooled cast-wheel practice | max | 1250 |  | IN-713LC/MAR-M247 uncooled rotor practice (JetCat/AMT class 1050-1200 K) | above 1250 K an uncooled wheel is creep-life limited; check MECH turbine rules |
| CYC-4 | T04 above combustor stability floor | min | 950 |  | lean stability at idle/design |  |
| CYC-5 | compressor exit temperature vs aluminium impeller limit (info) | info | - | K | materials.T_max |  |
| CYC-6 | nozzle pressure ratio | info | - | - | - |  |
| CYC-7 | fuel-air ratio below 60 % stoichiometric | max | 0.04098 |  | combustor: overall phi < 0.6 |  |

## speed

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| SPD-1 | inducer shroud relative Mach at design | max | 1.3 |  | fielded micro-turbojet band 1.10-1.33 (boomsonic_v0 A3R.1) | lower rpm, larger hub/tip ratio or higher inlet Mach margin |
| SPD-2 | design rpm vs turbine AN2 limit | max | 8.523e+04 | rpm | AN2 with IN713LC allowable 436 MPa at 1030 K, margin 1.25 | lower rpm, stronger turbine material, or lower T04 |
| SPD-2b | design rpm vs turbine disc bore-stress limit | max | 7.497e+04 | rpm | bored IN713LC wheel, allowable 631 MPa at 750 K, k_peak 1.3 | lower rpm, smaller hub/tip target, boreless wheel or stronger material |
| SPD-3 | design rpm vs bearing DN limit | max | 8.095e+04 | rpm | bearing 71902C-HC DN 1.5e+06 x 0.85 | smaller journal (if torque allows), hybrid bearing, or lower rpm |
| SPD-4 | impeller tip speed allowed by material (info: set by work, see COMP-3) | info | - | m/s | Al2618-T61 yield at Tt3 |  |

## compressor

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| COMP-1 | inducer shroud relative Mach | max | 1.3 |  | fielded micro-turbojet band (boomsonic A3R.1) | reduce rpm or raise hub/tip ratio |
| COMP-2 | impeller tip speed U2 | max | 620 | m/s | Ti impellers ~550-600 m/s, Al ~450-500 (Dixon; Rodgers) | lower OPR, less backsweep, more blades, or accept a stronger material |
| COMP-3 | exducer root stress at MCS vs allowable (root sized to the limit) | max | 243.6 | MPa | Al2618-T61 yield at 461 K / SF 1.0 | root thickness capped at 20 mm: reduce U2 or backsweep, or change material |
| COMP-4 | impeller material temperature (Tt3) | max | 473 | K | Al2618-T61 T_max | compressor exit too hot for this material: lower OPR or change material |
| COMP-5 | exit width ratio b2/D2 | min | 0.03 |  | narrow exits lose efficiency (Rodgers): b2/D2 >= 0.03 | raise phi2 or backsweep, or lower rpm |
| COMP-6 | relative diffusion ratio W1s/W2 | max | 2 |  | Dixon & Hall / Rodgers: W1s/W2 <= ~1.8-2.0 for attached flow | raise phi2 (wider exit), more backsweep, or reduce inducer Mach |
| COMP-7 | inducer throat choke margin at design | min | 0.1 |  | Rodgers: design at <= 90 % of throat choke flow (boomsonic A3R.5) | thinner LE, fewer main blades, larger hub/tip or lower inducer relative Mach |
| COMP-7b | inducer throat not choked at design | min | 0 |  | throat mass-flow function | the inducer throat is choked: lower rpm / relative Mach or open the throat |
| COMP-8 | radius ratio r2/r1s | min | 1.3 |  | Aungier: 1.4-2.2 for a radial impeller | rpm too high for the required work: reduce rpm |
| COMP-9 | radius ratio r2/r1s upper | max | 2.3 |  | Aungier: 1.4-2.2 for a radial impeller | rpm too low: raise rpm or hub/tip ratio |
| COMP-10 | impeller exit absolute Mach | max | 1.1 |  | vaned diffuser LE tolerates ~M 1.1 (Japikse) |  |
| COMP-11 | diffuser inlet flow angle from radial | max | 78 |  | vaneless stability: alpha < ~78 deg (Senoo) | more backsweep or higher phi2 to reduce swirl |
| COMP-12 | estimated vs assumed stage efficiency |diff| | max | 0.03 |  | consistency: run `jet converge` | estimate 0.808 vs cycle assumption 0.805 |
| COMP-13 | backsweep angle | max | 45 |  | manufacturing/loading practice 15-45 deg |  |
| COMP-14 | backsweep angle minimum for stability | min | 15 |  | range/stability practice |  |
| COMP-15 | implied diffuser total-pressure loss | max | 0.12 |  | impeller/diffuser split: 3-10 % typical | impeller_eta_offset too large or eta_c assumption too low |

## turbine

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| TURB-1 | stage loading psi | max | 2.4 |  | Smith chart: efficiency falls fast above ~2.2 | raise rpm (larger Um) or accept lower efficiency |
| TURB-2 | stage loading psi minimum | min | 1.2 |  | below ~1.2 the annulus becomes very short |  |
| TURB-3 | rotor-exit hub/tip ratio | min | 0.55 |  | practice 0.6-0.85 for a single stage | too long blades: raise psi target or rpm |
| TURB-4 | rotor-exit hub/tip ratio upper | max | 0.88 |  | very short blades: clearance losses |  |
| TURB-5 | blade root stress at MCS x margin vs allowable | max | 436 | MPa | IN713LC min(yield, creep) at 1030 K; margin 1.25 | lower rpm, shorter blades (higher psi/hub-tip), stronger material or lower T04 |
| TURB-6 | rotor metal temperature vs material limit | max | 1223 | K | IN713LC T_max |  |
| TURB-7 | NGV metal temperature vs material limit | max | 1223 | K | IN713LC T_max | NGV sees T04 directly; use a higher-temperature alloy or lower T04 |
| TURB-8 | NGV exit Mach | max | 1.05 |  | subsonic/transonic NGV practice |  |
| TURB-9 | rotor exit absolute Mach | max | 0.6 |  | jet-pipe entry Mach; boomsonic R7.1 annulus cap |  |
| TURB-10 | estimated vs assumed turbine efficiency |diff| | max | 0.03 |  | consistency: run `jet converge` | estimate 0.875 vs cycle assumption 0.873 |
| TURB-11 | AN2 (rotor annulus x rpm^2) at MCS | max | 4.5e+07 | m2rpm2 | uncooled cast wheels: JetCat/AMT class 2-3.5e7, ceiling ~4.5e7 m2 rpm2 |  |
| TURB-12 | turbine tip diameter (info) | info | - | mm | - |  |

## combustor

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| COMB-1 | reference velocity | max | 25 | m/s | Lefebvre: annular 15-25 m/s; micro practice ~20 | casing annulus too small: raise diffuser radius ratio or shrink the tunnel |
| COMB-2 | reference velocity minimum | min | 12 | m/s | low U_ref wastes volume |  |
| COMB-3 | liner residence time | min | 2.5 | ms | vaporiser combustors 4-7 ms (JetCat/AMT class) |  |
| COMB-4 | liner length / height | max | 3.6 |  | practice 2.5-3.5 (Lefebvre) | long liner: raise U_ref or liner height |
| COMB-5 | liner metal temperature margin (T04 vs liner T_max; film-cooled liners run cooler) | max | 1403 | K | IN625 T_max + 150 K film credit |  |
| COMB-6 | heat release rate | max | 300 | MW/m3bar | large annular 20-60, micro-turbojet vaporiser combustors up to ~300 MW/(m3 bar) | raise residence time or liner volume |
| COMB-7 | air split sums to 1 | max | 1 |  | input check |  |
| COMB-8 | vaporiser fuel loading | max | 12 | kg/h | practice 3-12 kg/h per tube | more vaporisers |

## layout

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| LAY-1 | engine outer diameter vs limit | max | - | mm | requirements.max_diameter_mm |  |
| LAY-2 | engine length vs limit | max | - | mm | requirements.max_length_mm |  |
| LAY-3 | bearing span / D2 (rotordynamic sanity) | max | 2.2 |  | long spans lower the bending critical; boomsonic_v0 1.43 | shorten the combustor (higher U_ref / residence) or move the rear bearing aft |
| LAY-4 | tail cone shorter than nozzle | max | 0.1193 |  | geometry |  |

## rotor

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| ROT-1 | bearing DN at MCS vs rating | max | 1.5e+06 | mm.rpm | 71902C-HC catalogue DN limit | larger-DN (hybrid, oil-air) bearing, smaller journal, or lower rpm |
| ROT-2 | bearing temperature rating | max | 523 | K | 71902C-HC T_max |  |
| ROT-3 | first bending critical / MCS | min | 1.25 |  | API 684 separation margin practice (25 %) | stiffer/larger tube, shorter span, lighter overhung wheels |
| ROT-4 | rigid-body criticals below 60 % speed (soft mount) | max | 0.6 |  | traverse rigid modes below idle-to-cruise band | stiffer mounts move rigid modes up; keep them below idle or add damping |
| ROT-5 | journal torsional stress | max | 175.3 | MPa | AISI4340 0.577 Fty / SF 3 |  |
| ROT-6 | tube torsional stress | max | 175.3 | MPa | AISI4340 0.577 Fty / SF 3 |  |
| ROT-7 | shaft tunnel fits inside combustor inner casing | max | 0.03818 | m | layout: tunnel OD + 3 mm gap | smaller tube or larger combustor inner radius |
| ROT-8 | bearing L10 life (info) | info | - | h | ISO 281 basic rating (no thermal factors) |  |

## mechanical

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| MECH-1 | impeller disc peak stress at MCS vs yield | max | 267 | MPa | Al2618-T61 min-basis yield at 441 K; k_peak 1.6 | lower U2 (OPR/backsweep), boreless mount, or a stronger material |
| MECH-2 | impeller burst speed ratio | min | 1.2 |  | 14 CFR 33.27 style; Robinson k 0.85 | reduce average tangential stress: thicker hub, lower U2 |
| MECH-3 | inducer root radial stress vs yield | max | 267 | MPa | Al2618-T61 yield |  |
| MECH-4 | exducer root stress (from compressor stage, sized to limit) vs allowable | max | 243.6 | MPa | compressor.COMP-3 |  |
| MECH-5 | turbine disc peak stress vs bore allowable | max | 630.8 | MPa | IN713LC allowable at bore 750 K | thicker web/hub, lower rpm |
| MECH-6 | turbine disc average stress vs rim creep allowable | max | 615.9 | MPa | IN713LC allowable at rim 950 K |  |
| MECH-7 | turbine burst speed ratio | min | 1.2 |  | 14 CFR 33.27 style; Robinson k 0.85 |  |
| MECH-8 | turbine blade root (from turbine stage) | max | 436 | MPa | turbine.TURB-5 (no margin factor here) |  |
| MECH-9 | impeller clamp load retained hot | min | 1.435e+04 | N | tie-shaft preload minus thermal relaxation and gas load >= 20 % of preload | higher preload, longer tie shaft, or a matched-expansion sleeve |

## geometry

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| GEO-1 | dry mass estimate vs limit | max | - | kg | requirements.max_mass_kg |  |
| GEO-2 | thrust/weight (info) | info | - | - | - |  |
| GEO-3 | flange screws count (info) | info | - |  | ISO 4762 M2 |  |
