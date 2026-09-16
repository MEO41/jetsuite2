# jetsuite — build checklist

Status of record for what is built, what is open, and what order to do it in.
Tick items only when the "done when" condition is met, not when the code merges.

**Current state:** v3 complete in `jetsuitev2/`. Core chain 0.4 s, 36 tests green,
134 rules, L0–L3 provenance, `jet analyze all` ~6 min. Default design `designs/p500`
recovers 512 N at the T04 limit, TSFC 0.118 kg/N/h, with four open findings (§0).

**Guiding rule for this phase:** the suite currently finds operability problems it
cannot express the solution to. Close that asymmetry before adding fidelity anywhere else.

---

## 0. Open findings on p500 — the work these items exist to close

These are design findings, not tool defects. Each must be closed by a modelled,
reported change — never by editing a default.

- [ ] **F1 — Low-speed stall.** Fixed-nozzle running line sits in the predicted stall
      region below ~50 % speed. Attack order: bleed schedule → nozzle area → resize.
- [ ] **F2 — Slam surge margin.** Dips negative on slam acceleration. Suspected
      controller problem, not aerodynamic. Attack order: acceleration limit line first.
- [ ] **F3 — Turbine disc LCF.** Bore is LCF-limited at the start thermal transient.
      Attack order: sweep start ramp rate before touching disc geometry.
- [ ] **F4 — Turbine tip clearance.** Stack-up leaves almost no margin. The one
      genuinely structural finding: tolerance redistribution, abradable shroud, or
      cold-clearance change, traded against the efficiency penalty.

**Policy until a surge datum exists (§2):** carry margin, schedule around it, instrument
for it. Do not resize geometry against a ±30 % boundary. The surge line is reported as a
band, never a single number.

---

## 1. Surge credibility and control authority — *do first*

The ±30 % surge band is the weakest number in the suite and three of the four findings
depend on it. Two halves, both needed.

### 1a. Vaned-diffuser stall model
- [ ] Japikse diffuser inlet blockage / throat-Mach stall criterion implemented
- [ ] Vaneless-space rotating-stall criterion implemented
- [ ] Calibrated against NASA HECC and CC3 published surge lines
- [ ] Uncertainty band re-derived from calibration residuals, not declared
- [ ] `docs/validation.md` updated with the new error and the cases used

**Done when:** the predicted surge line for at least two published rigs falls inside its
own stated band, and the band is narrower than ±30 %.

### 1b. Variable geometry and control as design objects
- [ ] Handling bleed valve: port location, bleed fraction vs. corrected speed, effect on
      running line / surge margin / thrust / TSFC
- [ ] Variable exhaust nozzle area A8 as a scheduled variable
- [ ] Variable inlet guide vanes as an optional architecture (work-input vs. surge-margin
      vs. mechanical-complexity trade)
- [ ] Fuel schedule object: Wf/P3 vs. corrected speed, accel and decel limit lines, idle
      governor, max-speed and max-TIT topping limiter
- [ ] Start schedule with ramp rate exposed as a parameter
- [ ] Transient model runs **through** the controller, not around it
- [ ] All of the above participate in dependency invalidation and appear in the rule set

**Done when:** F1 and F2 are re-run against a scheduled configuration and either close or
are restated with a named, modelled remedy. F3 re-run against a start ramp-rate sweep.

---

## 2. Rig data for validation — *do second*

Everything currently validates against another code or a datasheet. This item changes what
every other number in the suite is worth. Data acquisition, not code.

- [ ] **Paper correlation.** Model 2–3 published commercial micro-turbojets in the
      100–1000 N class as if they were our designs; compare thrust, TSFC, spool speed,
      dimensions against published figures. `jet correlate` exists and currently has
      nothing to consume.
- [ ] **Fix transcribed geometry.** Pull original reports for the literature compressor
      and turbine cases; replace approximate transcribed geometry. Until done, stated
      validation errors contain an unknown component that is not the model's fault.
- [ ] **Measured map.** Acquire one real compressor map — university rig, JetCat rig test,
      or CC3 in machine-readable form.
- [ ] **Cold-flow rig definition.** Specify a compressor-only test article (impeller,
      diffuser, drive, no combustion) the suite can design and instrument. Cheapest route
      to a real surge line; de-risks the hardest part to manufacture.

**Done when:** at least one system-level and one component-level case in `jet validate`
is backed by measured data, with the error reported.

---

## 3. Freeze and comparison workflow — *do third*

Restores the discipline v0 had and that "test readiness" implies. Cheap, and it protects
everything downstream. ~1–2 days.

- [ ] Side-by-side comparison of two designs or two versions: rules, maps, report deltas
- [ ] `jet freeze` gate: snapshots the design, records sign-off and open risks
- [ ] CAD and export refuse to run on an unfrozen design unless explicitly overridden
- [ ] Frozen snapshots are immutable and hash-verifiable

**Done when:** p500 can be frozen, a variant branched, and the two diffed in one command.

---

## 4. Compressor map and plot suite

The primary review artifact. Should land alongside §1 so the scheduled results are
visible rather than tabulated.

### Compressor map — required layers
- [ ] Corrected mass flow (X) vs. pressure ratio (Y)
- [ ] Constant corrected-speed lines, sub-idle to overspeed, labelled as % design speed,
      drawn only between their surge and choke intercepts
- [ ] **Surge line as a shaded uncertainty band**, nominal dashed inside it — never a
      bare curve
- [ ] Choke line joining each speed line's max-flow point
- [ ] Efficiency islands, contoured and labelled
- [ ] Steady running line with the design point marked
- [ ] SAE surge margin annotated at points along the running line, with the band shown
- [ ] Scheduled running line drawn over a **ghosted unscheduled line**, so the bleed and
      nozzle benefit is visible
- [ ] Transient trajectories overlaid: start, slam accel, decel
- [ ] Stall / no-run region shaded

### Companion plots
- [ ] Turbine map: corrected flow vs. PR, speed lines, efficiency contours, operating points
- [ ] Smith chart and Balje/Cordier placement against achievable-efficiency bands
- [ ] Campbell diagram with operating range and resonance crossings marked

### Implementation
- [ ] Vector export (SVG + PNG) at publication resolution for the report
- [ ] Interactive HTML: layer toggles, hover readout, transient scrubbing
- [ ] `jet plot map` and siblings; auto-regenerated and stale-flagged by the graph
- [ ] Every plotted element tagged with its fidelity tier; L1-correlated and L3-derived
      lines visually distinguishable

**Done when:** F1 and F2 are legible from the map alone, with no table required.

---

## 5. Automated L3 loop — *do fourth*

Export and ingest are plumbed but only demonstrated. Close the loop so an L3 value
overwrites an L1 value without a human copying numbers.

- [ ] Impeller passage CFD driven end to end from `jet export` (SU2 or OpenFOAM; mesh via
      exported curves with cfMesh/snappyHexMesh, or TurboGrid if available)
- [ ] Impeller and turbine stress via CalculiX
- [ ] Result files parsed and ingested automatically as L3 overrides
- [ ] Graph re-triggers on ingest; provenance updated
- [ ] **One real solve each**, reported: impeller CFD at design point, turbine disc FE at
      the start transient — the two weakest correlations and the two binding findings
- [ ] Report what moved when L3 replaced L1, and whether F3 survives

**Done when:** a single command takes a design from state to ingested solver results, and
the p500 report cites L3 values for impeller efficiency and disc stress.

---

## 6. Secondary air, thermal and oil system — *do fifth*

Fixes the weakest inputs in the life stage. Disc bore/rim temperatures are currently
assumptions. ~3–5 days.

- [ ] Lumped secondary-air network: cavity flows, disc-cooling budget
- [ ] Thermal network: disc bore and rim temperatures predicted, not assumed
- [ ] Bearing heat balance
- [ ] Oil / mist system sizing
- [ ] Bearing-temperature abort criterion becomes a prediction

**Done when:** the life stage consumes predicted metal temperatures and the LCF and creep
results are re-reported against them.

---

## Second wave

### 7. True L2.5 through-flow
- [ ] Meridional streamline-curvature solver with blade force from the camber law
- [ ] Stanitz-type blade loading
- [ ] Hub-to-shroud incidence and loading diagrams
- [ ] First check of the blade *shape*, not just its angles

*~1 week. The brief asked for this; v3 covers it with mean-line loss models plus
radial-equilibrium checks only.*

### 8. Speed and dashboard
- [ ] Cache the steady schedule
- [ ] Parallelise the envelope grid
- [ ] `jet analyze all` under 2 minutes
- [ ] Single HTML dashboard per design: maps, running line, Campbell, envelope, rules

### 9. Manufacturing outputs
- [ ] 2D drawings with tolerances for shaft, housings, casing from the geometry sheet
- [ ] CAM-ready impeller: hub/shroud surfaces with fillets applied, not the sharp-cornered
      analysis solid

*Only worth doing once a design is close to freeze.*

### 10. Controller design
- [ ] Real ECU logic model: schedules, limiters, start logic, fault handling
- [ ] Exportable as tables to an actual controller

*Pairs with §1b.*

### 11. Architecture variants
- [ ] Two-stage or mixed-flow compressor
- [ ] Radial-inflow turbine as an alternative sizing stage

*Each is a new sizing stage reusing the rest. Only if the tool is to go beyond the
single-spool centrifugal brief.*

---

## Standing constraints

These apply to every item above. A change that breaks one of these is not done.

- [ ] Core chain stays at 0.4 s; new analysis is opt-in and cached
- [ ] All v2 and v3 regression cases stay green; the regression set grows, never shrinks
- [ ] New state (control, VG, thermal) participates fully in dependency invalidation —
      a material change must invalidate life results and optimisation studies, not just
      geometry
- [ ] Conceptual-level correlations stay labelled and keep their error bars
- [ ] No result is reported at a higher tier than its weakest input
- [ ] No finding is closed by changing a default

---

## Gate: are we ready to cut metal?

Do not order material until all four hold.

- [ ] Paper correlation reproduces published engines within stated error (§2)
- [ ] Cold rig — or a measured map — matches the predicted map inside the band (§2)
- [ ] L3 solves confirm impeller efficiency and disc stress (§5)
- [ ] All four p500 findings closed or accepted with a written rationale (§0)

If any of the first three disagrees with the suite, that disagreement is worth more than
the part would have been. Investigate before proceeding.
