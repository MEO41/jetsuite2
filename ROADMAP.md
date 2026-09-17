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

- [~] **F1 — Low-speed stall.** Fixed-nozzle running line sits in the predicted stall
      region below ~50 % speed. Attack order: bleed schedule → nozzle area → resize.
      *Re-run 2026-09-16 (scheduled configuration, `designs/p500_sched`, L2, band ±0.077):*
      bleed 15 % + nozzle A8 1.30 lift idle (0.50 N) SM from −0.089 to 0.00 — not enough;
      backsweep 30→45° does not help below 0.6 N (the low-speed surge points are set by the
      **inducer incidence** criterion, not the diffuser). **Named remedy: IGV pre-swirl**
      (25° at ≤0.5 N, closed by 0.8 N, with the same bleed/nozzle): SM +0.17 at 0.45 N,
      +0.23 at idle, ≥ +0.19 everywhere from idle up (OD-1 still reports +0.06 at 0.40 N,
      below idle, only crossed during start). Open until IGV maps have a rig case (no IGV
      rig data exist; L2 extrapolation) and the IGV row is in the layout/CAD/mass.
      *Evening update (corrected part-speed model, see 0b):* fixed geometry idle SM −0.044 (was −0.089);
      scheduled (bleed 15 %, A8 1.30, IGV 25°) idle +0.300 with band ±0.159 (IGV term 0.140 dominant) → +0.141
      ≥ 0.08 passes with the band; IGV row now in layout / geometry / CAD (+22 mm, +0.165 kg); failed-open
      IGV slam SM +0.034 (fails with the band). Status: **open — uncalibrated remedy**.
- [~] **F2 — Slam surge margin.** Dips negative on slam acceleration. Suspected
      controller problem, not aerodynamic. Attack order: acceleration limit line first.
      *Re-run 2026-09-16 through the controller (accel/decel limit lines vs Nc, governor,
      topping limiters):* the accel line is **not** the lever — scaling it 0.4…1.0 trades
      idle→95 % time 7→>12 s with no SM gain because the minimum sits at the idle point
      itself (F2 was F1 in disguise). Idle 0.60 N alone gives SM +0.05 at 5.5 s. With the F1
      remedy (IGV + bleed + nozzle) the slam accel min SM is **+0.12 at 0.81 N** (TRN-4
      passes nominally; inside the ±0.077 band it is +0.04, i.e. not closed with margin),
      t95 7.2 s (TRN-3 still warns vs 6 s). Closes together with F1.
      *Evening update:* slam min **+0.171 at 0.81 N** (IGV closed there), band rss(0.077, 0.030) = 0.082,
      +0.171 − 0.082 = +0.089 ≥ 0.05 → **passes with the band** on p500_sched; on the fixed-geometry p500 it is
      −0.038 (fails). Depends on the same uncalibrated IGV remedy as F1 at idle, so it is closed only
      conditionally on F1.
- [~] **F3 — Turbine disc LCF.** Bore is LCF-limited at the start thermal transient.
      Attack order: sweep start ramp rate before touching disc geometry.
      *Start-ramp sweep 2026-09-16 (`control.start_ramp_rate` 0.25→0.01, i.e. 4 s→100 s
      gas-temperature ramp, life L1, factor-3 scatter):* LIFE-4 153→218 cycles vs 500,
      thermal ΔT 293→266 K. The ramp is not the lever: the bore is dominated by the
      mechanical (centrifugal) bore stress, the thermal term adds ~15 %. **Restated: disc
      geometry** (thicker hub, boreless/stub wheel — `turbine_mount` already `stub`; the LCF
      model still applies a bore) or an ingested L3 FE bore stress. Still open.
      *Evening update (L3, work package E):* CalculiX says the wheel as drawn is a 15 mm through-bored disc:
      peak 967 MPa at MCS (L1 said 518), 1281 MPa with the start gradient → **14 cycles** vs 500; MECH-5
      fails at L3. Boreless what-if 675 / 899 MPa. Disc geometry (integral boreless hub, thicker web, fillets)
      or material step required; trade against overhung mass / RD-1 and the tip-clearance stack (F4).
- [ ] **F4 — Turbine tip clearance.** Stack-up leaves almost no margin. The one
      genuinely structural finding: tolerance redistribution, abradable shroud, or
      cold-clearance change, traded against the efficiency penalty.

**Policy until a surge datum exists (§2):** carry margin, schedule around it, instrument
for it. Do not resize geometry against a ±30 % boundary. The surge line is reported as a
band, never a single number.

---

## 0b. Work package after §1/§4 (2026-09-16, evening) — status

**A. Hot-start T04 limiter — fixed (defect).** Root cause was not the limiter logic alone: below ~40 %
speed the quasi-steady matching had *no solution* (burner/jet-pipe dP fixed at the design fraction, turbine PR
floor 1.05, nozzle residual badly scaled, turbine map clamped at its lowest PR), so the integrator held a stale
state for hundreds of steps while the fuel ratio wound up, and the limiter acted on a held temperature. Fixed
by four physics corrections (dP scales with dynamic head; PR_t floor 1.001; capacity-form nozzle residual;
orifice-like turbine-map extrapolation), a T04 loop that is a per-step fuel ceiling with anti-windup, and a
residual scan for the ceiling solve. Hot-start peak on p500_sched 1650 K → 1200.0 K (the limit), zero steps
over on both designs; regression test `test_hot_start_T04_limiter_holds_at_low_speed` (lit engine at 30 %,
rich accel, limit 1100 K, unlimited case must exceed it). Residual: the fixed-geometry start still holds
below ~15 % speed (no solution), and TRN-7 is now a plain pass. **Side effect that matters:** the part-speed
running line moved (idle SM on fixed geometry −0.089 → −0.044 in the corrected model; the schedules' benefit
is now larger), so every F1/F2 number below supersedes the morning's.

**B. Freeze and compare — done.** `jet freeze --by/--note/--status/--verify`, `frozen/vNNNN.json` +
`.sha256`, read-only on disk, content-hash = f(inputs, outputs, overrides); any change unfreezes and names
what moved. `jet cad` / `jet export` refuse unfrozen designs unless `--unfrozen-ok`. `jet compare A B
[--out]` with `dir`, `dir@vNNNN`, `dir@frozen`: headline, inputs, overrides, rules that changed, surge
margins with band and dominant term, running lines, map overlay PNG. Demonstrated: `jet compare designs/p500
designs/p500_sched --out designs/p500_sched/compare_vs_p500.md`. Test `test_freeze_compare_and_gate`.

**E. Disc FE before redesign — done, and it changes the picture.** `jet fe disc [--ingest]`: CalculiX
2.21 (WSL) axisymmetric CAX4 model of the wheel profile, centrifugal + blade-row pull + start thermal field.
Mesh convergence: mean hoop = L1 mass value (398 vs 399 MPa); peak ≥ 1 mm from the unfilleted re-entrant
corners converges 956/967/973 MPa (0.8/0.5/0.35 mm), the corner value diverges (singular). **The profile as
drawn has a 15 mm through-bore while the L1 factor assumed a boreless disc**: L3 peak 967 MPa vs 518 MPa L1,
above the 631 MPa bore allowable (MECH-5 now FAILS at L3); LCF with the start gradient 153 → **14 cycles**
(LIFE-4). Boreless what-if (`--variant boreless`): 675 / 899 MPa — better, still inadmissible. Proposal
(not executed, per E): (1) make the wheel genuinely boreless with an integral stub *and* a thicker hub
(target hoop mean ≤ 250 MPa at MCS → hub width ≈ +60 %), traded against +0.1–0.15 kg on the overhung mass
(rotordyn RD-1 bending margin, currently 25 %) and the tip-clearance stack (MFG-2 already failing); (2) or a
material step (MAR-M-247 / IN718 bore allowable) at lower rpm. Fillets must be in the profile before the
corner stresses mean anything. F3 restated at L3: **open, disc geometry**.

**D. Band compounding — stated.** `uncertainty.py`: terms rig 0.077 (derived), IGV extrapolation = 0.5 ×
credited pre-swirl benefit at the point (declared fraction, zero with IGV open), low-speed extension 0.03
(declared), transient quasi-steady model form 0.03 (declared); combined by RSS (independent sources, no
known-sign bias; documented in `docs/validation.md`). Every surge rule (MAP-1, OD-1, OD-4, ENV-2, TRN-4)
carries value ± band with terms, value − band and the with-band verdict; the report has a "Surge margins with
their uncertainty bands" table and `jet compare` shows both sides. The morning's F2 statement is now
arithmetic: p500_sched slam min +0.171 at 0.81 N (IGV closed there), band = rss(0.077, 0.03) = 0.082,
+0.171 − 0.082 = +0.089 ≥ 0.05 → passes with the band. Idle: +0.300, band rss(0.077, 0.140 igv) = 0.159,
+0.141 ≥ 0.08 → passes with the band, dominant term IGV extrapolation.

**C. F1 remedy made honest — partly done, F1 stays open with an uncalibrated remedy.**
* Band: every surge result produced with the IGV scheduled carries its own named term (0.5 × the credited
  pre-swirl benefit at that point); on p500_sched at idle the term is 0.140, larger than the rig term.
* Mechanical row (`layout` reads `inputs.control.igv_enabled`, no graph cycle): 17 flat vanes, chord 14.7 mm,
  hub bullet 12.6 mm, radial spindles 3 mm through the duct wall with PTFE-lined bronze bushings, unison ring
  outside the inlet, rotary servo; row + gap 22 mm ahead of the bellmouth → engine length 350 → 379 mm; mass
  +0.165 kg (vanes 61 g, ring 31 g, bullet 13 g, actuator 60 g) → 6.66 kg. CAD parts `igv_vanes`,
  `igv_hub_bullet`, `igv_unison_ring` build valid. No rotor bearing or hot-seal implication (cold inlet, vane
  spindle bushings only); the extra overhang is on the static inlet, not the rotor.
* Rules: CTL-8 actuation rate required (schedule slope × fastest class accel) 9.4 °/s vs 30 °/s capability
  (pass); CTL-9 failure position defined (`control.igv_fail_position`, default open = 0 °).
* Failed-IGV transient (TRN-10, new scenario `igv_failed`): slam accel with the vanes stuck open on
  p500_sched → SM min **+0.034** (idle +0.121), t95 7.4 s. Passes the ≥ 0 floor nominally; with the band
  (rss 0.077, 0.03 = 0.082) it is −0.048 → **fails with the band**. A fail-closed actuator (pre-swirl kept)
  or a bleed interlock on IGV-position loss is the named follow-up; both are modelled objects now
  (`igv_fail_position=closed` re-runs the case).
* Re-run with the IGV mechanically real: the aero results are unchanged by construction (the row adds
  length and mass, not loss — the vane-row loss is *not* in the loss model yet; listed as an open model item).
  **F1 status: open with an uncalibrated remedy.** The remedy has no rig datum (§F adds one) and its own
  band term dominates the idle margin.

**New finding F6 — impeller bore at L3.** The impeller hub FE (blades smeared as traction, steady
eye-to-exit temperature field) puts the bore at 739 MPa vs 617 MPa min-basis yield (MECH-1 FAIL at L3;
L1 said 405 MPa with k_peak 1.6) and the bore LCF at 343 cycles / scatter vs 500 (LIFE-3). Same root as
F3: a 15 mm through-bore in a thick hub at 524 m/s tip speed. Remedies to trade together with F3: boreless
(tie-bolt-less) impeller with an integral stub, lower U2 (OPR / backsweep), or Ti-6Al-4V → a higher-strength
titanium; every one moves the rotor mass, RD-1 and MFG-2.

**New finding F5 — high-speed / altitude surge margin.** With the corrected part-speed model the binding
points are no longer at low speed: OD-1 minimum is at 1.05 N (+0.069 vs 0.10, fixed geometry, no schedule
acts there) and ENV-2 worst −0.046 at 9000 m / M 0.6 / cold day (max-power point). Both fail with the
band. Remedy candidates (unmodelled so far): variable nozzle opening at altitude / overspeed, N_max 1.05 →
1.03, or rematching the design point; to be attacked before §2.

## 0c. Deferred: transonic / installed-performance capability (requested 2026-09-16, not started)

Kept for after the planned items. Scope agreed in conversation:
- [ ] Inlet stage (core, L1): recovery vs Mach by intake type (pitot: duct loss + MIL-E-5008B / normal shock
      above M 1, transonic spillage term 0.8-1.2; optional cone/ramp external compression with the ramp position as
      a control schedule), capture-area ratio, additive drag; rules on the recovery cliff. Plot: Pt2/Pt1 vs M0,
      one curve per intake setting. Declared band until a datum exists (add a published pitot recovery curve to §2).
- [ ] Installed thrust decomposition: envelope Mach grid to 1.2-1.4 (needs map speed lines beyond 1.10 or an
      explicit beyond-map flag), gross / ram / net / spillage per point; `jet plot installed`.
- [ ] Extended surge margin vs Mach with altitude contours and the band; explicit SM = 0 and SM = floor crossings
      exported as a (Mach, altitude) table for RL constraints.
- [ ] Airframe drag polar stage (L0/L1, declared): CD0, wave-drag rise 0.8-1.2, induced drag; excess thrust, thrust =
      drag crossings, "stuck at M 0.95" rule.
- [ ] Later: optimise a design for a given operating envelope (studies over the installed sweep).

## 1. Surge credibility and control authority — *do first*

The ±30 % surge band is the weakest number in the suite and three of the four findings
depend on it. Two halves, both needed.

### 1a. Vaned-diffuser stall model
- [x] Japikse diffuser inlet blockage / throat-Mach stall criterion implemented (incidence vs M3, `closs.diffuser_stall_incidence`)
- [x] Vaneless-space rotating-stall criterion implemented (Senoo-Kinoshita, radius ratio ≥ 1.3)
- [x] Calibrated against NASA HECC and CC3 published surge lines (`jet validate rigs`, 9/9 inside tolerance; CC3 vane LE assumed)
- [x] Uncertainty band re-derived from calibration residuals, not declared (±0.077 SM points absolute, `surge_calibration.json`)
- [x] `docs/validation.md` updated with the new error and the cases used

**Done when:** the predicted surge line for at least two published rigs falls inside its
own stated band, and the band is narrower than ±30 %.
*Status 2026-09-16: both rigs inside the band. The band (±0.077 absolute) is narrower than
±30 % relative only for margins above 0.26 — for p500's low-speed margins it is wider. Honest
outcome; the CC3 vane angle is the dominant unknown → §2.*

### 1b. Variable geometry and control as design objects
- [x] Handling bleed valve: port location, bleed fraction vs. corrected speed, effect on
      running line / surge margin / thrust / TSFC (`control` stage; port in the geometry sheet)
- [x] Variable exhaust nozzle area A8 as a scheduled variable
- [~] Variable inlet guide vanes as an optional architecture (work-input vs. surge-margin
      vs. mechanical-complexity trade) — aero (pre-swirl in the loss model, per-IGV map family,
      schedule) done; the mechanical row (vane ring, actuator, mass, layout length) is not
- [x] Fuel schedule object: Wf/P3 vs. corrected speed, accel and decel limit lines, idle
      governor, max-speed and max-TIT topping limiter
- [x] Start schedule with ramp rate exposed as a parameter (`control.start_ramp_rate`, read by transient and life)
- [x] Transient model runs **through** the controller, not around it (bench too)
- [x] All of the above participate in dependency invalidation and appear in the rule set (CTL-1…7; `outputs.control.*` in READS of maps/offdesign/transient/life/geometry)

**Done when:** F1 and F2 are re-run against a scheduled configuration and either close or
are restated with a named, modelled remedy. F3 re-run against a start ramp-rate sweep.

---

## 2. Rig data for validation — *do second*

Everything currently validates against another code or a datasheet. This item changes what
every other number in the suite is worth. Data acquisition, not code.

- [x] **Paper correlation.** Model 2–3 published commercial micro-turbojets in the
      100–1000 N class as if they were our designs; compare thrust, TSFC, spool speed,
      dimensions against published figures. `jet correlate` exists and currently has
      nothing to consume.
      *Done 2026-09-16: `jet validate paper` (P300-PRO, Olympus HP, P400-PRO-LN; data + sources in
      `paper_engines.json`). Result: at the published rpm the suite runs +6…+25 % thrust and +30…+140 K
      hotter (MAP-6: loss-model map ~7 % stronger than the sized cycle); EGT-limited thrust within 2 %,
      airflow +6…+8 %, fuel flow −20…−23 % (suite TSFC optimistic by ~20 %); mass +10…+58 %. Two-point
      calibration on the P300 is under-determined; eta_b runs to its bound. See docs/validation.md.*
- [~] **Fix transcribed geometry.** Pull original reports for the literature compressor
      and turbine cases; replace approximate transcribed geometry. Until done, stated
      validation errors contain an unknown component that is not the model's fault.
      *2026-09-16: Olympus HP PR corrected 3.5 → 3.8 from the datasheet; HECC geometry is from the CR
      appendix (sourced). The CC3 vane leading-edge angle could not be retrieved (NTRS / ResearchGate /
      MDPI blocked or without the number) — still the dominant surge-band unknown; needs the McKain &
      Holbrook CR-204134 tables or Skoch's rig drawings, offline.*
- [~] **Measured map.** Acquire one real compressor map — university rig, JetCat rig test,
      or CC3 in machine-readable form.
      *The HECC vaned map (`validation/data/hecc/map_vaned.csv`, NASA CR-2014-218114 rig data) is
      measured and machine-readable and is what the surge model is fitted on — satisfied at rotorcraft
      scale (4.9 kg/s). A micro-scale map (JetCat / university rig) is still wanted.*
- [x] **Cold-flow rig definition.** Specify a compressor-only test article (impeller,
      diffuser, drive, no combustion) the suite can design and instrument. Cheapest route
      to a real surge line; de-risks the hardest part to manufacture.
      *Done: `jet rig compressor` (`rig.py`) writes the test article (engine impeller + diffuser + IGV
      row if fitted, collector, throttle), drive sizing (p500: 152 kW at design → 250 kW drive, i.e. an
      air-turbine drive), instrumentation with ranges from the map, a per-speed-line run matrix with the
      predicted surge band, safety trips, and the ingest template for the measured surge / choke / eta.*

**Done when:** at least one system-level and one component-level case in `jet validate`
is backed by measured data, with the error reported.
*Status: met — system level `jet validate paper` (datasheet points, errors reported above), component
level `jet validate rigs` (HECC / CC3 measured maps). Outstanding: micro-scale map, CC3 vane angle,
IGV / pre-swirl case (0b-C).*

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
- [x] Corrected mass flow (X) vs. pressure ratio (Y)
- [x] Constant corrected-speed lines, sub-idle to overspeed, labelled as % design speed,
      drawn only between their surge and choke intercepts (stalled branch is an off-by-default layer)
- [x] **Surge line as a shaded uncertainty band**, nominal dashed inside it — never a
      bare curve
- [x] Choke line joining each speed line's max-flow point
- [x] Efficiency islands, contoured and labelled
- [x] Steady running line with the design point marked
- [x] SAE surge margin annotated at points along the running line, with the band shown
- [x] Scheduled running line drawn over a **ghosted unscheduled line**, so the bleed and
      nozzle benefit is visible (plus the surge lines of the scheduled IGV settings)
- [x] Transient trajectories overlaid: start, slam accel, decel
- [x] Stall / no-run region shaded

### Companion plots
- [~] Turbine map: corrected flow vs. PR, speed lines, efficiency contours, operating points (operating points pending: the running line does not yet store turbine PR / corrected flow)
- [x] Smith chart and Balje/Cordier placement against achievable-efficiency bands (L0 contours)
- [x] Campbell diagram with operating range and resonance crossings marked

### Implementation
- [x] Vector export (SVG + PNG) at publication resolution for the report (embedded by `jet report`)
- [~] Interactive HTML: layer toggles, hover readout (W, PR, nearest line, SM vs its surge point) — transient scrubbing not yet
- [x] `jet plot map|turbine|all`; regenerated by `jet report`, stale-flagged in `jet status` via `analysis/plots/manifest.json`
- [~] Every plotted element tagged with its fidelity tier; L1-correlated and L3-derived
      lines visually distinguishable (tier tags per layer are on the map; no L3-derived line style yet because no L3 map exists)

**Done when:** F1 and F2 are legible from the map alone, with no table required.

---

## 5. Automated L3 loop — *do fourth*

Export and ingest are plumbed but only demonstrated. Close the loop so an L3 value
overwrites an L1 value without a human copying numbers.

- [~] Impeller passage CFD driven end to end from `jet export` (SU2 or OpenFOAM; mesh via
      exported curves with cfMesh/snappyHexMesh, or TurboGrid if available)
      *2026-09-17: OpenFOAM is not installable on this WSL Ubuntu release.  Built on SU2 v8.5.0 win64 instead:
      `jet cfd` writes a structured periodic H-mesh of one passage from the CAD camber and thickness laws
      (`cfd/hmesh.py`, 45k hexes Euler / 72k wall-resolved RANS), a streamline-aligned initial field, runs a
      throttle continuation to the design passage mass flow, post-processes the totals and would ingest
      `eta_impeller_cfd` / `PR_cfd` (COMP-16).  Verified on eight non-rotating and wall-of-revolution cases
      (docs/validation.md).  NOT CLOSED: the bladed rotating solutions miss 15-25 % of their Euler work in the
      energy equation even when converged (a plain rotating duct closes within ~10 %), so an efficiency from them
      is uncertain by +/- 0.2; nothing is ingested (gate `JET_SU2_ROTATING_WALLS_OK`).  Reference case
      `validation/su2_rotating_wall_repro.py`.  Next: finer / less skewed mesh with the Giles turbomachinery
      boundary set, or a cell-centred solver.*
- [x] Impeller and turbine stress via CalculiX (`jet fe impeller|disc|all`: axisymmetric hub / disc, blades as smeared traction; blade-root stress stays strip theory)
- [x] Result files parsed and ingested automatically as L3 overrides (`.dat` element stresses -> ingest JSON -> `Design.ingest`)
- [x] Graph re-triggers on ingest; provenance updated (overrides are part of the stage input hash; the mechanical and life stages evaluate their rules on the ingested value)
- [~] **One real solve each**, reported: impeller CFD at design point, turbine disc FE at
      the start transient — the two weakest correlations and the two binding findings
      *Disc FE done (0b-E). Impeller hub FE done as a bonus: 700 MPa centrifugal / 739 MPa with the steady
      eye-to-exit field at the bore (r 7.8 mm) vs 405 MPa L1, above the 617 MPa Ti-6Al-4V yield. Impeller
      CFD: pipeline complete, the solve does not close its energy balance (see above); no L3 impeller efficiency.*
- [x] Report what moved when L3 replaced L1, and whether F3 survives
      *`jet l3` runs both FE cases, ingests, re-runs core + life and prints the before/after rule deltas
      (`analysis/l3_delta.md`). On p500_sched: MECH-1 405 → 739 MPa (pass → FAIL), MECH-5 518 → 967 MPa
      (pass → FAIL), LIFE-3 impeller bore 2.8e6 → 343 cycles (FAIL), LIFE-4 154 → 14 cycles. **F3 does
      not survive L3, and the impeller joins it (new finding F6 below).**

**Done when:** a single command takes a design from state to ingested solver results, and
the p500 report cites L3 values for impeller efficiency and disc stress.
*Status: the single command exists (`jet l3`, 26 s) and the report cites L3 disc and impeller stress;
impeller efficiency is still L2 (no CFD).*

---

## 6. Secondary air, thermal and oil system — *do fifth*

Fixes the weakest inputs in the life stage. Disc bore/rim temperatures are currently
assumptions. ~3–5 days.

- [x] Lumped secondary-air network: cavity flows, disc-cooling budget (`thermal` stage: impeller back-face labyrinth (Martin) -> shaft tunnel -> turbine front cavity -> rim seal; windage heating; THM-4 budget, THM-5 rim-purge minimum)
- [x] Thermal network: disc bore and rim temperatures predicted, not assumed (9-node steady network: blade root -> rim -> web -> bore -> shaft -> rear bearing -> housing, impeller hub -> front bearing; rotating-disc / flat-plate convection; p500: rim 1040 K predicted vs 950 K assumed, bore 791 vs 750 -> THM-8 warns and names the `jet set` to carry it into the stress rules)
- [x] Bearing heat balance (Palmgren M0 + M1 friction heat, ~200 W per bearing on p500; oil / mist and housing paths; THM-3 / THM-6 vs the bearing rating)
- [x] Oil / mist system sizing (oil flow for a 40 K rise, carrier air, pump duty in `thermal.oil_system`)
- [x] Bearing-temperature abort criterion becomes a prediction (bench abort = predicted rear-bearing T + 30 K: 389 K on p500 instead of the assumed 450 K)

**Done when:** the life stage consumes predicted metal temperatures and the LCF and creep
results are re-reported against them.
*Status 2026-09-17: met. Life reads `thermal.temperatures` when present (rule sources say "T thermal network
L1 +/-40 K"); p500 LIFE-4 re-reported at the predicted rim / bore (dT_max 293 -> 342 K, 14 cycles unchanged
in verdict), bearing L10 at the predicted 359 K. The +/-40 K band is declared until a thermocouple datum
exists; the mechanical stage's stress rules still use its temperature inputs (core cannot read an opt-in
analysis) and THM-8 flags the mismatch with the exact `jet set` to close it.*

---

## Second wave

### 7. True L2.5 through-flow
- [~] Meridional streamline-curvature solver with blade force from the camber law (`throughflow` stage, L2.5: streamlines hub->shroud on the CAD channel, normal-equilibrium curvature term for the Cm profile, continuity with blade + boundary-layer blockage, rothalpy thermodynamics with a polytropic loss law; blade-aligned flow with slip-based deviation toward the TE. Not a full SCM iteration on the streamline positions: the streamlines are the geometric blends)
- [x] Stanitz-type blade loading (W_ss - W_ps = 2 pi / N cos(beta) d(r C_theta)/dm, splitter row doubling N; TF-1 reverse-flow, TF-2 suction deceleration 1.6, TF-5 loading 0.9)
- [x] Hub-to-shroud incidence and loading diagrams (`analysis/throughflow.png`: loading on hub / mid / shroud, incidence vs span, Cm contour; TF-3 incidence spread, TF-4 exit Cm distortion)
- [x] First check of the blade *shape*, not just its angles
      *p500: shroud suction-side deceleration 1.93 (TF-2 FAIL vs 1.6), loading parameter 1.96 (TF-5 warn vs 0.9),
      pressure-side velocity down to 4 m/s in the inducer (TF-1 just passes), incidence +4 hub / +8 shroud deg
      (spread 4 deg, TF-3 pass), exit Cm distortion 1.03. The smooth-step camber with 8 main blades and the
      splitter at 40 % loads the inducer too hard: **new finding F7 — inducer blade loading**; remedies are a
      camber law with earlier turning, an earlier splitter, or 9-10 main blades (COMP / MFG-6 wrap trade).*

*~1 week. The brief asked for this; v3 covers it with mean-line loss models plus
radial-equilibrium checks only.*

### 8. Speed and dashboard
- [x] Cache the steady schedule (off-design exports `steady_schedule`; transient and bench reuse it)
- [x] Parallelise the envelope grid (process pool, `envelope.workers`, 70 -> 39 s on p500)
- [x] `jet analyze all` under 2 minutes — **1 min 47 s** on p500 (was 5 min 29 s serial, ~8 min originally).
      How: (1) the graph runner executes each dependency wave of analysis stages concurrently in processes
      (`api.analyze(parallel=True)`, `--workers`, `--serial`); (2) the transient's three start scenarios run in
      their own pool and the envelope grid in a process pool; (3) per-step cost of the integrator cut 3.6x: scalar
      bilinear thermo lookups on python lists (`gas_fast._scalar`, same tables), the surge margin computed only
      on the accepted point rather than inside every residual evaluation, and the T04-ceiling solve warm-started
      from the previous step and skipped when the last converged point is > 15 % below the limit with the command
      off the accel line (the limiter test still passes); (4) the bench and the 1-D combustor no longer declare
      dependencies they did not use (bench: controller from the control stage, pattern factor from the core
      combustor's liner), so both run in the transient wave. Waves on p500: 14 s (maps, throughflow, thermal,
      rotordyn, manufacturing), 15 s (offdesign, envelope, life), 64 s (assess, combustor1d, transient, testbench).
- [x] Single HTML dashboard per design: maps, running line, Campbell, envelope, rules (`jet dashboard` -> `dashboard.html`, self-contained, base64 plots, rules with band arithmetic, stage status and L3 provenance)

### 9. Manufacturing outputs
- [x] 2D drawings with tolerances for shaft, housings, casing from the geometry sheet (`jet drawings`: dimensioned half-section SVG/PNG + `drawings.md` fit tables; ISO 286 deviations for the sizes used — seats k5, bores H6, tunnel H7, ring / o-ring grooves; datums, runout and flatness callouts)
- [~] CAM-ready impeller: hub/shroud surfaces with fillets applied, not the sharp-cornered
      analysis solid
      *`jet cam impeller` writes the package a 5-axis CAM system consumes: suction / pressure surface grids
      (main + splitter), hub and shroud meridional curves, STEP of hub, blade and the sharp impeller, and
      `cam_spec.json` with the fillet radius, tip thickness, clearance allowance and machining notes. The OCC
      fillet on the fused solid fails (1566 candidate edges from the tessellated blade solids; the wrapped
      thin-TE geometry is beyond the fillet builder), so the filleted STEP is **not** produced; the sharp solid
      is exported and the fillet stays a specification the CAM applies. Second attempt (same day): the gas-path
      hub rebuilt as one spline surface of revolution (root edges 1566 -> 85, selected by face ancestry), then a
      fallback ladder (all root edges at r; suction/pressure root curves only; 0.6 r on 51 edges) — the OCC
      builder fails on every rung. The blade-hub junction of the sewn B-spline blade solids is beyond
      BRepFilletAPI; the remaining route is an explicit fillet (sweep a fillet section along each root curve
      and fuse) or leaving it to the CAM system, which is what the spec does.*

*Only worth doing once a design is close to freeze.*

### 10. Controller design
- [x] Real ECU logic model: schedules, limiters, start logic, fault handling (`ecu.py`: state machine OFF /
      PURGE / CRANK / IGNITION / ACCEL-TO-IDLE / IDLE / RUN / SHUTDOWN / ABORT, limiter arbitration as the transient
      model runs it, fault table). The fallbacks are transient scenarios with rules: P3 sensor lost -> N-only fuel
      schedule with the accel line x0.8 (TRN-11: p500_sched slam SM min +0.18, t95 9.4 s, T04 held at the limit);
      EGT sensor lost -> accel x0.8 and T04 limit -50 K (TRN-12: t95 8.8 s, thrust 490 N); IGV position lost ->
      failure position (TRN-10).
- [x] Exportable as tables to an actual controller (`jet ecu` -> `handoff/ecu/schedules.csv`, `limits.json`, `ecu_tables.json`, `logic.md`; the bearing abort comes from the thermal stage, the EGT limit from the design-point Tt5/T04 sensitivity)

*Pairs with §1b.*

### 11. Architecture variants
- [ ] Two-stage or mixed-flow compressor
- [ ] Radial-inflow turbine as an alternative sizing stage
*Not started (2026-09-17): the roadmap scopes these only if the tool is to go beyond the single-spool
centrifugal brief; left for a decision.*

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
