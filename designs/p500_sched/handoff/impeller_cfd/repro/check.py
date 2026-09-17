import numpy as np
d = np.loadtxt("restart_duct.csv", delimiter=",", skiprows=1); d = d[np.argsort(d[:, 0].astype(int))]
rho = d[:, 4]; V = d[:, 5:8] / rho[:, None]; E = d[:, 8]; p = 0.4 * (E - 0.5 * rho * (V ** 2).sum(1)); T = p / (287.058 * rho)
NI, NJ, NK = 41, 13, 13; ids = np.arange(NI * NJ * NK).reshape(NI, NJ, NK)
inner = T[ids[10:31, 2:11, 2:11]]; walls = np.r_[T[ids[10:31, 0, :]].ravel(), T[ids[10:31, -1, :]].ravel(), T[ids[10:31, :, 0]].ravel(), T[ids[10:31, :, -1]].ravel()]
print(f"interior T {inner.min():.0f}..{inner.max():.0f} K (mean {inner.mean():.1f});  wall rows T {walls.min():.0f}..{walls.max():.0f} K")
print("defect present" if walls.max() > 400 or walls.min() < 200 else "clean")
