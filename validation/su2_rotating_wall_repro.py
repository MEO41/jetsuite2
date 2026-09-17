"""Minimal rotating-frame energy-balance check for SU2 8.5 (win64), the reference case behind the gated impeller CFD ingest
(ROADMAP section 5, docs/validation.md "Impeller passage CFD").

A straight duct 0.1 x 0.02 x 0.02 m (41 x 13 x 13 nodes, hexahedra) rotating about x, Euler solver, slip walls on the four
sides (planes that move normal to themselves in the rotating frame), inlet total conditions, static-pressure outlet,
uniform axial start, Roe / MUSCL.  check.py prints the mass-weighted Euler work (omega * d(r C_theta) / cp), the measured
total-temperature rise and the isentropic rise for the total-pressure ratio.  With this build at 7592 rad/s the three agree
within about 10 % once converged (3,600 iterations: 11.7 / 13.1 / 12.1 K) while the wall rows sit +/- 100 K off the interior;
the bladed impeller passage on its H-mesh misses 15-25 % of its Euler work in the energy equation even when converged, which is
why no impeller efficiency is ingested.  AUSM+-up2 must not be used: it drives the wall rows of this duct to 5-18,000 K.

    python validation/su2_rotating_wall_repro.py <out_dir>      # writes duct.su2, duct.cfg, check.py
    cd <out_dir> && SU2_CFD duct.cfg && python check.py         # balances and wall-row temperatures
"""
import sys
from pathlib import Path

import numpy as np

out = Path(sys.argv[1] if len(sys.argv) > 1 else "su2_rotating_wall_repro")
out.mkdir(parents=True, exist_ok=True)
NI, NJ, NK = 41, 13, 13
xs, ys, zs = np.linspace(0, 0.1, NI), np.linspace(0, 0.02, NJ), np.linspace(0, 0.02, NK)
ids = np.arange(NI * NJ * NK).reshape(NI, NJ, NK)
nodes = [(x, y, z) for x in xs for y in ys for z in zs]
H = [[ids[i, j, k], ids[i + 1, j, k], ids[i + 1, j + 1, k], ids[i, j + 1, k], ids[i, j, k + 1], ids[i + 1, j, k + 1], ids[i + 1, j + 1, k + 1], ids[i, j + 1, k + 1]]
     for i in range(NI - 1) for j in range(NJ - 1) for k in range(NK - 1)]
qi = lambda i: [[ids[i, j, k], ids[i, j + 1, k], ids[i, j + 1, k + 1], ids[i, j, k + 1]] for j in range(NJ - 1) for k in range(NK - 1)]
qj = lambda j: [[ids[i, j, k], ids[i + 1, j, k], ids[i + 1, j, k + 1], ids[i, j, k + 1]] for i in range(NI - 1) for k in range(NK - 1)]
qk = lambda k: [[ids[i, j, k], ids[i + 1, j, k], ids[i + 1, j + 1, k], ids[i, j + 1, k]] for i in range(NI - 1) for j in range(NJ - 1)]
M = {"INLET": qi(0), "OUTLET": qi(NI - 1), "WALL_Y0": qj(0), "WALL_Y1": qj(NJ - 1), "WALL_Z0": qk(0), "WALL_Z1": qk(NK - 1)}
with open(out / "duct.su2", "w") as f:
    f.write(f"NDIME= 3\nNELEM= {len(H)}\n")
    for e, h in enumerate(H):
        f.write("12 " + " ".join(map(str, h)) + f" {e}\n")
    f.write(f"NPOIN= {len(nodes)}\n")
    for n, (x, y, z) in enumerate(nodes):
        f.write(f"{x:.9e} {y:.9e} {z:.9e} {n}\n")
    f.write(f"NMARK= {len(M)}\n")
    for k, q in M.items():
        f.write(f"MARKER_TAG= {k}\nMARKER_ELEMS= {len(q)}\n")
        for qq in q:
            f.write("9 " + " ".join(map(str, qq)) + "\n")
(out / "duct.cfg").write_text("""SOLVER= EULER
MATH_PROBLEM= DIRECT
RESTART_SOL= NO
SYSTEM_MEASUREMENTS= SI
GRID_MOVEMENT= ROTATING_FRAME
MOTION_ORIGIN= 0.0 0.0 0.0
ROTATION_RATE= -7592.1822 0.0 0.0
MACH_NUMBER= 0.3
AOA= 0.0
FREESTREAM_PRESSURE= 99298.5
FREESTREAM_TEMPERATURE= 288.15
REF_DIMENSIONALIZATION= DIMENSIONAL
INIT_OPTION= TD_CONDITIONS
FREESTREAM_OPTION= TEMPERATURE_FS
FLUID_MODEL= IDEAL_GAS
GAMMA_VALUE= 1.4
GAS_CONSTANT= 287.058
MARKER_EULER= ( WALL_Y0, WALL_Y1, WALL_Z0, WALL_Z1 )
MARKER_INLET= ( INLET, 288.15, 99298.5, 1.0, 0.0, 0.0 )
MARKER_OUTLET= ( OUTLET, 89000.0 )
MARKER_MONITORING= ( WALL_Y0 )
MARKER_ANALYZE= ( INLET, OUTLET )
MARKER_ANALYZE_AVERAGE= MASSFLUX
NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CFL_NUMBER= 2.0
CFL_ADAPT= NO
ITER= 3000
LINEAR_SOLVER= FGMRES
LINEAR_SOLVER_PREC= ILU
LINEAR_SOLVER_ERROR= 1E-4
LINEAR_SOLVER_ITER= 25
MGLEVEL= 0
CONV_NUM_METHOD_FLOW= ROE
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.05
TIME_DISCRE_FLOW= EULER_IMPLICIT
CONV_FIELD= RMS_DENSITY
CONV_RESIDUAL_MINVAL= -10
MESH_FILENAME= duct.su2
MESH_FORMAT= SU2
OUTPUT_FILES= ( CSV )
RESTART_FILENAME= restart_duct.csv
VOLUME_FILENAME= flow
CONV_FILENAME= history
OUTPUT_WRT_FREQ= 3000
SCREEN_OUTPUT= ( INNER_ITER, RMS_DENSITY, SURFACE_MASSFLOW, SURFACE_TOTAL_TEMPERATURE )
SCREEN_WRT_FREQ_INNER= 500
""")
(out / "check.py").write_text("""import numpy as np
w = 7592.1822
d = np.loadtxt("restart_duct.csv", delimiter=",", skiprows=1); d = d[np.argsort(d[:, 0].astype(int))]
X = d[:, 1:4]; rho = d[:, 4]; mom = d[:, 5:8]; E = d[:, 8]; V = mom / rho[:, None]; V2 = (V ** 2).sum(1)
p = 0.4 * (E - 0.5 * rho * V2); T = p / (287.058 * rho); Tt = T + V2 / 2009.0
r = np.hypot(X[:, 1], X[:, 2]); ct = (V[:, 2] * X[:, 1] - V[:, 1] * X[:, 2]) / np.maximum(r, 1e-9)
NI, NJ, NK = 41, 13, 13; ids = np.arange(NI * NJ * NK).reshape(NI, NJ, NK)
def st(i):
    F = s_rc = s_Tt = s_pt = 0.0
    for j in range(NJ - 1):
        for k in range(NK - 1):
            q = [ids[i, j, k], ids[i, j + 1, k], ids[i, j + 1, k + 1], ids[i, j, k + 1]]; pts = X[q]
            n = 0.5 * np.cross(pts[2] - pts[0], pts[3] - pts[1]); f = abs(np.dot(mom[q].mean(0), n))
            F += f; s_rc += (r[q] * ct[q]).mean() * f; s_Tt += Tt[q].mean() * f; s_pt += (p[q] * (Tt[q] / T[q]) ** 3.5).mean() * f
    return F, s_rc / F, s_Tt / F, s_pt / F
Fi, rci, Tti, pti = st(0); Fo, rco, Tto, pto = st(NI - 1)
inner = T[ids[10:31, 2:11, 2:11]]; walls = np.r_[T[ids[10:31, 0, :]].ravel(), T[ids[10:31, -1, :]].ravel(), T[ids[10:31, :, 0]].ravel(), T[ids[10:31, :, -1]].ravel()]
print(f"mass flow {Fi:.4f} in / {Fo:.4f} out kg/s")
print(f"Euler work {abs(w * (rco - rci)) / 1004.5:.2f} K, measured dTt {Tto - Tti:.2f} K, isentropic dTt for PR {pto / pti:.4f}: {Tti * ((pto / pti) ** (1 / 3.5) - 1):.2f} K")
print(f"interior T {inner.min():.0f}..{inner.max():.0f} K, wall rows {walls.min():.0f}..{walls.max():.0f} K")
""")
print(f"written {out}/duct.su2, duct.cfg, check.py")
