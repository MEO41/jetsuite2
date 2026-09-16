# CLAUDE.md — operating jetsuite2

jetsuite2 designs a single-spool centrifugal micro-turbojet (100–1000 N) from
requirements to CAD.  It is operated through the `jet` CLI (or `jetsuite2.api.Design`).

## Environment

One venv, Python 3.12, CadQuery 2.8: `.venv\Scripts\jet ...` (install: see README).
No subprocesses, no other venvs.  Physics chain ~0.4 s; CAD 30–60 s (cached per part).

## Workflow

1. `jet new <dir> --thrust N [--alt m --mach M] [--set stage.key=value]` creates and runs.
2. Read the verdicts: `jet rules -d <dir>` (problems only) / `--all`.  Every rule says what to change.
3. Change inputs with `jet set -d <dir> stage.key=value --run`.  The output lists which stages
   re-ran, which were skipped (value hash unchanged) and the numbers that moved.
4. `jet converge` whenever COMP-12 / TURB-10 flag that the cycle efficiency assumptions differ
   from the component estimates.
5. `jet cad` builds STEP (per part + assembly); only parts whose geometry-sheet hash changed rebuild.
6. `jet report` writes `report.md`; `jet diff`, `jet history`, `jet checkout` manage versions.

Inputs live under `inputs.<stage>` in `design.json`; `jet inputs [stage]` documents them.
`auto` inputs are derived by the stage and may be overridden with a number.

## Ground rules

* Numbers come from the stages, never from memory.  If a rule fails, report it; do not
  hide it by loosening the input that defines the limit unless the user decides so.
* Estimates are labelled as such (efficiency correlations, conceptual stress factors).
  The surge margin of a vaned-diffuser stage is **not** predicted by this tool (no validated
  method; boomsonic_v0 finding) — say so when asked.
* The exducer root and the turbine are sized *to* their limits by construction; a 0 % margin
  on COMP-3 / MECH-4 is by design, not a defect.
* CAD booleans are volume-checked; a failed fuse falls back to a compound and is reported in
  the notes.  `CLASH` lines in `jet cad` output are real interferences to fix in the layout.

## Code map

`src/jetsuite2/`: `gas.py` (variable-cp thermo), `stages/` (one module per design stage with
`DEFAULTS`, `READS`, `run(doc)`), `rules/` (verdicts), `state/` (store + value-hash graph),
`library/` (materials + hardware JSON), `geomlib.py` (meridional profiles shared by analysis and
CAD), `rotordyn.py` (two-plane beam + gyroscopics), `cad/` (cadlib, impeller, blades, parts,
hardware, build), `api.py`, `cli.py`, `report.py`.  Tests: `pytest`.

Adding a stage: write `stages/<name>.py` with `DEFAULTS`, `READS` (dotted paths it consumes)
and `run(doc) -> dict` (include `_rules`), then add it to `stages/__init__.py: MODULES`.
Reading a value not listed in `READS` breaks invalidation — list everything you read.
