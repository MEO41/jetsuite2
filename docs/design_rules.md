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
| SPD-2 | design rpm vs turbine AN2 limit | max | 8.52e+04 | rpm | AN2 with IN713LC allowable 436 MPa at 1030 K, margin 1.25 | lower rpm, stronger turbine material, or lower T04 |
| SPD-2b | design rpm vs turbine disc bore-stress limit | max | 7.494e+04 | rpm | bored IN713LC wheel, allowable 631 MPa at 750 K, k_peak 1.3 | lower rpm, smaller hub/tip target, boreless wheel or stronger material |
| SPD-3 | design rpm vs bearing DN limit | max | 8.095e+04 | rpm | bearing 71902C-HC DN 1.5e+06 x 0.85 | smaller journal (if torque allows), hybrid bearing, or lower rpm |
| SPD-4 | impeller tip speed allowed by material (info: set by work, see COMP-3) | info | - | m/s | Ti-6Al-4V yield at Tt3 |  |

## compressor

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| COMP-1 | inducer shroud relative Mach | max | 1.3 |  | fielded micro-turbojet band (boomsonic A3R.1) | reduce rpm or raise hub/tip ratio |
| COMP-2 | impeller tip speed U2 | max | 620 | m/s | Ti impellers ~550-600 m/s, Al ~450-500 (Dixon; Rodgers) | lower OPR, less backsweep, more blades, or accept a stronger material |
| COMP-3 | exducer root stress at MCS vs allowable (root sized to the limit) | max | 602.6 | MPa | Ti-6Al-4V yield at 461 K / SF 1.0 | root thickness capped at 20 mm: reduce U2 or backsweep, or change material |
| COMP-4 | impeller material temperature (Tt3) | max | 673 | K | Ti-6Al-4V T_max | compressor exit too hot for this material: lower OPR or change material |
| COMP-5 | exit width ratio b2/D2 | min | 0.03 |  | narrow exits lose efficiency (Rodgers): b2/D2 >= 0.03 | raise phi2 or backsweep, or lower rpm |
| COMP-6 | relative diffusion ratio W1s/W2 | max | 2 |  | Dixon & Hall / Rodgers: W1s/W2 <= ~1.8-2.0 for attached flow | raise phi2 (wider exit), more backsweep, or reduce inducer Mach |
| COMP-7 | inducer throat choke margin at design | min | 0.1 |  | Rodgers: design at <= 90 % of throat choke flow (boomsonic A3R.5) | thinner LE, fewer main blades, larger hub/tip or lower inducer relative Mach |
| COMP-7b | inducer throat not choked at design | min | 0 |  | throat mass-flow function | the inducer throat is choked: lower rpm / relative Mach or open the throat |
| COMP-8 | radius ratio r2/r1s | min | 1.3 |  | Aungier: 1.4-2.2 for a radial impeller | rpm too high for the required work: reduce rpm |
| COMP-9 | radius ratio r2/r1s upper | max | 2.3 |  | Aungier: 1.4-2.2 for a radial impeller | rpm too low: raise rpm or hub/tip ratio |
| COMP-10 | impeller exit absolute Mach | max | 1.1 |  | vaned diffuser LE tolerates ~M 1.1 (Japikse) |  |
| COMP-11 | diffuser inlet flow angle from radial | max | 78 |  | vaneless stability: alpha < ~78 deg (Senoo) | more backsweep or higher phi2 to reduce swirl |
| COMP-12 | estimated vs assumed stage efficiency |diff| | max | 0.03 |  | consistency: run `jet converge` | estimate 0.807 vs cycle assumption 0.805 |
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
| ROT-7 | shaft tunnel fits inside combustor inner casing | max | 0.03821 | m | layout: tunnel OD + 3 mm gap | smaller tube or larger combustor inner radius |
| ROT-8 | bearing L10 life (info) | info | - | h | ISO 281 basic rating (no thermal factors) |  |

## mechanical

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| MECH-1 | impeller disc peak stress at MCS vs yield | max | 617 | MPa | Ti-6Al-4V min-basis yield at 441 K; k_peak 1.6 | lower U2 (OPR/backsweep), boreless mount, or a stronger material |
| MECH-2 | impeller burst speed ratio | min | 1.2 |  | 14 CFR 33.27 style; Robinson k 0.85 | reduce average tangential stress: thicker hub, lower U2 |
| MECH-3 | inducer root radial stress vs yield | max | 617 | MPa | Ti-6Al-4V yield |  |
| MECH-4 | exducer root stress (from compressor stage, sized to limit) vs allowable | max | 602.6 | MPa | compressor.COMP-3 |  |
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

## assess

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| ASS-1 | compressor quality score (mean of items) | min | 0.75 |  | assessment items AQ-C* | AQ-C5 slip factor disagreement between methods (max-min) = 0.0563; AQ-C12 inducer incidence range along the running line (max - min) = 17.5; AQ-C2 specific diameter Ds = 2.99; AQ-C4 L1 efficiency estimate vs Balje achievable band = -0.0493 |
| ASS-2 | diffuser quality score | min | 0.75 |  | AQ-D* |  |
| ASS-3 | turbine quality score | min | 0.75 |  | AQ-T* | AQ-T6 hub reaction (free vortex) = -0.0241 |

## combustor1d

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| C1D-1 | primary-zone equivalence ratio | max | 1.4 |  | Lefebvre: primary zone phi 0.8-1.4 for vaporiser combustors | more primary air (holes/dome) |
| C1D-1b | primary-zone equivalence ratio minimum | min | 0.8 |  | Lefebvre: phi_pz >= 0.8 for stability |  |
| C1D-2 | primary-zone Damkohler number (residence/chemical) | min | 5 |  | Da >> 1 required for stable combustion (global kinetics; order of magnitude) |  |
| C1D-3 | combustion efficiency (Lefebvre theta correlation) | min | 0.98 |  | theta correlation calibrated on the fleet (+/-2 pts) | larger liner volume, higher P3, or better mixing |
| C1D-4 | lean blow-out margin at design (phi_pz / phi_LBO) | min | 1.5 |  | Lefebvre stability loop | richer primary zone or larger primary volume |
| C1D-5 | lean blow-out margin at idle | min | 1.2 |  | Lefebvre stability loop at the idle point | raise idle speed or the deceleration fuel floor |
| C1D-6 | pattern factor into the turbine | max | 0.3 |  | Lefebvre: PF 0.2-0.35 for short annular liners | peak NGV inlet temperature ~1336 K |
| C1D-7 | liner wall temperature vs material limit | max | 1253 | K | IN625 T_max; radiation/convection/film balance | more film cooling, thermal barrier coating or IN625 -> Haynes 230 |
| C1D-8 | altitude relight index (phi_LBO windmilling / phi_LBO design) | max | 2.5 |  | Lefebvre loading at 6000 m, N 0.12 | relight needs a rich start schedule or a lower relight altitude |

## maps

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| MAP-1 | design-point surge margin (loss-model map, SAE definition) | min | 0.15 |  | stall indicators in perf.closs; uncertainty +/-30 % of the margin | more backsweep, larger vaneless gap, fewer / lower-solidity diffuser vanes, or a lower running line |
| MAP-2 | design-point choke margin (flow to choke / design flow - 1) | min | 0.08 |  | inducer / diffuser throat choke on the design speed line | open the inducer or diffuser throat |
| MAP-3 | L2 loss-model compressor efficiency vs L1 estimate |diff| | max | 0.04 |  | consistency between fidelity tiers | L2 0.838 vs L1 0.807: consider `jet ingest` of the L2 value or check inputs |
| MAP-4 | L2 loss-model turbine efficiency vs L1 estimate |diff| | max | 0.05 |  | consistency between fidelity tiers | L2 0.837 vs L1 0.875 |
| MAP-5 | design-point vaned-diffuser incidence | max | 4 |  | vane stall onset ~ +4-6 deg (Japikse) |  |
| MAP-6 | compressor loss-model PR at design vs cycle OPR |diff|/OPR | max | 0.06 |  | the sized geometry should deliver the cycle pressure ratio within the loss-model accuracy | loss model PR 4.318 vs cycle OPR 4.000 |

## offdesign

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| OD-1 | minimum surge margin along the running line | min | 0.1 |  | SAE margin from the L2 map at N 0.40; surge line uncertainty +/-30 % | lower the running line (larger nozzle), more backsweep, or a bleed / variable geometry |
| OD-2 | max-thrust point recovers the design thrust | min | 0.95 |  | map-based matching vs design-point cycle (consistency) | max thrust 513 N vs design 500 N (T04-limited) |
| OD-3 | idle speed fraction | min | 0.35 |  | micro-turbojet idle 30-40 % (JetCat 33-35 %) |  |
| OD-4 | idle surge margin | min | 0.08 |  | low-speed operability (boomsonic_v0 risk 4.2) |  |

## envelope

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| ENV-1 | fraction of envelope grid points cleared (converged, SM >= floor) | min | 0.9 |  | SM floor 0.08; L2 maps | see the envelope table for the failing corners |
| ENV-2 | worst-case surge margin over the envelope | min | 0.08 |  | at alt 9000.0 m, M 0.8, dT 0.0 K | hot-day / high-Mach corners load the compressor: consider a variable nozzle or bleed |
| ENV-3 | sea-level static max thrust vs design thrust | min | 0.95 |  | envelope max-power point at SLS (T04- or N-limited) |  |

## transient

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| TRN-1 | start reaches idle | min | 1 |  | start sequence simulation | more starter torque, earlier light-off or richer start schedule |
| TRN-2 | start light-off to self-sustain time | max | 8 | s | micro-turbojet practice 3-8 s |  |
| TRN-3 | slam acceleration idle -> 95 % time | max | 6 | s | class practice 3-6 s (JetCat ~4 s) | raise the accel limiter (watch SM) |
| TRN-4 | minimum surge margin during the slam acceleration | min | 0.05 |  | transient excursion toward surge; surge line uncertainty +/-30 % | lower accel_limit or add bleed |
| TRN-5 | T04 peak during acceleration vs limit | max | 1200 | K | over-temperature limiter (the limiter holds the peak at the limit) |  |
| TRN-6 | deceleration 100 % -> idle time | max | 8 | s | class practice |  |
| TRN-7 | hot start T04 peak (schedule x1.5) | max | 1300 | K | abnormal case: rich start |  |
| TRN-8 | hung start with half starter torque avoided | min | 1 |  | abnormal case | starter torque margin is thin |
| TRN-9 | overspeed on governor failure (peak N / design) | max | 1.15 |  | burst margin 1.2 x MCS must cover the overspeed reached before the fuel cut |  |

## life

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| LIFE-1 | turbine blade creep life over the mission / scatter | min | 50 | h | Larson-Miller from the IN713LC creep table (C 20.0), Robinson damage | lower T04 or rpm, or MAR-M247 |
| LIFE-2 | turbine disc rim creep life / scatter | min | 50 | h | as LIFE-1 |  |
| LIFE-3 | impeller bore LCF cycles / scatter | min | 500 |  | Manson universal slopes, Ti-6Al-4V | lower bore stress: boreless hub or lower U2 |
| LIFE-4 | turbine bore LCF cycles incl. start thermal stress / scatter | min | 500 |  | Manson universal slopes, IN713LC; thermal dT_max 293 K | slower start, thicker hub, or boreless wheel |
| LIFE-5 | bearing L10 life (ISO 281, lubrication/temperature factors) | min | 200 | h | 71902C-HC C 4.0 kN, P_eq 358 N, oil-mist |  |
| LIFE-6 | bearing DN with the lubrication method | min | 1 |  | catalogue DN x lubrication factor | grease halves the DN rating: use oil-mist / oil-air |
| LIFE-7 | casing wall vs containment thickness (1/3 disc fragment at burst) | min | 7.261 | mm | energy balance, AISI321 UTS at 700 K, k 3 (conceptual) | a containment ring around the turbine plane is the usual answer |

## rotordyn

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| RD-1 | first forward bending critical / MCS (nominal support) | min | 1.25 |  | API 684 separation margin | see the critical-speed map for the stiffness that helps |
| RD-2 | max synchronous vibration amplitude at G2.5 residual unbalance | max | 25 | um | ISO 1940 G2.5; 25 um pk at the wheels is a common limit for tip clearance/seal rub | better balance grade, more support damping, or move the criticals |
| RD-3 | amplification factor at the first response peak | max | 8 |  | API 684: AF < 8 for a well-damped critical | add squeeze-film / O-ring damping |
| RD-4 | blade resonance crossings within the operating range | max | 0 |  | Campbell: exducer vs diffuser vane passing, turbine blade vs NGV passing |  |
| RD-5 | blade resonance within +/-10 % of the design speed | max | 0 |  | no crossing at the dwell speed | change the vane/NGV count |
| RD-6 | max bearing dynamic load at G2.5 / static capacity C0 | max | 0.1 |  | dynamic load should stay a small fraction of C0 |  |

## manufacturing

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| MFG-1 | impeller tip clearance remaining at worst-case stack-up | min | 0.05 | mm | tolerance chain (worst case) | tighten the axial chain or open the nominal clearance |
| MFG-2 | turbine tip clearance remaining at worst-case stack-up | min | 0.05 | mm | tolerance chain incl. thermal growth |  |
| MFG-3 | impeller efficiency scatter from clearance tolerance (RSS) | max | 0.01 |  | 0.3 x d(clr)/b2 |  |
| MFG-4 | balancing: required residual per plane vs achievable | min | 0.05 | g mm | ISO 21940 G2.5 at 72500 rpm: 0.306 g mm per plane | a finer balancer or a lower grade is needed |
| MFG-5 | minimum impeller passage width vs cutter | min | 3 | mm | 5-axis cutter access | fewer blades / splitters or a smaller cutter (deflection!) |
| MFG-6 | impeller blade wrap / pitch (axial-view overlap) | max | 1.6 |  | flank-milling reach |  |
| MFG-7 | impeller features flagged | max | 0 |  | machinability screen |  |
| MFG-8 | turbine casting features flagged | max | 0 |  | investment-casting screen |  |
| MFG-9 | exducer root stress vs process-adjusted allowable | max | 602.6 | MPa | billet-5axis: allowable x 1.0 (root sized to the limit) |  |
| MFG-10 | turbine root stress vs process-adjusted allowable | max | 370.6 | MPa | investment-cast: allowable x 0.85 |  |

## testbench

| id | rule | kind | limit | unit | source | remedy |
|---|---|---|---|---|---|---|
| TB-1 | virtual run completed without abort | max | 0 |  | abort criteria |  |
| TB-2 | max thrust reached on the bench vs design | min | 0.95 |  | throttle step to 100 % |  |
