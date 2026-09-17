# CLAUDE.md — operating jetsuite2 (v3)

jetsuite2 designs, analyses and optimises a single-spool centrifugal micro-turbojet
(100–1000 N) from requirements to CAD, off-design/transient performance, life and a
test-ready package.  Operate it through the `jet` CLI (or `jetsuite2.api.Design`).

## Environment

One venv, Python 3.12, CadQuery 2.8, matplotlib: `.venv\Scripts\jet ...` (README).
Core chain ~0.4 s (never regress this); analyses are opt-in and cached; CAD 30–60 s.

## Workflow

1. `jet new <dir> --thrust N [--alt m --mach M] [--set stage.key=value]` — create + core run.
2. `jet rules -d <dir>` — verdicts with sources and remedies; `jet status` — fidelity tier,
   staleness and ingested overrides per stage.
3. `jet set -d <dir> stage.key=value --run` — change; the report says what re-ran and what moved.
   `jet converge` when COMP-12/TURB-10 flag efficiency inconsistency.
4. `jet analyze [names|all]` — opt-in analysis stages (see table).  Invalidated like every stage.  Stages
   of each dependency wave run concurrently in processes (`--workers N`, `--serial` to disable); the
   transient's start scenarios and the envelope grid use their own small pools (`transient.workers`,
   `envelope.workers`).  Off-design exports the steady schedule the transient and bench reuse.
5. `jet study sweep|doe|optimize|uq|sensitivity <name> --spec '{...}'` — design-space work on
   the fast chain, stored under `studies/`, flagged STALE when the design changes.
6. `jet export cfd compressor|turbine` / `jet export fea impeller|turbine` — L3 hand-off package;
   fill `ingest_template.json` with the solver results, then `jet ingest <file> --run`.
7. `jet correlate test.csv [--calibrate --apply]` — as-designed vs as-tested, auditable calibration.
8. `jet cad`, `jet report`, `jet readiness`, `jet validate` (`jet validate rigs` = HECC / CC3 surge calibration).
9. `jet plot map|turbine|all` — the layered compressor map (surge band, choke, efficiency islands,
   scheduled running line over the ghosted unscheduled one, transient trajectories, tier tags) as
   PNG + SVG + interactive HTML under `analysis/plots/`; plus turbine map, Smith/Balje, Campbell.
   Operability findings should be read from the map, not from tables.
11. `jet freeze --by <name> [--note]` signs off a hash-verifiable, immutable snapshot (`frozen/`);
    `jet freeze` alone shows the status, `--verify` recomputes the hashes.  `jet cad` and `jet export`
    refuse an unfrozen design unless `--unfrozen-ok`.  `jet compare A B [--out file.md]` diffs two
    designs or versions (`dir`, `dir@vNNNN`, `dir@frozen`): headline, inputs, rules, margins with
    bands, running lines, map overlay.
17. `jet drawings` writes dimensioned half-section drawings of the shaft, bearing housings and casing with ISO 286
    fits (bearing seats k5, bores H6, tunnel H7, ring and o-ring grooves) under `handoff/drawings/`.
    `jet cam impeller` writes the CAM package (suction / pressure surface grids as CSV, hub and shroud curves,
    STEP of hub, blade and the sharp impeller, `cam_spec.json` with the fillet radius and machining notes) and
    tries the root fillet on the fused solid; if OCC cannot fillet the wrapped blades the sharp solid is
    exported and the spec carries the fillet, which is how the CAM system applies it anyway.
16. `jet ecu` exports the controller the transients were run with: `schedules.csv` (steady Wf/P3, accel/decel
    lines, bleed, A8, IGV per corrected speed), `limits.json` (topping limits, overspeed trip, bearing abort
    from the thermal stage, sensor-loss fallbacks), `logic.md` (state machine, limiter arbitration, faults).
    The transient stage runs the fallbacks as scenarios (`p3_sensor_loss`, `egt_derate`, `igv_failed`;
    rules TRN-10..12).
15. `jet l3` is the §5 loop: impeller + disc CalculiX cases, ingest as L3, core + life re-run, and a
    before/after rule delta (`analysis/l3_delta.md`).  On p500 both wheels fail at L3 (impeller bore
    739 MPa vs 617 yield, disc 967 vs 631): findings F3 and F6, disc/hub geometry work.
18. `jet cfd [--euler] [--iters N] [--ingest]` runs the impeller passage in SU2 8.5 (structured H-mesh, rotating frame,
    streamline-aligned start, throttle continuation to the design passage flow) and reports PR / eta for information;
    the ingest of `eta_impeller_cfd` / `PR_cfd` (COMP-16) is gated behind `JET_SU2_ROTATING_WALLS_OK` because the
    bladed rotating solutions miss 15-25 % of their Euler work in the energy equation (docs/validation.md,
    `validation/su2_rotating_wall_repro.py`).  Do not quote an impeller CFD efficiency until that gate is lifted.
    Roe only (AUSM+-up2 breaks moving walls in the rotating frame), blade first cell 0.02 mm for RANS, adiabatic walls.
12. `jet fe disc [--ingest] [--variant boreless]` runs the turbine-disc axisymmetric CalculiX case
    (ccx native or via WSL) and, with `--ingest`, replaces the L1 disc stresses by the L3 result
    (mechanical and life re-run on it).  The corner peaks of an unfilleted profile are singular; the
    reported and ingested value is the converged peak >= 1 mm from the re-entrant corners.
14. `jet validate paper` models three commercial engines from their datasheets (T04 backed out from the
    published EGT) and reports the errors: at the published rpm the suite runs +6…+25 % thrust and hotter
    (MAP-6), EGT-limited thrust is within 2 %, fuel flow 20 % low, mass over-predicted.  Quote the suite's
    TSFC as optimistic by ~20 % until a component datum exists.  `jet rig compressor` writes the cold-flow
    compressor test article (drive, instrumentation, run matrix, ingest template) under `handoff/`.
13. Surge-margin rules carry a band made of named terms (rig 0.077 derived; IGV extrapolation, low-speed
    extension and transient model form declared) combined by RSS; the rule note and the report show the
    with-band arithmetic.  Never state "passes nominally" without the value - band line.
10. Control and variable geometry are design objects (`control` core stage): handling bleed,
    variable nozzle, IGV pre-swirl, accel/decel limit lines, idle governor, topping limiters and the
    start ramp.  `jet set control.bleed_enabled=true` etc.; every analysis stage runs *through* the
    schedules and reports the unscheduled line as a ghost for comparison.

| analysis stage | tier | what | typical time |
|---|---|---|---|
| maps | L2 | compressor/turbine maps from the mean-line loss models, surge/choke lines | 10–15 s |
| offdesign | L2 | running line, idle, max point, surge margin | 5–10 s |
| envelope | L2 | altitude/Mach/dT sweeps at max power | 1–3 min |
| transient | L2 | start, slam accel/decel, hot/hung start, overspeed, flameout | 1–3 min |
| assess | L1/L2 | component quality scores, slip disagreement, Balje, backsweep trade | ~10 s |
| combustor1d | L2 | zone network, blow-out, pattern factor, liner wall T, relight | < 1 s |
| life | L1 | creep (LMP), LCF, thermal transient, bearing L10, containment | < 1 s |
| rotordyn | L2 | Campbell, critical-speed map, unbalance response, blade resonances | 10–30 s |
| manufacturing | L1 | tolerance stack-up, balance grade, machinability, process, BOM | < 1 s |
| testbench | L2 | virtual test-cell run, log CSV, instrumentation plan, abort criteria | 1–2 min |
| throughflow | L2.5 | impeller meridional through-flow on the CAD channel and camber law: curvature-equilibrium Cm profile, Stanitz loading, hub-to-shroud incidence, TF-1..5 (Dean 1.6, Aungier 0.9); `analysis/throughflow.png` | ~1 s |
| thermal | L1 | secondary-air network, 9-node thermal network (rim / bore / shaft / bearing T predicted, +/-40 K declared), Palmgren bearing heat, oil / mist sizing, bearing abort setting; life and the bench consume it, THM-8 names the `jet set` for the mechanical inputs | < 1 s |

## Ground rules

* Numbers come from the stages, never from memory.  Report failed rules; do not loosen the
  input that defines a limit unless the user decides so.
* Every claim has a tier (L0 rule of thumb, L1 correlation/mean-line sizing, L2 loss models
  and FE beam, L3 ingested solver/test).  Say the tier when quoting a margin.  A margin that
  mixes an L3 stress with an L1 load is reported at L1.
* Estimates stay labelled: surge line +/-0.077 SM points (absolute band, rig-calibrated on
  HECC/CC3, `validation/data/surge_calibration.json`), life factor-of-3 scatter, conceptual
  stress factors.  `jet study uq` turns those bands into output distributions.
* Findings are closed by a modelled, reported change (a schedule, a geometry, an ingested
  result), never by editing a default or a limit.  Carry margin against the surge band.
* The exducer root and the turbine are sized *to* their limits by construction; 0 % margin on
  COMP-3 / MECH-4 is by design.
* CAD booleans are volume-checked; failures fall back to compounds and are reported.
* Validation before trust: `jet validate` and `docs/validation.md`.  New methods need a case.

## Code map

`stages/` core: requirements, cycle, speed, compressor, turbine, combustor, layout, rotor,
mechanical, control, geometry; analysis: maps, offdesign, envelope, transient, assess, combustor1d,
life, rotordyn, manufacturing, testbench (each declares `TIER`, `CORE`, `DEFAULTS`, `READS`, `run`).
`perf/`: closs (compressor loss model incl. rig-calibrated stall indicators and IGV pre-swirl),
tloss (turbine), maps (per-IGV map family), matching (schedules applied inside `evaluate`),
control (`Schedules`), transient (runs through the controller; T04 limiter is a per-step fuel ceiling).
`plots.py`: map / plot suite.  `compare.py`: freeze / verify / gate / side-by-side compare.
`uncertainty.py`: surge-margin band terms and the with-band arithmetic.  `fea/disc.py`: CalculiX disc case.
`validation/calibrate_surge.py`: re-derives the surge band from the rig residuals (`--write`).
`gas.py` exact thermo, `gas_fast.py` tabulated (used by matching loops).  `studies.py`
(DOE/NSGA-II/RBF/UQ/Morris), `handoff.py` (L3 export/ingest), `correlation.py` (test data),
`validation/` (database + runner), `report.py` (design + readiness reports), `cad/`, `library/`.

Adding a stage: `DEFAULTS`, `READS` (list every path you read), `run(doc)` returning outputs
with `_rules`; register the name in `stages/__init__.py` (CORE_MODULES or ANALYSIS_MODULES).
