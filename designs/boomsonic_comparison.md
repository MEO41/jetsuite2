# jetsuite2 vs boomsonic_v0 — same requirement, independent designs

Source of the boomsonic numbers: `boomsonic_v0/docs/design_freeze.md` (Phase 5 snapshot,
2026-09-14) plus `docs/phase3r_centrifugal.md`, `docs/phase4r_centrifugal.md`.
All jetsuite2 numbers are from the runs below; nothing is quoted from memory.

## Design point taken from boomsonic

| | |
|---|---|
| net thrust | 500 N |
| condition | M 1.02, 5000 m ISA |
| T04 | 1150 K |
| OPR | 4.0 |
| efficiencies ("fielded" level) | η_c 0.70, η_t 0.75, η_b 0.95 |
| intake recovery | 0.9695 (boomsonic: normal shock 0.99999 × 3.05 % duct loss) |
| combustor loss | dP/P 0.05 |

boomsonic's ≤25 kg MTOW airframe constraint has no counterpart in jetsuite2 (no airframe
stage), so it is not part of this comparison. boomsonic's engine result was 6.85 kg
calibrated / 5.70 kg raw bottom-up, OD 187 × 426 mm.

## The four runs

| design | what is pinned |
|---|---|
| `bs_reqs` | **only** 500 N / M 1.02 / 5 km. Everything else is jetsuite2's own choice. |
| `bs_cycle` | + boomsonic's cycle (OPR, T04, fielded efficiencies, intake recovery). Hardware auto. |
| `bs_conv` | `bs_cycle` after `jet converge` — cycle efficiencies driven to jetsuite2's own component estimates. |
| `bs_full` | `bs_cycle` + boomsonic's frozen hardware choices: 75 000 rpm, 15° backsweep, 12+12 blades, 19 diffuser vanes, r3/r2 1.06, r4/r2 1.35, 34 NGV / 28 rotor, boreless impeller, 32 × 25.6 mm shaft, 12 mm journals, soft mounts 1.75e6 N/m, 150 mm liner. |

```
jet rules -d designs/<name> --all      jet report -d designs/<name>
```

---

## 1. The cycle agrees almost exactly; the flow and TSFC do not

At boomsonic's own cycle inputs (`bs_cycle` / `bs_full`), every station lands on boomsonic's:

| station | boomsonic | jetsuite2 | Δ |
|---|---|---|---|
| Tt2 / Pt2 | 309 K / 102.1 kPa | 309.0 K / 101.5 kPa | −0.6 % |
| Tt3 / Pt3 | 520 K / 408 kPa | 520.9 K / 406.2 kPa | +0.2 % / −0.4 % |
| Pt4 | 388 kPa | 385.8 kPa | −0.6 % |
| Tt5 | 972 K | 968.1 K | −0.4 % |
| turbine PR (tt) | 2.60 | 2.66 | +2.4 % |
| **airflow** | **1.326 kg/s** | **1.409 kg/s** | **+6.3 %** |
| **TSFC** | **0.164 kg/N/h** | **0.182 kg/N/h** | **+10.9 %** |
| nozzle A8 | 70.8 cm² | 80.6 cm² | +13.8 % |

**The entire airflow gap is secondary-loss bookkeeping that boomsonic's pyCycle model does
not carry.** Re-running the same cycle with `nozzle_Cv=1, nozzle_Cd=1, bleed_frac=0,
dp_jetpipe=0, eta_mech=1, power_offtake_W=0`:

| | airflow | specific thrust | NPR |
|---|---|---|---|
| jetsuite2, default losses | 1.409 kg/s | 355 N·s/kg | 2.629 |
| jetsuite2, losses removed | **1.291 kg/s** | **387 N·s/kg** | **2.743** |
| boomsonic | 1.326 kg/s | 377 N·s/kg | 2.760 |

With the losses off, jetsuite2 is 2.6 % *better* than boomsonic on specific thrust and
reproduces the nozzle pressure ratio to 0.6 %. So the 6 % is: nozzle Cv 0.98 and Cd 0.97,
1 % compressor bleed, 2 % jet-pipe loss, 0.99 mechanical efficiency, 100 W offtake.
**Whether boomsonic's 500 N is really achievable depends on whether those losses exist in
its engine** — they almost certainly do, which means boomsonic's 1.326 kg/s is optimistic
and its 187 mm engine is undersized for 500 N by roughly that margin.

The remaining TSFC gap is fuel-air ratio: boomsonic Wf/W = 0.0172, jetsuite2 0.0179
(+4.2 %) for the same 520.9 → 1150 K rise at η_b 0.95. jetsuite2 uses a Walsh & Fletcher
enthalpy balance with LHV 43.124 MJ/kg. Worth chasing — 4 % of fuel flow is 4 % of sortie
fuel in boomsonic's 25 kg budget. (Note boomsonic's freeze table quotes far 0.0163, which
does not reconcile with its own 0.0228 / 1.326 = 0.0172.)

---

## 2. The fork: spool speed

This is where the two designs part company, and it drives everything else.

| | boomsonic | jetsuite2 (`bs_reqs` / `bs_conv`) |
|---|---|---|
| design speed | 75 000 rpm | 62 500 / 62 000 rpm |
| what sets it | inducer shroud M_rel 1.29 (fielded band 1.10–1.33) | **turbine disc bore stress** (`binding_limit = turbine_disc`) |
| inducer M_rel achieved | 1.29 | 1.06 |

jetsuite2's speed stage checks four limits — inducer Mach, turbine blade AN², **turbine disc
bore stress**, bearing DN — and takes the lowest. In *every* run the turbine disc is binding.
At 62 500 rpm the disc limit is 64 572 rpm: only 3 % of headroom. The inducer Mach limit
would have allowed ~78 000 rpm.

**boomsonic never evaluated the turbine disc.** Its axisymmetric FE solver
(`scripts/phase3_cycle/impeller_stress.py`, `phase4_turbomachinery/axisym_fe.py`) was run on
the *impeller* only; the Phase 4 stress gate covers impeller disc, burst and blade roots. The
turbine's only structural constraint in boomsonic is `r_tip_stress_limit` — a blade-root
stress cap on tip radius. Disc bore stress, rim creep and turbine burst margin are not in
`design_freeze.md` and not in the scripts. jetsuite2's MECH-5/6/7 cover them and they are
what caps its speed.

Whether jetsuite2's disc model is right is a separate question — but this is a real coverage
gap in boomsonic, not a modelling difference.

---

## 3. Compressor: the two tools agree, once the speed is matched

Forcing 75 000 rpm (`bs_full`) brings the compressors close together:

| | boomsonic | jetsuite2 `bs_full` | Δ |
|---|---|---|---|
| impeller D2 | 134.0 mm | 130.1 mm | −2.9 % |
| tip speed U2 | 525 m/s | 511 m/s | −2.7 % |
| eye tip / hub radius | 49.7 / 17.4 mm | 51.8 / 18.1 mm | +4.3 % |
| diffuser exit radius r4 | ~93.3 mm | 87.8 mm | −5.9 % |
| exducer root thickness | 2.24 mm | 3.61 mm | +61 % |
| exducer root stress at MCS | 618 MPa (= Fty) | 559 MPa (= its allowable) | sized to limit in both |
| **stage η_tt estimate** | **0.817 TurboFlow / 0.803 turbo-design** | **0.794** | within 1.5–2.3 pts |
| engine OD | 187 mm | 178 mm | −5 % |
| engine length | 426 mm | 413 mm | −3 % |

jetsuite2's independent compressor efficiency estimate (0.794–0.807 across the runs) sits
inside the spread of boomsonic's two independent tools. That is a genuine cross-validation:
three codes, three methods, agreeing on a single-stage centrifugal at PR 4.

The exducer root is the notable exception: jetsuite2 wants 3.61 mm where boomsonic froze
2.24 mm. Both size the root so that its peak stress equals the minimum yield at MCS, so this
is a difference in the bending model, not in the criterion. jetsuite2's
`blade_load_relief = 0.8` is documented as calibrated on boomsonic's own verified Morley
plate FE (618 vs 780 MPa), so the models are meant to agree — the 61 % gap is worth a look.
It matters: a 3.6 mm root blocks materially more exit area than 2.24 mm, which is exactly the
failure mode that killed boomsonic's 30° impeller in the Phase 4 gate.

At 75 000 rpm jetsuite2 also flags, as warnings, things boomsonic's frozen design is living
with: inducer M_rel 1.331 (over its 1.30 limit), diffusion ratio W1s/W2 = 2.58 against a 2.0
practice limit, throat choke margin 7.8 % against 10 %, exit Mach 1.045 at the diffuser
leading edge. boomsonic acknowledged the choke margin (A3R.5) and the Mach number; the
diffusion ratio is not discussed in its reports.

---

## 4. Turbine: the substantive disagreement

**The allowables agree to three figures. The geometry does not.**

jetsuite2's blade-root allowable is 436 MPa (IN713LC min(yield, creep) at 1030 K) with a 1.25
margin → **348.8 MPa** permitted. boomsonic sized its tip radius to **350 MPa**
("conceptual allowable, A3.2"). Same number.

Feeding boomsonic's own wheel (r_tip 61.1 mm, r_hub 37.1 mm) through jetsuite2's stress
relation σ = k_taper·ρ·ω²·(r_t²−r_h²)/2:

| | stress |
|---|---|
| boomsonic wheel at 75 000 rpm (100 %) | **348.9 MPa** — reproduces boomsonic's 350 MPa exactly |
| boomsonic wheel at 78 750 rpm (MCS, 105 %) | **384.6 MPa** — 10 % over the allowable |
| jetsuite2 `bs_full` wheel at MCS | 569.3 MPa — 63 % over |

Two separate causes:

**(a) boomsonic sized the blade root at 100 % speed; jetsuite2 sizes at 105 % MCS.** That
alone is +10 %. boomsonic applies 105 % to the *impeller* ("the Phase 3R impeller is
stress-sized at 105 % speed") but not to the turbine. That looks like an inconsistency inside
boomsonic, not a difference of opinion.

**(b) jetsuite2 needs a 48 % larger turbine annulus** — 109.6 cm² vs 74.0 cm² — for the same
duty. Only ~5 % is the higher airflow from §1. The rest is axial velocity: jetsuite2 holds
φ = 0.65 and rotor-exit Mach ≤ 0.6 (TURB-9); boomsonic's TurboFlow design implies φ ≈ 1.0.
Sweeping φ on `bs_full`:

| φ | annulus | r_tip | hub/tip | exit M3 | root stress at MCS |
|---|---|---|---|---|---|
| 0.65 (default) | 109.6 cm² | 70.1 mm | 0.540 | 0.462 | 569 MPa |
| 0.80 | 94.0 cm² | 67.9 mm | 0.592 | 0.573 | 488 MPa |
| 0.95 | 85.7 cm² | 65.7 mm | 0.607 | 0.671 | 445 MPa |
| 1.05 | 82.2 cm² | 64.4 mm | 0.607 | 0.732 | 427 MPa |
| boomsonic | **74.0 cm²** | **61.1 mm** | **0.607** | — | 349 @100 % / 385 @MCS |

Even at φ = 1.05 — exit Mach 0.73, far outside jetsuite2's 0.5–0.8 φ band and past its
exit-Mach rule — jetsuite2 still wants a 5 % larger radius and is 22 % over the root-stress
allowable. **jetsuite2 does not believe boomsonic's turbine passes this flow at 75 000 rpm.**

Consequences in `bs_full`: TURB-5 (root stress), TURB-3 (hub/tip 0.540 below 0.55), MECH-5
(disc bore 874 vs 631 MPa), MECH-6 (rim creep 672 vs 616 MPa), MECH-7 (burst ratio 0.976 vs
1.20 required) all FAIL, and AN² is 6.80e7 against a 4.5e7 uncooled-wheel ceiling.

Turbine efficiency: jetsuite2 estimates η_tt 0.876–0.899. boomsonic's TurboFlow gives 0.933–0.936.
That is a 4–6 point disagreement — larger than the compressor disagreement and in the
direction that flatters boomsonic.

---

## 5. What jetsuite2 comes up with on its own

`bs_conv` is jetsuite2's self-consistent answer at boomsonic's OPR/T04 — `jet converge` drove
the cycle efficiencies to its own component estimates (η_c 0.803, η_t 0.874 after 5 passes).
`bs_reqs` (requirements only, jetsuite2 defaults) lands in the same place.

| | boomsonic | jetsuite2 `bs_conv` |
|---|---|---|
| η_c / η_t used | 0.70 / 0.75 ("fielded", calibrated to vendor TSFC) | 0.803 / 0.874 (converged to its own estimates) |
| spool speed | 75 000 rpm | 62 000 rpm |
| airflow | 1.326 kg/s | 1.147 kg/s |
| TSFC | 0.164 kg/N/h | 0.154 kg/N/h |
| impeller D2 | 134 mm | 159 mm |
| turbine tip dia | 122 mm | 131 mm |
| engine OD × L | 187 × 426 mm | 222 × 398 mm |
| dry mass | 6.85 kg calibrated (5.70 raw) | 9.35 kg (8.78 raw parts + accessories allowance) |
| verdict | — | warn (COMP-7 choke margin −12 %, MECH-7 burst +4 %) |

**jetsuite2's engine is 19 % larger in diameter and heavier.** For boomsonic's airframe that
matters: its own sensitivity is ~3 N of dash margin per mm of engine diameter, and 35 mm of
extra diameter plus ~2.5 kg would eat a large part of the +54.7 % nominal dash margin and
probably all of the +21.8 % worst corner.

Note the efficiency question cuts both ways. boomsonic's "fielded" 0.70/0.75 came from
matching commercial micro-turbojet TSFC, i.e. it is an *engine-level* calibration. jetsuite2
flags 0.70/0.75 as inconsistent with its own aero (COMP-12 fails at 0.063, TURB-10 at 0.123)
and will not leave them there. If boomsonic's calibration is right, jetsuite2's TSFC of
0.154 is optimistic by ~7 %. If jetsuite2's aero is right, boomsonic is carrying 6 % more air
than it needs. The two positions are not reconciled by either tool.

Running jetsuite2 *at* the fielded efficiencies with everything else auto (`bs_cycle`) gives
the worst of both: 49 500 rpm, D2 216 mm, OD 300 mm, 17.0 kg. That design would not fit
boomsonic's airframe at all.

---

## 6. Mass

jetsuite2's mass is a bottom-up sum of the same geometry that drives its CAD, with no
calibration factor (6 % + 0.05 kg for fasteners/fittings/wiring). The right comparison is
against boomsonic's **raw** 5.70 kg, not the ×1.20-calibrated 6.85 kg.

| part | boomsonic raw | jetsuite2 `bs_full` |
|---|---|---|
| impeller | 0.92 | 1.08 |
| outer casing | 0.73 | 0.95 |
| combustor liners | 0.54 | 0.80 |
| shaft | 0.58 | 0.44 |
| **turbine disc / wheel** | **0.28** (0.43 with blades, per Phase 4R) | **1.55** |
| NGV ring | not listed separately | 0.78 |
| total | 5.70 | 8.07 (+0.53 accessories = 8.60) |

Most of the gap is the turbine wheel — 3.6× heavier even against boomsonic's 0.43 kg bladed
figure, from a wheel only 15 % larger in radius. One of the two mass models is wrong here,
and jetsuite2's has the advantage that its volume is the volume that gets cut in CAD.
boomsonic's ×1.20 calibration to JetCat P400 / AMT Nike partly hides this by construction.

---

## 7. Things boomsonic has that jetsuite2 does not

Flagging these so the comparison is not read as a scoreboard:

* **Surge margin.** boomsonic's top open risk (4.1) and its most valuable result: the
  peak-of-characteristic surrogate fails by an order of magnitude against NASA HECC measured
  data, because neither meanline tool models vaned-diffuser stall. jetsuite2 has no surge
  prediction at all and correctly does not pretend to (CLAUDE.md states this).
* **Rotor dynamics under API 684/617** with damped supports, gyroscopic stiffening and a
  verified ROSS model. jetsuite2's ROT-3 is a simpler forward-whirl separation check. The two
  disagree, but *not* on identical hardware — see below.
* **Blade vibration** (exducer mode 1 crossing 19-vane passing at idle — boomsonic risk 4.4).
  No jetsuite2 equivalent.
* **Off-design deck, transient acceleration, mission fuel, airframe closure.** jetsuite2 is
  on-design only.
* **Cantera real-gas check** at the combustor exit.

---

## 7a. Rotor dynamics: the gyroscopic stiffening ratio

`bs_full` pins boomsonic's shaft (32 × 25.6 mm tube, 12 mm journals) and support stiffness
(1.75e6 N/m), but the bearing *span* is jetsuite2's own layout output, so this is not a
like-for-like comparison:

| | boomsonic | jetsuite2 `bs_full` |
|---|---|---|
| bearing span | 192 mm | 161 mm |
| rotor mass | 2.11 kg | 2.63 kg (impeller 1.08 + turbine 1.55) |
| polar inertia Ip | 2.13e-3 kg·m² | 4.09e-3 kg·m² (1.51e-3 + 2.57e-3) |
| first bending, **at rest** | 34 000 rpm | 26 891 rpm |
| forward-whirl **synchronous crossing** | 105 600 rpm | 161 509 rpm |
| stiffening ratio | 3.1× | 6.0× |
| margin over MCS | +34 % (criterion 25.8 %) | +105 % |

The static modes are in the same family (jetsuite2 lower, consistent with 25 % more overhung
mass on a shorter span). The divergence is in the **gyroscopic stiffening ratio, 6.0× vs
3.1×** — and jetsuite2 has 1.9× boomsonic's polar inertia, mostly from its much heavier
turbine wheel (§6), which is exactly what drives forward-whirl stiffening. So the two are not
necessarily contradictory; a large part of the gap may simply be the turbine mass
disagreement propagating.

The **span sensitivity agrees in sign and roughly in slope**, which is reassuring. Lengthening
the combustor in `bs_full` (which lengthens the rotor, as boomsonic's did):

| liner | span | forward crossing | margin |
|---|---|---|---|
| 139.9 mm | 161.4 mm | 161 509 rpm | 2.05 |
| 140.5 mm | 162.0 mm | 160 492 rpm | 2.04 |
| 150.0 mm | 171.5 mm | 145 501 rpm | 1.85 |

−16 krpm per +10 mm of span, against boomsonic's −9 krpm per +11 mm. Both tools agree the
bearings barely participate (jetsuite2 puts 0.26 % of that mode's spring energy in the
supports; boomsonic 4 %), so dampers cannot help it — the same conclusion boomsonic reached.

(Side note: at L/H 2.2 and 2.8 jetsuite2 gives the same 139.9 mm liner, because the
residence-time criterion is binding there, not the length/height ratio.)

So the disagreement is not a span artifact. It is the absolute level, and the polar-inertia
difference is the leading candidate. What it does mean is that **jetsuite2's comfortable
+105 % margin is not independent confirmation of boomsonic's layout** — settle the turbine
wheel mass first.

---

## 8. Where I would look first

1. **Turbine wheel mass 1.55 vs 0.43 kg.** It propagates into polar inertia, rotor dynamics
   and the mass budget, and it is the largest single discrepancy in the whole comparison.
2. **Turbine disc stress and burst.** boomsonic has no analysis here; jetsuite2 says it is the
   binding speed limit in every run. If jetsuite2 is right, 75 000 rpm is not available and
   boomsonic's 134 mm impeller grows.
3. **Turbine annulus, φ ≈ 1.0 vs 0.65.** A 48 % area disagreement on a component both tools
   claim to have designed at meanline.
4. **The 6 % airflow / nozzle-loss question.** Cheapest to settle: add Cv, Cd, bleed and
   jet-pipe loss to boomsonic's pyCycle model and see whether 500 N still closes at 1.326 kg/s.
5. **Turbine efficiency 0.876 vs 0.936.**
6. **Exducer root 3.61 vs 2.24 mm**, where jetsuite2's model is supposedly calibrated on
   boomsonic's own FE.
7. **Forward-whirl stiffening ratio 6.0× vs 3.1×** (§7a) — likely downstream of (1), but
   confirm rather than assume.
