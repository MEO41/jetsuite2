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
4. `jet analyze [names|all]` — opt-in analysis stages (see table).  Invalidated like every stage.
5. `jet study sweep|doe|optimize|uq|sensitivity <name> --spec '{...}'` — design-space work on
   the fast chain, stored under `studies/`, flagged STALE when the design changes.
6. `jet export cfd compressor|turbine` / `jet export fea impeller|turbine` — L3 hand-off package;
   fill `ingest_template.json` with the solver results, then `jet ingest <file> --run`.
7. `jet correlate test.csv [--calibrate --apply]` — as-designed vs as-tested, auditable calibration.
8. `jet cad`, `jet report`, `jet readiness`, `jet validate`.

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

## Ground rules

* Numbers come from the stages, never from memory.  Report failed rules; do not loosen the
  input that defines a limit unless the user decides so.
* Every claim has a tier (L0 rule of thumb, L1 correlation/mean-line sizing, L2 loss models
  and FE beam, L3 ingested solver/test).  Say the tier when quoting a margin.  A margin that
  mixes an L3 stress with an L1 load is reported at L1.
* Estimates stay labelled: surge line +/-30 %, life factor-of-3 scatter, conceptual stress
  factors.  `jet study uq` turns those bands into output distributions.
* The exducer root and the turbine are sized *to* their limits by construction; 0 % margin on
  COMP-3 / MECH-4 is by design.
* CAD booleans are volume-checked; failures fall back to compounds and are reported.
* Validation before trust: `jet validate` and `docs/validation.md`.  New methods need a case.

## Code map

`stages/` core: requirements, cycle, speed, compressor, turbine, combustor, layout, rotor,
mechanical, geometry; analysis: maps, offdesign, envelope, transient, assess, combustor1d, life,
rotordyn, manufacturing, testbench (each declares `TIER`, `CORE`, `DEFAULTS`, `READS`, `run`).
`perf/`: closs (compressor loss model), tloss (turbine), maps, matching, transient.
`gas.py` exact thermo, `gas_fast.py` tabulated (used by matching loops).  `studies.py`
(DOE/NSGA-II/RBF/UQ/Morris), `handoff.py` (L3 export/ingest), `correlation.py` (test data),
`validation/` (database + runner), `report.py` (design + readiness reports), `cad/`, `library/`.

Adding a stage: `DEFAULTS`, `READS` (list every path you read), `run(doc)` returning outputs
with `_rules`; register the name in `stages/__init__.py` (CORE_MODULES or ANALYSIS_MODULES).
