# Validation

`jet validate [compressor|turbine|fleet|all]` runs every analysis method against the
validation database and prints model vs reference with the error and the tolerance.
No method ships unvalidated; the errors are what the UQ study uses as model-form bands.

## Data

| source | what | fidelity of the reference |
|---|---|---|
| `validation/data/boomsonic_v0_maps.json` | TurboFlow 0.1.18 (Oh loss set, Wiesner slip) design point and full maps (12 speed lines, ~230 points) of the v0 impeller at 0/10/15/20 deg backsweep; the JetCat P400-PRO-LN datasheet point run through TurboFlow; TurboFlow (Benner losses) turbine map (10 speed lines, 212 points); the NASA turbo-design cross-check | independent code, same method class |
| `validation/data/microturbojet_database.csv` | 26 datasheets, JetCat / AMT / KingTech / others: thrust, rpm, PR, mass flow, EGT, fuel, mass, size | measured engine data (manufacturer) |
| in-code literature cases | Eckardt impeller O (radial, 400 mm), NASA CC3 (4.54 kg/s, 21 789 rpm, 50 deg backsweep, vaned), NASA HECC (measured 8.4 % surge margin, vaned) | published rig data, approximate geometry transcribed |

## Results (2026-09-16)

Compressor mean-line loss model (`perf/closs.py`):

| case | quantity | model | reference | error | tolerance |
|---|---|---|---|---|---|
| v0 impeller design point vs TurboFlow | PR_tt | 4.19 | 4.01 | +4.6 % | 6 % |
| v0 impeller design point vs TurboFlow | eta_tt | 0.830 | 0.818 | +1.3 pts | 4 pts |
| speed line N = 1.0 (6 pts) | PR rms | | | 4.2 % | 5 % |
| speed line N = 1.0 | eta rms | | | 0.9 pts | 4 pts |
| speed line N = 0.8 | PR / eta rms | | | 1.1 % / 0.4 pts | |
| speed line N = 0.6 | PR / eta rms | | | 2.1 % / 3.4 pts | |
| Eckardt O | PR / eta | 2.04 / 0.862 | 2.10 / 0.88 | -2.7 % / -1.8 pts | 6 % / 4 pts |
| NASA CC3 (approx. geometry) | PR / eta | see `jet validate` | 4.0 / 0.84 | | 8 % / 5 pts |

Known deviations: the vaned-diffuser throat model differs from TurboFlow's (throat sized
for M 0.70 at design here), so the choke side of the low-speed lines ends 10-25 % earlier;
the surge side is a stall-indicator prediction (inducer incidence vs relative Mach, Coppage
diffusion factor, vaned-diffuser incidence vs inlet Mach, vaneless-space swirl angle) that
TurboFlow does not have.  Its calibration is below.

### Surge line calibration (rig data, `jet validate rigs`, 2026-09-16)

Cases: NASA HECC (CR-2014-218114, sourced geometry and measured vaned map, 100 % speed
line), NASA CC3 vaned (Skoch 2003 / McKain-Holbrook geometry; the vane leading-edge angle is
not published and is *assumed* equal to the HECC design incidence), NASA CC3 vaneless
(stable to 0.72 of design flow; must produce no false stall flag).  Data in
`validation/data/rigs.json` and `validation/data/hecc/`.

Model: vaned-diffuser stall incidence ``i_stall = 6.0 - 22.19 (M3 - 0.5)`` deg (slope fitted
on the HECC surge point, intercept from Japikse/Senoo practice), vaneless rotating-stall angle
``alpha_c = 87 - 70 b3/r3 - 5 max(M3 - 0.6, 0)`` deg applied only for radius ratio >= 1.30
(Senoo-Kinoshita), inducer incidence limit 14 -> 6 deg with the shroud relative Mach.

| case | quantity | model | measured | residual | inside band |
|---|---|---|---|---|---|
| HECC 100 % | PR at design | +0.7 % | 4.685 | | yes |
| | eta at design | +0.4 pts | 0.822 | | yes |
| | surge flow / design flow | -0.7 % | 0.951 | fitted | yes |
| | choke flow | +4.0 % | 5.239 kg/s | | yes |
| CC3 vaned | PR_ts at design | +5.5 % | 3.93 | | yes (8 %) |
| | surge flow / design flow | -5.8 % | 0.939 | assumed vane LE dominates | yes |
| | choke flow | -2.5 % | 4.695 kg/s | | yes |
| CC3 vaneless | false stall flags on the measured stable range | 0 | 0 | | yes |

Band: rss(max surge-flow residual 5.8 %, 1 % map read-off) x 1.3 = **+/-0.077 surge-margin
points, absolute**, stored in `validation/data/surge_calibration.json` and loaded by
`perf/closs.py` (`SURGE_BAND_SM`).  Every SM rule note quotes it.  The band is narrower
than the old +/-30 % relative band only for margins above ~0.26; for the low-speed margins
that matter on p500 it is *wider*, which is the honest state: the CC3 vane angle is the
dominant unknown and only a measured map (roadmap 2) will shrink it.  IGV pre-swirl maps
use the same loss model with the inducer incidence reduced by the pre-swirl; no rig case
with IGVs exists, so IGV results are L2 extrapolations and are labelled as such.

### Part-speed matching model changes (2026-09-16, work package A)

Diagnosing the hot-start T04 limiter showed the transient model could not represent the start region at all:
below ~40 % speed the quasi-steady flow-compatibility problem had no solution, the integrator held a stale
state for hundreds of steps while the fuel ratio wound up, and the limiter was acting on a held (fake)
temperature.  Four model corrections, all physics rather than tuning:

| change | before | after | effect |
|---|---|---|---|
| burner / jet-pipe pressure loss | fixed fraction (5 % / 2 %) at every speed | scales with dynamic head, dP/P = k (W sqrt(T)/P)^2 (Walsh & Fletcher), capped at 1.5x design | the low-speed running line drops: p500 idle SM -0.089 -> +0.043 (fixed geometry); design point unchanged |
| turbine PR floor in `evaluate` | 1.05 | 1.001 | start-region solutions with PR_t 1.01-1.05 become reachable |
| nozzle continuity residual | area form with a 1 m/s velocity floor (residual ~100 near PR 1) | mass-flow capacity form, well scaled | the 2-unknown solve converges from 15 % speed |
| turbine map below the lowest mapped PR | clamped to the lowest tabulated flow | orifice-like extrapolation W ~ sqrt((PR-1)/(PR_min-1)) toward zero at PR 1 | consistent with the PR floor |

Plus solver changes: the T04 topping limiter is now a fuel ceiling on the command every step (with anti-windup while
the model holds), and the fixed-T04 solve has a residual scan fallback used only for the ceiling.  The hot-start
peak on the scheduled p500 went from 1650 K (limiter lost authority) to exactly the 1200 K limit; regression test
`test_hot_start_T04_limiter_holds_at_low_speed`.  Residual model gap: the fixed-geometry start still holds the state
below ~15 % speed (no solution there), and the "unlimited" T04 a rich start can reach is bounded by where the
fuel-driven solve converges (~1220 K on the test fixture), so the limiter test uses a 1100 K limit.

The part-speed dP scaling omits the fundamental (heat-addition) loss, ~0.5-1 % at design, which does not scale with
dynamic head; the running-line shift it causes is second order (< 0.01 SM) and is listed as a known deviation.

### Surge-margin uncertainty terms (work packages C / D, `uncertainty.py`)

| term | value | status | applies |
|---|---|---|---|
| rig | 0.077 SM points | derived (HECC / CC3 residuals) | always |
| IGV extrapolation | 0.5 x credited pre-swirl SM benefit at the point | declared fraction; no rig case with IGVs exists | IGV scheduled at the point |
| low-speed similarity extension | 0.03 | declared | below the lowest mapped speed line |
| transient quasi-steady model form | 0.03 | declared, pending test data | transient trajectories |

Combination: root-sum-square (independent sources, no known-sign bias).  Every surge-margin rule (MAP-1, OD-1, OD-4,
ENV-2, TRN-4) carries value, band, terms, value - band and the with-band verdict; the report prints the arithmetic.

### Turbine disc FE (work package E, `fea/disc.py`, CalculiX 2.21 in WSL)

Axisymmetric CAX4 model of the wheel profile (structured raster, 0.5 mm cells), centrifugal load, blade-row pull on
the rim, lumped rim/bore start temperature field at the instant of maximum rim-bore difference.  Mesh convergence on
p500: the area-mean hoop stress equals the L1 disc-mass value (398 MPa vs 399 MPa, a check on the mass and load
path); the peak away from the unfilleted re-entrant corners converges (956 / 967 / 973 MPa at 0.8 / 0.5 / 0.35 mm
cells) while the corner value diverges (1030 / 1285 / 1923 MPa: singular, needs a fillet radius in the profile before
it means anything).  The ingested L3 values are the away-from-corner peaks.  Finding: the profile as drawn carries a
15 mm through-bore (the shaft passes through the wheel) while the L1 stress factor assumed a boreless disc (k 1.3);
the L3 peak is 967 MPa vs the 518 MPa L1 estimate, above the 631 MPa bore allowable, and the LCF life with the start
gradient superposed drops from 153 to 14 cycles.  A boreless what-if (`jet fe disc --variant boreless`) gives
675 MPa centrifugal / 899 MPa combined: better, still not admissible.

### Impeller hub FE (`jet fe impeller`, `jet l3`, 2026-09-17)

Same axisymmetric CalculiX model as the disc, on the impeller hub profile with the blade row smeared as a
centrifugal traction on the gas-path hub surface and the steady eye-to-exit temperature field (Tt2 + 20 K to
T02, linear in x).  Mean hoop stress 258 MPa vs the L1 disc-mass value 253 MPa (load path check).  Peak 700 MPa
cold / 739 MPa with the field, at the bore under the back face (r 7.8 mm, x 53.7 mm), not at a re-entrant
corner; the L1 factor (k_peak 1.6 for a bored disc) gave 405 MPa.  Blade-root stress is not resolved (blades
are a smeared load), so COMP-3 / MECH-4 keep the strip-theory value.  `jet l3` chains impeller + disc FE,
ingest, core + life re-run and a before/after delta (`analysis/l3_delta.md`) in ~26 s.

### Secondary air and thermal network (`jet analyze thermal`, section 6, 2026-09-17)

L1 correlations with no rig datum yet: Martin labyrinth flow, free-disc windage moment (Cm = 0.0622 Re^-0.2),
Owen & Rogers rotating-disc heat transfer (Nu = 0.0197 Re^0.8), flat-plate platform convection, Palmgren bearing
friction.  Nine-node steady network solved by Gauss-Seidel.  Declared band +/-40 K on every predicted metal
temperature; the rim-purge ingestion minimum (0.5 % of gas-path flow) is declared.  p500: leakage 1.0 % of core
flow, cavity air 611 / 681 K, rim 1040 K, web 853 K, bore 791 K, shaft 600 K, bearings 355-360 K, ~200 W friction
heat per bearing, 0.02 l/h oil at 40 K rise.  The rim prediction is 90 K above the mechanical-stage assumption
(950 K): THM-8 reports it and the life stage now uses the prediction.

### Impeller through-flow (`jet analyze throughflow`, section 7, 2026-09-17)

Blade-aligned quasi-3D analysis on the CAD's own meridional channel and camber law (the angle law is asserted
identical in the tests).  Meridional velocity profile from the streamline-curvature normal-equilibrium term
and continuity with blade + boundary-layer blockage; rothalpy-conserving relative-frame thermodynamics with a
polytropic loss; Stanitz blade-to-blade loading.  No validation case yet (no measured blade-surface velocities
for a micro impeller are available); the checks it feeds are the Dean deceleration limit (1.6), the Aungier loading
band (0.7-1.0) and the incidence-spread practice, and the velocity band is declared +/-10 %.  Consistency checks
on p500: exit Cm within 8 % of the mean-line Cm2, exit swirl 4 % below the mean-line slip value (the deviation
law grows toward the TE), the streamline mass flow closes to 0.1 %.

### Speed changes that touch numerics (section 8, 2026-09-17)

`gas_fast` scalar lookups are a bilinear interpolation on the same 1 K / 0.01 FAR tables as before (unit test
against the exact polynomials unchanged, < 200 J/kg).  The transient integrator skips the T04-ceiling solve when
the previous converged point is more than 15 % below the limit and the command is off the accel line: with a
0.3 s fuel lag and a 0.05 s step the temperature cannot cross that gap in one step, and the hot-start regression
test (limit 1100 K, rich start) still holds the peak at the limit.  Results of every stage on p500 are unchanged to
the printed precision by these changes (forced re-run diffs: 0 values changed in maps, envelope, thermal, life,
rotordyn, manufacturing; transient / bench differences are the process-pool scenario ordering only).

### Impeller passage CFD (`jet cfd`, ROADMAP section 5, 2026-09-17)

**Set-up.**  SU2 8.5.0 (win64 binaries in `tools/su2/bin`), single passage of the p500_sched impeller (8 main + 8
splitter blades, 45 deg pitch) on a structured two-block H-mesh written directly in SU2 format by `cfd/hmesh.py`
(Euler check: 45,584 hexahedra, 50,623 nodes; RANS: 71,632 hexahedra with the blade first cell at 0.020 mm; periodic pair
node-matched to 1e-11 m, hub and shroud first cell 0.25 mm, no tip clearance, shroud attached to the frame, straight inlet extension 0.6 r1s upstream, vaneless extension
to 1.12 r2).  Rotating frame about -x (the CAD camber wraps in +theta along the flow), inlet total conditions, static-
pressure outlet, Roe / MUSCL / Venkatakrishnan, implicit Euler at CFL 2 (final block adaptive 1-5), SST for the RANS
run.  The solve starts from a streamline-aligned initial field written with the mesh (`passage_init.csv`): meridional
velocity from continuity, relative velocity along the blade camber, absolute swirl rising to the mean-line work
coefficient at the trailing edge, free vortex downstream, static pressure ramped to the outlet value.  The operating
point is found by throttle continuation: blocks of 240 iterations at a fixed outlet pressure, a block is healthy when
inlet and outlet mass flow are within 25 % of each other and within 0.3-2 x the design passage flow, unhealthy blocks
continue at the same pressure (up to three), then a secant step (clamped to 8 %) moves the pressure towards the design
passage mass flow +/- 2 %; choke and collapse bracket the search.

**Verification chain** (Euler unless noted; every case run before the impeller was trusted):

| case | what it checks | result |
|---|---|---|
| straight duct, uniform start | mesh-writer conventions, inlet / outlet, config | mass 0.042 in / 0.046 out, T_t exit 288 K |
| annular 45 deg sector, periodic | cylindrical geometry + periodic pair | mass balanced, T_t exit 288 K |
| closed annulus, free vortex, periodic vs walls | vector transfer across the periodic pair | r C_theta preserved to 1.00 at every interior radius under periodicity, 0 under walls |
| closed annulus in solid-body rotation, plane walls | moving-wall + rotating-frame formulation | Roe and JST hold C_theta / (omega r) = 1.000, T = 288 K, residual -8; **AUSM+-up2 decays to 40 K at the walls and 320-2000 K mid-passage** (excluded) |
| rotating annulus, axial through-flow, 7592 rad/s | frame source terms with through-flow | T_t drift 1.7 K over 40 mm (0.6 %) |
| bladed passage, static, aligned start | blade topology (cusped LE / TE lines, shared splitter nodes) | residual -6.1, mass 0.036 / 0.039, T_t 285 K |
| impeller at 26 % speed (2000 rad/s), 110 kPa | full rotating bladed case, mild regime | residual -6.1, W 0.029 / 0.027 kg/s, T_t exit 297.6 K (+9.5 K), PR_tt 1.17 |
| impeller at design speed, Euler, p_out 312.6 kPa | design regime, transient length | after 720 iterations W 0.119 / 0.119 kg/s (design 0.108), T_t exit 474 K, PR_tt 6.0 (lossless, no clearance) |

**Failure modes met on the way, and their signatures** (kept because each one looks like a mesh defect and is not):
a uniform axial start field pulls fluid off the shroud face of the radial exit and the pressure outlet then feeds a
standing vortex (350 m/s inflow at the shroud / periodic corner, net flow zero, total temperature rising by compression
while the residual falls); a start with the swirl lagging the blades is a piston (pressure side to 1e5 K, suction side
cavitating, within 20 iterations); SU2's outlet pressure ramp acts only on the Giles / Riemann boundaries and there is
no compressible mass-flow outlet, so the operating point must be iterated; AUSM+-up2 in this build does not carry the
rotating-frame grid velocity (table above); and the draining transient of the design-speed passage needs about 600
iterations at CFL 2 before mass balance is reached, so blocks that restart from the initial field never converge; and SU2 8.5's adiabatic no-slip wall in the rotating frame runs away on the pressure sides only (wall nodes at 1300-3000 K at the inducer with the fluid one cell away at 290 K, suction-side wall nodes cooling to 214 K, the no-slip velocity honoured to 2 m/s on both; the same RANS case without rotation holds every wall between 276 and 296 K), which is the pressure work of the moving wall landing on the wall node of a node-centred scheme, where only conduction through the first cell can carry it away: isothermal walls change nothing (the energy condition is weak), reversing every boundary quad changes nothing, and a wall-resolved pitchwise spacing (first cell 0.020 mm instead of 0.35 mm, nk 22, tanh clustering 3.2) removes it (wall nodes 235-570 K, residual -6.3, T_t exit 298 K at 26 % speed).  The RANS mesh is therefore wall-resolved at the blades (71,632 hexahedra) with isothermal walls at the mean relative total temperature (386 K on p500_sched, heat-transfer error declared); the hub and shroud keep the 0.25 mm first cell.
The bladeless channel with a uniform start also converges to a spurious recirculation for the same outlet reason,
which is why the aligned initial field is written for every case.

**Status: no impeller number is ingested.**  On the wall-resolved RANS mesh at 26 % speed (converged: mass balance 1 %,
residual -6.8 after 1,600 iterations) the field does not close its energy balance: the total pressure ratio 1.165 needs at
least 12.9 K of total-temperature rise, the mass-weighted Euler work from the exit swirl is 12.1 K, and the field shows
10.1 K (JST from scratch: 8.8 K).  The design-speed RANS blocks show the same ratio (167 K of T_t rise for 215 K of Euler
work).  Isothermal walls make it worse for a different reason (they extract a fifth of the work as heat through the
resolved wall layer) and were reverted.  The reference case `validation/su2_rotating_wall_repro.py` (a plain duct rotating
at 7592 rad/s with walls that move normal to themselves, Roe) closes the same balances within about 10 % once converged
(11.7 / 13.1 / 12.1 K after 3,600 iterations) with its wall rows +/- 100 K off the interior, so the rotating-frame
formulation of this build is consistent only to that level on a plain mesh and worse on the twisted, cusped passage mesh;
SU2's source (v8.0 `BC_Sym_Plane` reflected state with grid velocity, `CNSSolver::AddDynamicGridResidualContribution`
with p v_wall.n and tau.v_wall.n) has the wall work terms, so this is discretisation accuracy, not a missing term.  An
efficiency from a field that misses 15-25 % of its work is uncertain by +/- 0.2 and is not an L3 value.  Until the
balances close (candidates: a finer, less skewed mesh with the Giles / mixing-plane turbomachinery boundary set, SU2 built
from source at a version whose turbomachinery test cases pass, or a cell-centred solver), `jet cfd` runs the whole
pipeline, reports the totals for information and writes nothing for ingest; the ingest is gated behind
`JET_SU2_ROTATING_WALLS_OK` and COMP-16 stays dormant.  The pipeline itself (mesh writer, initial field, throttle
continuation, post-processing, ingest path, COMP-16, tests) is complete and verified on every case in the table above.

### Paper correlation against commercial engines (ROADMAP section 2, `jet validate paper`, 2026-09-16)

Three published micro-turbojets modelled as if they were our designs: only thrust, OPR and max rpm from the
datasheet; T04 (not published) backed out from the published max EGT; cycle efficiencies converged onto the
loss models; everything else the suite's own sizing.  Data and sources in `validation/data/paper_engines.json`
(JetCat P300-PRO and P400-PRO-LN product pages; AMT Olympus HP datasheet June 2009).  The datasheet max point is
compared two ways: at the published rpm (how the datasheet defines it) and EGT-limited (how the ECU tops out).

| engine | quantity | model | datasheet | error | tolerance |
|---|---|---|---|---|---|
| P300-PRO @ 105 krpm | thrust / fuel / EGT / flow | 344 N / 44.1 kg/h / 1104 K / 0.553 kg/s | 300 / 47.0 / 1023 / 0.50 | +15 % / -6 % / +81 K / +11 % | 10 % / 15 % / 60 K / 15 % |
| P300-PRO EGT-limited max | thrust / fuel / flow | 297 N / 37.5 kg/h / 0.529 | 300 / 47.0 / 0.50 | -1 % / -20 % / +6 % | 10 / 15 / 15 % |
| P300-PRO idle 35 krpm | thrust / fuel | 15.0 N / 6.3 kg/h | 14 / 8.6 | +7 % / -27 % (below the map, similarity extension) | 10 / 15 % |
| Olympus HP @ 108.5 krpm | thrust / fuel / EGT / flow | 243 N / 29.6 kg/h / 1005 K / 0.429 | 230 / 38.4 / 973 / 0.45 | +6 % / -23 % / +32 K / -5 % | |
| Olympus HP idle 36 krpm | thrust | 11.4 N | 13 | -13 % | 10 % |
| P400-PRO-LN @ 98 krpm | thrust / fuel / EGT / flow | 533 N / 67.8 kg/h / 1166 K / 0.782 | 425 / 66.8 / 1023 / 0.67 | +25 % / +2 % / +143 K / +17 % | |
| P400-PRO-LN EGT-limited max | thrust / fuel / flow | 415 N / 51.4 kg/h / 0.723 | 425 / 66.8 / 0.67 | -2 % / -23 % / +8 % | |
| all three | diameter / length | -9 to -12 % / -7 to -28 % | | inside the (wide) bands | 12 / 20 % |
| all three | mass | +10 / +30 / +58 % | 2.85 / 4.01 / 2.73 kg | P300 outside | 30 % |

What it says, in order of importance:

1. **At the published rpm the suite's engines run hotter and stronger than the datasheets** (thrust +6 to +25 %,
   EGT +30 to +140 K, flow +11 to +17 %).  This is the MAP-6 inconsistency seen on p500: the loss-model map delivers
   ~7 % more pressure ratio at the design speed than the sized cycle assumed, so the matched running line at 100 %
   speed sits above the design point.  Converging the cycle efficiencies does not remove it (it is PR, not eta).
2. **EGT-limited, thrust is right (-1 %, -2 %) and airflow is close (+6 to +8 %), but fuel flow is 20-23 % low.**
   The real engines burn more fuel for the same thrust: TSFC ~0.157 kg/N h published vs ~0.125 here.  A two-point
   `jet correlate --calibrate` on the P300 with the five declared levers is under-determined (three levers run to
   their bounds); with only eta_c and eta_b free, eta_b goes to its lower bound (0.86) and the fit still leaves
   thrust +11 %.  So the gap is not combustion efficiency: it is the component efficiencies of the real engines
   (fleet 0.80-0.88 stage eta range) and the running-line position.  Treat the suite's TSFC as optimistic by
   ~20 % until the impeller CFD (section 5) or a rig gives a component datum.
3. **Idle** (30-35 % speed) is below the lowest mapped line and uses the similarity extension: thrust within
   +7 / -13 %, fuel 17-27 % low.  Consistent with the fixed-geometry start-region gap.
4. **Mass** is over-predicted (+10 to +58 %); the datasheets are bare-engine or hood-integrated masses, the suite's
   casing / combustor / housing sizing is conservative.  The suite's L0 mass model is the weakest number here.
5. Dimensions are 8-12 % small in diameter and short in length: the datasheet envelope includes the starter,
   accessories and nozzle extension.

The fleet database entry for the Olympus HP was corrected from PR 3.5 to 3.8 (datasheet).  The CC3 vaned-diffuser
leading-edge angle could not be recovered from any reachable source (NTRS, ResearchGate and MDPI pages blocked or
without the number); it stays an assumption and the dominant surge-band unknown.  The HECC vaned map in
`validation/data/hecc/map_vaned.csv` is measured rig data (CR-2014-218114) and already machine-readable, which
satisfies the "one measured map" item at rotorcraft scale, not micro scale.

Turbine mean-line model (`perf/tloss.py`, AMDC with Kacker-Okapuu scaling):

| case | quantity | model | reference | error | tolerance |
|---|---|---|---|---|---|
| v0 turbine design point vs TurboFlow | mass flow | 1.047 | 1.087 | -3.6 % | 6 % |
| | PR_tt | 1.973 | 1.961 | +0.6 % | 3 % |
| | eta_tt | 0.883 | 0.936 | -5.3 pts | 6 pts |
| speed lines N = 1.0 / 0.8 / 0.6 | mass flow rms | | | 4.1 / 5.5 / 6.7 % | 8 % |
| | eta rms | | | 5.2 / 9.0 / 11.5 pts | 12 pts |

AMDC/KO is pessimistic against Benner-type loss sets by 3-6 points at design and more at
part speed; TurboFlow's 0.936 for 25 mm blades with 0.3 mm clearance is itself optimistic
against the micro-turbine fleet (0.80-0.88).  The band between them is the model-form
uncertainty used for `cycle.eta_t` in the UQ defaults (+/-0.03).

Sizing chain (v2 regression, `tests/test_design_sweep.py`): the boomsonic_v0 frozen 500 N
design is reproduced within 3 % on airflow and 5 % on impeller / inducer radii and turbine
pressure ratio.  `jet validate fleet` runs the chain on every datasheet with thrust, PR, rpm
and mass flow and reports airflow (tolerance 15 %), diameter (25 %) and mass (50 %) errors.

Rotordynamics (`tests/test_rotordyn.py`): closed-form simply-supported beam (0.2 %), gyroscopic
forward/backward splitting, Jeffcott critical (3 %).

Gas model (`tests/test_gas.py`, `test_v3.py`): cp vs reference air data (< 0.4 %), tabulated
fast model vs exact polynomials (< 0.02 %).
