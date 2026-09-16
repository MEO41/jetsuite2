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
diffusion factor, vane incidence, vaneless swirl) that TurboFlow does not have.  The
measured HECC surge margin (8.4 %) is the only surge datum; the stall indicators carry a
stated +/-30 % uncertainty on the margin and should be treated as such until rig data exist.

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
