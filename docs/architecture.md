# Architecture

## Goals (from the brief) and how they are met

| requirement | mechanism |
|---|---|
| modular stages with explicit contracts | one module per stage: `DEFAULTS` (inputs + docs), `READS` (exact state paths consumed), `run(doc) -> outputs + _rules` |
| bidirectional, low-latency iteration | in-process pure-numpy physics (~0.4 s whole chain); value-hash invalidation; versioned state with diff/checkout |
| fast, robust parametric CAD | CadQuery/OCCT B-rep, revolved profiles + B-spline blades, volume-checked booleans, per-part cache |
| standard component library | JSON catalogues (bearings, rings, screws, nuts, O-rings, igniter, probe, seals) + materials with T-dependent allowables |
| design-principle fidelity | 70+ rule checks with sources, limits and remedies; auto speed selection from the binding physical limit |

## State and invalidation

`design.json` holds `inputs.<stage>`, `outputs.<stage>`, `stamps.<stage>` and `rules.<stage>`.
A stage's input hash is the canonical hash (sorted keys, 12-significant-digit floats) of the
values at its `READS` paths.  `StageGraph.run` re-executes a stage only when its hash differs
from the stamp.  Consequences:

* editing prose, reordering keys or re-running an upstream stage to identical numbers does not
  cascade (jetsuite F2/F3 lesson);
* a stage that produces the same outputs as before leaves its downstream untouched;
* `jet set` reports "directly affected" (hash changed) vs "will re-run" (transitively pending).

Every `set`, `run`, `converge`, `checkout` bumps the version and snapshots the full document
(`history/vNNNN.json`, a few tens of kB).  `diff` is a field-level comparison of snapshots.

## Stage sequence and contracts

| stage | reads | key outputs |
|---|---|---|
| requirements | its inputs | ambient / ram conditions |
| cycle | requirements | W, Wf, TSFC, stations, dh_c, dh_t, A8 |
| speed | cycle, material inputs | rpm from min(inducer Mach, turbine AN², turbine disc, bearing DN) |
| compressor | cycle, speed | inducer, impeller, exducer root (stress-sized), diffuser, efficiency estimate |
| turbine | cycle, speed | mean-line triangles, annulus, counts, chords, stress, efficiency estimate |
| combustor | cycle, compressor, turbine, speed | annulus, liner, holes, vaporisers |
| layout | compressor, turbine, combustor, cycle | axial stations, bearing positions, envelope |
| rotor | layout, speed, compressor, turbine, combustor | shaft, bearing (library), DN, forward criticals (gyroscopic) |
| mechanical | compressor, turbine, rotor | disc/burst/root stresses, retention |
| geometry | everything | geometry sheet in mm per part group with hashes; masses; hardware picks |

The impeller hub profile, turbine disc profile and shaft profile are generated once in
`geomlib.py` and used both for mass/inertia/stress and for the CAD revolve, so analysis and
geometry cannot drift.

## Efficiency closure

The cycle takes efficiency *assumptions*; compressor and turbine produce *estimates*
(Casey-Robinson-type peak curve with Reynolds and clearance corrections; Smith chart fit with
clearance, Reynolds and trailing-edge penalties).  Rules COMP-12 / TURB-10 flag inconsistency;
`jet converge` iterates (under-relaxed) until both agree.  This keeps the graph acyclic while
making the coupling explicit.

## Spool speed

`speed` computes four rpm limits from the cycle alone (inducer relative Mach at the
minimum-Mach shroud radius; turbine blade root AN² with the material creep allowable; turbine
disc bore stress; bearing DN with the journal the torque and stiffness rules require) and takes
97 % of the binding one.  A material change therefore moves the speed, and the speed moves
every diameter — the "different material, different impeller" loop from the brief runs in one
`jet set --run`.

## CAD

`cad/build.py` keys each builder on the hash of the sheet groups it reads, stores `.brep`
solids in `cad/cache`, exports STEP per part and rebuilds the coloured assembly only when a part
changed.  Assembly-level checks intersect critical part pairs and report `CLASH` lines.
Impeller blades: camber surface from a blade-angle law integrated along streamlines, radial
trailing edge, thickness taper, B-spline suction/pressure surfaces, ruled caps, sewn, root row
buried 0.6 mm in the hub, single multi-tool fuse with sequential fallback.  Turbine/NGV blades:
ruled lofts of planar sections (v0's robust construction).

## Lessons applied from the prior efforts

* v0: proven revolve/loft constructions kept; volume-check every boolean; the impeller took
  10 min through pyturbo-aero — replaced by an own camber law (10 s).
* jetsuite: no subprocess per stage, no multi-venv, no four-ring architecture; cache keys over
  values; failures never exit 0; documentation budgeted against code.
