"""Component maps generated from the mean-line loss models, plus the
beta-line interpolation the matching code uses.

Corrected quantities (SAE ARP 1210 conventions, reference 288.15 K / 101325 Pa):
    W_corr = W sqrt(theta) / delta,  N_corr = N / sqrt(theta),  theta = T0/288.15, delta = P0/101325.
Speed lines are stored as fractions of the design corrected speed.
"""
from __future__ import annotations

import math

import numpy as np

from . import closs, tloss

T_REF, P_REF = 288.15, 101325.0


def corr_flow(W, T0, P0):
    return W * math.sqrt(T0 / T_REF) / (P0 / P_REF)


def phys_flow(Wc, T0, P0):
    return Wc / math.sqrt(T0 / T_REF) * (P0 / P_REF)


# ---------------------------------------------------------------- compressor
def compressor_map(g: closs.CompressorGeometry, N_design: float, T01_design: float, P01_design: float,
                   N_fracs=(0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.05, 1.1), n_pts: int = 22, verbose=None,
                   igv_deg: float = 0.0) -> dict:
    """Map at the design inlet conditions expressed in corrected terms (one IGV setting)."""
    lines = []
    Nc_design = N_design / math.sqrt(T01_design / T_REF)
    for f in N_fracs:
        omega = f * N_design * 2 * math.pi / 60
        if verbose:
            verbose(f"  compressor speed line {f:.2f} (igv {igv_deg:.0f} deg)")
        sl = closs.speedline(g, omega, T01_design, P01_design, n_pts=n_pts, igv_deg=igv_deg)
        if not sl.get("ok"):
            continue
        # keep from choke down to the surge point (plus two points beyond for interpolation stability)
        Ws = np.array(sl["W"]); PR = np.array(sl["PR"]); eta = np.array(sl["eta"])
        keep = Ws >= 0.6 * sl["surge_W"]     # keep the stalled region too: the matching may run there and must report SM < 0
        Ws, PR, eta = Ws[keep], PR[keep], eta[keep]
        order = np.argsort(Ws)
        lines.append(dict(N_frac=f, W_corr=[corr_flow(w, T01_design, P01_design) for w in Ws[order]],
                          PR=list(PR[order]), eta=list(eta[order]),
                          surge_W_corr=corr_flow(sl["surge_W"], T01_design, P01_design),
                          choke_W_corr=corr_flow(sl["choke_W"], T01_design, P01_design),
                          surge_PR=float(np.interp(sl["surge_W"], Ws[order], PR[order])),
                          surge_reason=sl["surge_reason"]))
    return dict(kind="compressor", N_corr_design=Nc_design, T_ref=T_REF, P_ref=P_REF, lines=lines, igv_deg=igv_deg,
                surge_band_SM=closs.SURGE_BAND_SM)


# ------------------------------------------------------------------ turbine
def turbine_map(g: tloss.TurbineGeometry, N_design: float, T04_design: float, P04_design: float,
                N_fracs=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1), PR_ts=None, verbose=None) -> dict:
    """Turbine map: for each speed line, mass flow and efficiency vs total-static pressure ratio.
    Corrected to the design inlet conditions (T04_design, P04_design)."""
    PR_ts = PR_ts if PR_ts is not None else list(np.linspace(1.15, 3.4, 16))
    lines = []
    for f in N_fracs:
        omega = f * N_design * 2 * math.pi / 60
        if verbose:
            verbose(f"  turbine speed line {f:.2f}")
        pts = [tloss.evaluate(g, omega, T04_design, P04_design, P04_design / pr) for pr in PR_ts]
        ok = [(pr, p) for pr, p in zip(PR_ts, pts) if p.ok]
        if len(ok) < 3:
            continue
        lines.append(dict(N_frac=f, PR_ts=[pr for pr, _ in ok], PR_tt=[p.PR_tt for _, p in ok],
                          W_corr=[p.W * math.sqrt(T04_design / T_REF) / (P04_design / P_REF) for _, p in ok],
                          eta_tt=[p.eta_tt for _, p in ok], eta_ts=[p.eta_ts for _, p in ok],
                          choked=[bool(p.choked) for _, p in ok]))
    return dict(kind="turbine", N_corr_design=N_design / math.sqrt(T04_design / T_REF), T_ref=T_REF, P_ref=P_REF,
                T04_design=T04_design, P04_design=P04_design, lines=lines)


# ---------------------------------------------------------- interpolation
class CompressorMap:
    """Beta-line interpolation: beta = 0 at surge, 1 at choke, on each speed line."""

    def __init__(self, m: dict):
        self.m = m
        self.N = np.array([l["N_frac"] for l in m["lines"]])
        self.lines = m["lines"]
        self.Nc_design = m["N_corr_design"]

    @staticmethod
    def _interp_extrap(x, xs, ys):
        """np.interp with linear extrapolation at both ends (the stored lines end near choke and
        in the stalled region; the matching must still return a continuous value beyond)."""
        if x <= xs[0]:
            if len(xs) > 1:
                return ys[0] + (ys[1] - ys[0]) / (xs[1] - xs[0]) * (x - xs[0])
            return ys[0]
        if x >= xs[-1]:
            if len(xs) > 1:
                return ys[-1] + (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) * (x - xs[-1])
            return ys[-1]
        return float(np.interp(x, xs, ys))

    def _line_at_beta(self, line, beta):
        W = np.array(line["W_corr"]); PR = np.array(line["PR"]); eta = np.array(line["eta"])
        Ws, Wc = line["surge_W_corr"], line["choke_W_corr"]
        w = Ws + beta * (Wc - Ws)
        return w, float(self._interp_extrap(w, W, PR)), float(max(self._interp_extrap(w, W, eta), 0.2))

    def point(self, N_frac: float, beta: float, igv: float = 0.0):   # igv ignored: single-setting map
        """(W_corr, PR, eta) at corrected speed fraction and beta (beta < 0 = stalled region, extrapolated)."""
        N_frac = float(np.clip(N_frac, self.N.min(), self.N.max()))
        beta = float(np.clip(beta, -0.6, 1.08))
        i = int(np.searchsorted(self.N, N_frac))
        if i == 0:
            return self._line_at_beta(self.lines[0], beta)
        if i >= len(self.N):
            return self._line_at_beta(self.lines[-1], beta)
        lo, hi = self.lines[i - 1], self.lines[i]
        t = (N_frac - self.N[i - 1]) / (self.N[i] - self.N[i - 1])
        a, b = self._line_at_beta(lo, beta), self._line_at_beta(hi, beta)
        return tuple((1 - t) * np.array(a) + t * np.array(b))

    def surge_PR_at_flow(self, N_frac: float, W_corr: float) -> tuple[float, float]:
        """Surge point (W_corr, PR) on this speed line (interpolated between lines)."""
        w0, pr0, _ = self.point(N_frac, 0.0)
        return w0, pr0

    def surge_margin(self, N_frac: float, W_corr: float, PR: float, igv: float = 0.0) -> float:
        """SAE-style surge margin at constant corrected speed: (PR_s W)/(PR W_s) - 1."""
        w0, pr0 = self.surge_PR_at_flow(N_frac, W_corr)
        return (pr0 * W_corr) / (PR * w0) - 1.0


class CompressorMapFamily:
    """Maps at several IGV settings; linear interpolation in the IGV angle."""

    def __init__(self, maps: list[dict]):
        self.maps = sorted([CompressorMap(m) for m in maps], key=lambda cm: cm.m.get("igv_deg", 0.0))
        self.igvs = np.array([cm.m.get("igv_deg", 0.0) for cm in self.maps], float)
        self.Nc_design = self.maps[0].Nc_design
        self.m = self.maps[0].m
        self.N = self.maps[0].N

    def _pair(self, igv):
        if len(self.maps) == 1 or igv <= self.igvs[0]:
            return self.maps[0], self.maps[0], 0.0
        if igv >= self.igvs[-1]:
            return self.maps[-1], self.maps[-1], 0.0
        i = int(np.searchsorted(self.igvs, igv))
        t = (igv - self.igvs[i - 1]) / (self.igvs[i] - self.igvs[i - 1])
        return self.maps[i - 1], self.maps[i], t

    def point(self, N_frac, beta, igv=0.0):
        a, b, t = self._pair(igv)
        pa, pb = a.point(N_frac, beta), b.point(N_frac, beta)
        return tuple((1 - t) * np.array(pa) + t * np.array(pb))

    def surge_margin(self, N_frac, W_corr, PR, igv=0.0):
        w0, pr0, _ = self.point(N_frac, 0.0, igv)
        return (pr0 * W_corr) / (PR * w0) - 1.0


class TurbineMap:
    def __init__(self, m: dict):
        self.m = m
        self.N = np.array([l["N_frac"] for l in m["lines"]])
        self.lines = m["lines"]

    def _line(self, line, PR_ts):
        pr = np.array(line["PR_ts"])
        pmin = float(pr.min())
        if PR_ts < pmin:
            # below the lowest mapped pressure ratio (start / windmill region): corrected flow falls toward zero
            # at PR 1 like an orifice, W ~ sqrt((PR - 1) / (PR_min - 1)); efficiency held, PR_tt -> 1
            f = math.sqrt(max(PR_ts - 1.0, 0.0) / max(pmin - 1.0, 1e-6))
            W0, eta0, prtt0 = float(line["W_corr"][int(np.argmin(pr))]), float(line["eta_tt"][int(np.argmin(pr))]), float(line["PR_tt"][int(np.argmin(pr))])
            return W0 * f, eta0, 1.0 + (prtt0 - 1.0) * max(PR_ts - 1.0, 0.0) / max(pmin - 1.0, 1e-6)
        PR_ts = float(np.clip(PR_ts, pmin, pr.max()))
        return (float(np.interp(PR_ts, pr, line["W_corr"])), float(np.interp(PR_ts, pr, line["eta_tt"])),
                float(np.interp(PR_ts, pr, line["PR_tt"])))

    def point(self, N_frac: float, PR_ts: float):
        """(W_corr, eta_tt, PR_tt) at corrected speed fraction and total-static pressure ratio."""
        N_frac = float(np.clip(N_frac, self.N.min(), self.N.max()))
        i = int(np.searchsorted(self.N, N_frac))
        if i == 0:
            return self._line(self.lines[0], PR_ts)
        if i >= len(self.N):
            return self._line(self.lines[-1], PR_ts)
        lo, hi = self.lines[i - 1], self.lines[i]
        t = (N_frac - self.N[i - 1]) / (self.N[i] - self.N[i - 1])
        a, b = self._line(lo, PR_ts), self._line(hi, PR_ts)
        return tuple((1 - t) * np.array(a) + t * np.array(b))
