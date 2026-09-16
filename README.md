# jetsuite2 — micro-turbojet design, analysis and validation suite (v3)

Single-spool, centrifugal-compressor turbojets, 100–1000 N.  From a thrust target and a
mission to a Pareto-justified design with quantified envelope performance, margins,
uncertainty and a test-ready package.

```
core (sub-second, every run):
  requirements -> cycle -> speed -> compressor -> turbine -> combustor -> layout -> rotor -> mechanical -> geometry -> cad
analysis (opt-in, cached, value-hash invalidated like everything else):
  maps -> offdesign -> envelope -> transient -> testbench      assess, combustor1d, life, rotordyn, manufacturing
studies (on the fast chain): sweep, doe, optimize (NSGA-II), uq (LHS Monte Carlo), sensitivity (Morris)
hand-off: export cfd/fea packages -> external solver -> ingest results as L3 overrides
test: virtual test bench, instrumentation plan, abort criteria, correlation / calibration against test data
```

![500 N design, meridional section](docs/img/p500_section.png)

## Install

```powershell
uv venv --python 3.12 .venv
$env:VIRTUAL_ENV="$PWD\.venv"; uv pip install -e . pytest
.venv\Scripts\jet --help
```

## Quick start

```powershell
jet new designs\p500 --thrust 500                    # create + core chain (0.4 s)
jet set -d designs\p500 compressor.material=Al2618-T61 --run
jet converge -d designs\p500
jet analyze all -d designs\p500                      # maps, running line, envelope, transients, assessment, life, ...
jet status -d designs\p500                           # fidelity tier / staleness / ingested overrides per stage
jet rules -d designs\p500 --all
jet study doe opr_bs --spec '{"variables": {"cycle.OPR": [3.2, 4.6], "compressor.backsweep_deg": [15, 40]}, "n": 32}' -d designs\p500
jet study optimize pareto --spec '{"variables": {"cycle.OPR": [3.2, 4.6], "cycle.T04_K": [1080, 1200]}, "objectives": {"mass_kg": "min", "TSFC": "min"}, "pop": 24, "generations": 10}' -d designs\p500
jet study uq bands -d designs\p500                   # thrust, TSFC, margins as p05/p50/p95
jet study sensitivity rank -d designs\p500
jet export cfd compressor -d designs\p500            # handoff/compressor_cfd: curves, flowpath.step, case.json, ingest_template.json
jet ingest designs\p500\handoff\compressor_cfd\ingest_template.json --run -d designs\p500
jet correlate test_run.csv --calibrate -d designs\p500
jet validate                                         # every method vs the validation database
jet cad -d designs\p500 ; jet report -d designs\p500 ; jet readiness -d designs\p500
```

## What v3 adds over v2

* **Fidelity ladder** — every stage carries a tier (L0/L1/L2/L3); `jet status` shows where each
  component stands; ingested solver/test results override stage values with provenance and
  re-trigger the graph; rules carry the tier of the load they were evaluated at.
* **L2 component physics** — mean-line loss models for the compressor (Oh/Aungier set, spanwise
  inducer choke, stall indicators, vaned-diffuser throat/incidence) and the turbine
  (Ainley-Mathieson/Dunham-Came with Kacker-Okapuu scaling), validated against independent
  code and literature (`docs/validation.md`).  1-D combustor network.  Rotordynamics campaign.
* **Quality assessment** — Balje/Cordier placement, slip by four methods with the disagreement
  surfaced, de Haller / diffusion / Coppage loading, incidence across the running line, diffuser
  throat and two-zone mixing, backsweep trade study, Smith chart, Zweifel, hub reaction.
* **Off-design, envelope, transients** — maps with surge and choke lines, running line with
  surge margin, altitude/Mach/dT envelope, start / slam / decel / hot & hung start / overspeed /
  flameout on the rotor inertia.
* **Life** — Larson-Miller creep over a mission, Manson LCF with start thermal stress, bearing
  L10 with lubrication, containment.
* **Optimisation and UQ** — DOE (LHS/Sobol), NSGA-II with the rules as constraints, RBF
  surrogates with leave-one-out error, Morris sensitivity, Monte-Carlo UQ with the validation
  errors as default bands; every study records the base-design hash and is flagged stale.
* **Test loop** — virtual test bench (log CSV, plots), instrumentation plan, abort criteria,
  test-readiness report, correlation and calibration against measured data.
* **Manufacturability** — tolerance stack-up, ISO 21940 balance requirement, 5-axis
  machinability screen, process-dependent allowables, BOM with part numbers and cost/lead.

## Verification

`pytest` — v2 suite (gas model, invalidation, rotordynamics closed forms, thrust sweep,
boomsonic_v0 regression) plus `tests/test_v3.py` (tabulated thermo, loss-model validation
tolerances, tiers/ingest, maps and matching closure, studies).  `jet validate` prints the
model-vs-reference table (`docs/validation.md`).

## Documents

`docs/architecture.md`, `docs/kernel_evaluation.md`, `docs/design_rules.md`, `docs/validation.md`, `CLAUDE.md`.
