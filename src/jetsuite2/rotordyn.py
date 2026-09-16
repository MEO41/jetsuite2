"""Lateral rotordynamics of a stepped shaft with overhung wheels.

Two-plane Euler-Bernoulli beam finite elements (4 DOF per node: v, theta_z,
w, theta_y), lumped wheel masses with diametral and polar inertia, isotropic
grounded springs at the bearings and the gyroscopic coupling of the wheels.

    M q'' + Omega G q' + K q = 0

The whirl frequencies at spin speed Omega come from the state-space eigen
problem; a synchronous (forward-whirl) critical speed is a spin speed at
which a forward whirl frequency equals Omega.  ``critical_speeds`` scans
Omega and brackets the crossings, classifying the whirl direction from the
eigenvector phase at the heaviest wheel.

Verified in tests against: (1) the closed-form simply supported uniform beam,
(2) the rigid disc on a massless shaft (forward branch stiffens, backward
softens; Green's classical result).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.linalg import eig, eigh


def _element_matrices(EI, rhoA, L):
    k = EI / L ** 3 * np.array([[12, 6 * L, -12, 6 * L],
                                [6 * L, 4 * L * L, -6 * L, 2 * L * L],
                                [-12, -6 * L, 12, -6 * L],
                                [6 * L, 2 * L * L, -6 * L, 4 * L * L]])
    m = rhoA * L / 420 * np.array([[156, 22 * L, 54, -13 * L],
                                   [22 * L, 4 * L * L, 13 * L, -3 * L * L],
                                   [54, 13 * L, 156, -22 * L],
                                   [-13 * L, -3 * L * L, -22 * L, 4 * L * L]])
    return k, m


class RotorModel:
    """Assemble once, evaluate whirl frequencies at any spin speed.

    The whirl problem is solved in a modal subspace of the first ``n_modal``
    planar modes (identical in both planes), which keeps every evaluation in
    the sub-millisecond range while reproducing the low modes to < 0.1 %."""

    def __init__(self, x_nodes, EI, rhoA, masses: dict, Id: dict, Ip: dict, springs: dict, n_modal: int = 12):
        self.x = np.asarray(x_nodes, dtype=float)
        n = len(self.x)
        self.n = n
        # planar matrices (v, theta) then duplicated for (w, -theta_y) -> use identical sign convention
        Kp = np.zeros((2 * n, 2 * n))
        Mp = np.zeros((2 * n, 2 * n))
        for e in range(n - 1):
            L = self.x[e + 1] - self.x[e]
            k, m = _element_matrices(EI[e], rhoA[e], L)
            idx = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
            Kp[np.ix_(idx, idx)] += k
            Mp[np.ix_(idx, idx)] += m
        for node, mv in masses.items():
            Mp[2 * node, 2 * node] += mv
        for node, iv in Id.items():
            Mp[2 * node + 1, 2 * node + 1] += iv
        for node, kv in springs.items():
            Kp[2 * node, 2 * node] += kv
        # full 4n system: DOF order [plane y (v, th_z) ... , plane z (w, th_y) ...]
        Z = np.zeros_like(Kp)
        self.K = np.block([[Kp, Z], [Z, Kp]])
        self.M = np.block([[Mp, Z], [Z, Mp]])
        G = np.zeros((4 * n, 4 * n))
        for node, ip in Ip.items():
            a, b = 2 * node + 1, 2 * n + 2 * node + 1      # theta_z (plane y), theta_y (plane z)
            G[a, b] += ip
            G[b, a] -= ip
        self.G = G
        self.Ip = Ip
        self.springs = dict(springs)
        self.Mp, self.Kp = Mp, Kp
        self.wheel_node = max(masses, key=masses.get) if masses else 0
        # modal reduction basis (mass-normalised planar modes, both planes)
        w2, phi = eigh(Kp, Mp)
        order = np.argsort(w2)
        keep = order[: min(n_modal, len(order))]
        self.phi = phi[:, keep]                       # (2n, m)
        m = self.phi.shape[1]
        Z2 = np.zeros((2 * n, m))
        self.phi4 = np.block([[self.phi, Z2], [Z2, self.phi]])   # (4n, 2m)
        self.Kr = self.phi4.T @ self.K @ self.phi4
        self.Mr = self.phi4.T @ self.M @ self.phi4
        self.Gr = self.phi4.T @ self.G @ self.phi4
        self.Mr_inv = np.linalg.inv(self.Mr)

    # ------------------------------------------------------------ analysis
    def static_frequencies(self, n_modes=6):
        """Non-rotating natural frequencies [rad/s] (planar problem)."""
        w2 = eigh(self.Kp, self.Mp, eigvals_only=True)
        w2 = np.sort(w2[w2 > 1e-6])
        return np.sqrt(w2[:n_modes])

    def whirl(self, omega_spin: float, n_modes=8):
        """Whirl frequencies at spin speed [rad/s]: list of (freq, forward: bool)."""
        nr = self.Kr.shape[0]
        A = np.zeros((2 * nr, 2 * nr))
        A[:nr, nr:] = np.eye(nr)
        A[nr:, :nr] = -self.Mr_inv @ self.Kr
        A[nr:, nr:] = -self.Mr_inv @ (omega_spin * self.Gr)
        lam, vec_r = eig(A)
        vec = self.phi4 @ vec_r[:nr, :]        # back to physical DOFs (displacement part)
        out = []
        wn = self.wheel_node
        for i in range(len(lam)):
            f = lam[i].imag
            if f <= 1e-6:
                continue
            V = vec[2 * wn, i]                 # v at the wheel
            W = vec[2 * self.n + 2 * wn, i]    # w at the wheel
            if abs(V) < 1e-14 and abs(W) < 1e-14:
                V = vec[2 * wn + 1, i]
                W = vec[2 * self.n + 2 * wn + 1, i]
            # whirl sense from the phase between the two planes at the wheel; the sign is fixed by
            # the gyroscopic convention in G and verified by test_gyroscopic_forward_branch_stiffens
            forward = (np.conj(V) * W).imag < 0
            # strain-energy fraction in the bearing springs: ~1 for rigid-body modes, ~0 for shaft bending
            q = vec[:, i]
            e_tot = float(np.real(np.conj(q) @ self.K @ q))
            e_spr = float(sum(kv * (abs(q[2 * nd]) ** 2 + abs(q[2 * self.n + 2 * nd]) ** 2)
                              for nd, kv in self.springs.items()))
            frac = e_spr / e_tot if e_tot > 0 else 0.0
            out.append((float(f), bool(forward), frac))
        out.sort()
        # de-duplicate conjugate pairs (already filtered by f > 0) and near-identical entries
        ded = []
        for f, fw, fr in out:
            if ded and abs(f - ded[-1][0]) < 1e-6 * max(f, 1.0):
                continue
            ded.append((f, fw, fr))
        return ded[:n_modes]

    def critical_speeds(self, omega_max: float, n_scan: int = 40, forward_only: bool = True):
        """Synchronous critical speeds [rad/s] below omega_max by scanning and bisection."""
        omegas = np.linspace(omega_max / n_scan, omega_max, n_scan)
        prev = None
        crits = []
        for om in omegas:
            modes = self.whirl(om)
            g = [(f - om, fw, fr) for f, fw, fr in modes]
            if prev is not None:
                for i in range(min(len(g), len(prev))):
                    if prev[i][0] > 0 >= g[i][0]:
                        # bracket [om_prev, om]; bisection on the i-th sorted mode
                        lo, hi = om - omegas[1] + omegas[0], om
                        for _ in range(25):
                            mid = 0.5 * (lo + hi)
                            mm = self.whirl(mid)
                            if i >= len(mm):
                                break
                            if mm[i][0] - mid > 0:
                                lo = mid
                            else:
                                hi = mid
                        mh = self.whirl(hi)
                        f_at, fw_at, fr_at = mh[i] if i < len(mh) else (hi, g[i][1], g[i][2])
                        if fw_at or not forward_only:
                            crits.append((float(0.5 * (lo + hi)), bool(fw_at), float(fr_at)))
            prev = g
        crits.sort()
        return crits
