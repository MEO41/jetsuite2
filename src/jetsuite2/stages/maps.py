"""Analysis stage - component maps from the mean-line loss models (L2).

Generates the compressor map (speed lines with surge and choke limits) and
the turbine map (mass flow / efficiency vs pressure ratio per speed line) for
the current geometry, writes PNG plots into ``<design>/analysis/`` and
reports the design-point surge margin, the loss breakdown and the
consistency between the L2 loss-model efficiency and the L1 estimate.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..perf import closs, tloss, maps as pmaps
from ..rules import check
from .common import inp, out

TIER = "L2"
CORE = False

DEFAULTS = {
    "speed_fractions": [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.05, 1.1],
    "points_per_line": 22,
    "slip_model": "wiesner",
    "plots": True,
    "_doc": {
        "speed_fractions": "corrected speed fractions of the design speed for both maps",
        "points_per_line": "mass-flow points per compressor speed line",
        "slip_model": "wiesner | stanitz | stodola | busemann (used in the loss model)",
        "plots": "write PNG map plots into <design>/analysis/",
    },
}

READS = ["inputs.maps.*", "outputs.compressor.*", "outputs.turbine.*", "outputs.speed.rpm",
         "outputs.cycle.Tt2_K", "outputs.cycle.Pt2_Pa", "outputs.cycle.W_kg_s", "outputs.cycle.T04_K",
         "outputs.cycle.Pt4_Pa", "outputs.cycle.far", "outputs.cycle.W4_kg_s", "outputs.cycle.Pt5_Pa",
         "outputs.cycle.turbine_PR_tt", "outputs.cycle.eta_c_assumed", "outputs.cycle.eta_t_assumed",
         "outputs.cycle.OPR"]


def run(doc: dict) -> dict:
    m = lambda k: inp(doc, "maps", k, DEFAULTS[k])  # noqa: E731
    c, t = out(doc, "compressor"), out(doc, "turbine")
    rpm = out(doc, "speed", "rpm")
    T01, P01, W = out(doc, "cycle", "Tt2_K"), out(doc, "cycle", "Pt2_Pa"), out(doc, "cycle", "W_kg_s")
    T04, P04, far, W4 = out(doc, "cycle", "T04_K"), out(doc, "cycle", "Pt4_Pa"), out(doc, "cycle", "far"), out(doc, "cycle", "W4_kg_s")
    fr = [float(x) for x in m("speed_fractions")]
    gc = closs.CompressorGeometry.from_outputs(c)
    gc.slip_model = str(m("slip_model"))
    gt = tloss.TurbineGeometry.from_outputs(t, far)
    cmap = pmaps.compressor_map(gc, rpm, T01, P01, N_fracs=fr, n_pts=int(m("points_per_line")))
    tmap = pmaps.turbine_map(gt, rpm, T04, P04, N_fracs=fr)
    if not cmap["lines"] or not tmap["lines"]:
        raise RuntimeError("map generation produced no valid speed lines")
    # design-point evaluation with the loss model
    dp = closs.evaluate(gc, W, rpm * 2 * math.pi / 60, T01, P01)
    CM = pmaps.CompressorMap(cmap)
    Wc = pmaps.corr_flow(W, T01, P01)
    Nf = 1.0
    sm = CM.surge_margin(Nf, Wc, dp.PR_tt) if dp.ok else float("nan")
    w0, pr0, _ = CM.point(Nf, 0.0)
    wch, _, _ = CM.point(Nf, 1.0)
    # turbine design point
    P5 = out(doc, "cycle", "Pt5_Pa")
    tp = tloss.evaluate(gt, rpm * 2 * math.pi / 60, T04, P04, P5 * 0.93)
    opr = float(out(doc, "cycle", "OPR"))
    # plots
    ddir = doc.get("_design_dir")
    plots = {}
    if bool(m("plots")) and ddir:
        plots = _plot(cmap, tmap, Path(ddir) / "analysis", dp, Wc)
    rules = [
        check("MAP-1", "design-point surge margin (loss-model map, SAE definition)", sm, 0.15, "min",
              f"stall indicators in perf.closs; uncertainty +/-{100*closs.SURGE_UNCERTAINTY:.0f} % of the margin",
              note="more backsweep, larger vaneless gap, fewer / lower-solidity diffuser vanes, or a lower running line"),
        check("MAP-2", "design-point choke margin (flow to choke / design flow - 1)", wch / Wc - 1.0 if Wc else None, 0.08, "min",
              "inducer / diffuser throat choke on the design speed line", note="open the inducer or diffuser throat"),
        check("MAP-3", "L2 loss-model compressor efficiency vs L1 estimate |diff|",
              abs(dp.eta_tt - c["eta_tt_est"]) if dp.ok else None, 0.04, "max", "consistency between fidelity tiers",
              hard=False, note=f"L2 {dp.eta_tt:.3f} vs L1 {c['eta_tt_est']:.3f}: consider `jet ingest` of the L2 value or check inputs"),
        check("MAP-4", "L2 loss-model turbine efficiency vs L1 estimate |diff|",
              abs(tp.eta_tt - t["eta_tt_est"]) if tp.ok else None, 0.05, "max", "consistency between fidelity tiers",
              hard=False, note=f"L2 {tp.eta_tt if tp.ok else float('nan'):.3f} vs L1 {t['eta_tt_est']:.3f}"),
        check("MAP-5", "design-point vaned-diffuser incidence", dp.incidence_vd if dp.ok else None, 4.0, "max",
              "vane stall onset ~ +4-6 deg (Japikse)", hard=False),
        check("MAP-6", "compressor loss-model PR at design vs cycle OPR |diff|/OPR",
              abs(dp.PR_tt - opr) / opr if dp.ok else None,
              0.06, "max", "the sized geometry should deliver the cycle pressure ratio within the loss-model accuracy",
              hard=False, note=f"loss model PR {dp.PR_tt if dp.ok else float('nan'):.3f} vs cycle OPR {opr:.3f}"),
    ]
    return dict(compressor_map=cmap, turbine_map=tmap, design_point=dict(
        ok=dp.ok, PR=dp.PR_tt, eta=dp.eta_tt, incidence=dp.incidence, incidence_vd=dp.incidence_vd, M2=dp.M2,
        alpha3=dp.alpha3, D_f=dp.D_f, de_haller=dp.de_haller, stall=dp.stall, losses_J_kg=dp.losses, W_corr=Wc,
        surge_margin=sm, surge_W_corr=w0, surge_PR=pr0, choke_W_corr=wch, surge_reason=cmap["lines"][-1]["surge_reason"]),
        turbine_design_point=dict(ok=tp.ok, W=tp.W, PR_tt=tp.PR_tt, PR_ts=tp.PR_ts, eta_tt=tp.eta_tt, eta_ts=tp.eta_ts,
                                  M2=tp.M2, M3_rel=tp.M3_rel, incidence=tp.incidence, choked=tp.choked, losses=tp.losses),
        plots=plots, _rules=rules)


def _opr(doc):
    return out(doc, "cycle", "W_kg_s") * 0 + doc["outputs"]["cycle"]["OPR"]


def _plot(cmap, tmap, adir: Path, dp, Wc) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    adir.mkdir(parents=True, exist_ok=True)
    out_ = {}
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    sx, sy = [], []
    for l in cmap["lines"]:
        ax[0].plot(l["W_corr"], l["PR"], "-", lw=1.2, label=f"{l['N_frac']:.2f}")
        ax[1].plot(l["W_corr"], l["eta"], "-", lw=1.2)
        sx.append(l["surge_W_corr"]); sy.append(l["surge_PR"])
    ax[0].plot(sx, sy, "r--", lw=1.5, label="surge line")
    if dp.ok:
        ax[0].plot([Wc], [dp.PR_tt], "ko", ms=6, label="design")
        ax[1].plot([Wc], [dp.eta_tt], "ko", ms=6)
    ax[0].set_xlabel("corrected flow [kg/s]"); ax[0].set_ylabel("PR total-total"); ax[0].grid(alpha=.3); ax[0].legend(fontsize=7, ncol=2)
    ax[1].set_xlabel("corrected flow [kg/s]"); ax[1].set_ylabel("eta tt"); ax[1].set_ylim(0.4, 0.9); ax[1].grid(alpha=.3)
    fig.suptitle("Compressor map (mean-line loss model, L2)")
    p = adir / "compressor_map.png"; fig.tight_layout(); fig.savefig(p, dpi=110); plt.close(fig)
    out_["compressor_map"] = str(p)
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    for l in tmap["lines"]:
        ax[0].plot(l["PR_ts"], l["W_corr"], "-", lw=1.2, label=f"{l['N_frac']:.2f}")
        ax[1].plot(l["PR_ts"], l["eta_tt"], "-", lw=1.2)
    ax[0].set_xlabel("PR total-static"); ax[0].set_ylabel("corrected flow [kg/s]"); ax[0].grid(alpha=.3); ax[0].legend(fontsize=7, ncol=2)
    ax[1].set_xlabel("PR total-static"); ax[1].set_ylabel("eta tt"); ax[1].set_ylim(0.3, 1.0); ax[1].grid(alpha=.3)
    fig.suptitle("Turbine map (mean-line AMDC/KO loss model, L2)")
    p = adir / "turbine_map.png"; fig.tight_layout(); fig.savefig(p, dpi=110); plt.close(fig)
    out_["turbine_map"] = str(p)
    return out_
