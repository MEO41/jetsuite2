# Geometry kernel evaluation: CadQuery/OCCT vs PicoGK

Decision: **CadQuery 2.8 / OCCT 7.9 (B-rep)**, carrying forward the constructions proven in
boomsonic_v0 with a rewritten, faster impeller.  PicoGK was prototyped and measured, not
dismissed on paper.

## PicoGK 2.3.0 prototype (dotnet 10, win-x64)

Test: impeller-like body — hub of revolution (360-segment mesh) + 12 main + 12 splitter blades
built as voxel shells of camber-surface meshes, boolean-added, meshed and written to STL.
Scratch project: `PicoProbe` (Program.cs kept in the session scratchpad).

| voxel size | booleans | total (incl. mesh + STL) | triangles | STL size | kernel memory |
|---|---|---|---|---|---|
| 0.50 mm | 1.0 s | 3.9 s | 1.39 M | 70 MB | 90 MB |
| 0.25 mm | 1.2 s | 13.6 s | 5.58 M | 279 MB | 328 MB |
| 0.15 mm | 2.3 s | 56.4 s | 15.5 M | 775 MB | 964 MB |

(The reported volumes at the finer voxel sizes were inconsistent because the probe's hub mesh
was not watertight at the axis; that is a probe defect, not a kernel one, and does not affect
the conclusions below.)

Observations:

* Booleans are fast and never fail — the voxel representation has no topology to break.
* Output is **mesh only** (STL / CLI / VDB).  No B-rep, no STEP, no analytic faces.  A
  manufacturable assembly with catalogue hardware (bearing seats, threads, O-ring grooves,
  press fits) needs exact cylinders, planes and dimensions, which a voxel model can only
  approximate to the voxel size.
* Dimensional accuracy is bounded by the voxel size: 0.15 mm is coarser than a bearing fit
  (H6/k5 ~ 0.01 mm) and the 0.25 mm impeller tip clearance; going finer is cubic in memory.
* File sizes at useful resolution are 10–50x the equivalent STEP.
* C#/.NET toolchain beside a Python analysis stack — a second runtime for one stage.

PicoGK is the right tool for additive-manufacturing-oriented organic geometry (lattices,
heat exchangers, blended manifolds).  It is not the right tool for a parametric,
dimension-driven, STEP-delivered engine assembly.

## CadQuery / OCCT measurements (this suite, 500 N design, laptop)

| item | time | notes |
|---|---|---|
| impeller (hub + 8 main + 8 splitter B-spline blades, single fused solid) | ~10 s | v0: ~10 min via pyturbo-aero + wedge intersect |
| NGV ring (16 vanes fused to two rings) | 3 s | |
| turbine wheel (25 blades fused to the disc) | 2.4 s | |
| combustor liners with ~60 hole cuts, dome, vaporisers, igniter | 0.6 s | |
| all other revolved parts + hardware | < 0.1 s each | |
| interference checks (11 pairs) | ~10 s | |
| assembly STEP (33 MB) + GLB export | ~40 s | skipped when nothing changed |
| unchanged rebuild | 0 s | per-part `.brep` cache |

Robustness practices carried from v0: every boolean is volume-checked; blade solids must have
exactly 6 faces and positive volume or the builder raises; a failed fuse falls back to a
sequential fuse and then to a compound (reported, never silent); planar-section lofts for
turbine blades; radial trailing edge and buried root row for the impeller blades.

## Not evaluated

build123d (same OCCT kernel, different OCP build — v0 found it cannot share the CadQuery env),
FreeCAD (heavier runtime, same kernel), OpenVSP (aircraft-oriented).
