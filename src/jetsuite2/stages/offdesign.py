"""Analysis stage - steady-state off-design matching on the component maps (L2).

Solves the running line from idle to maximum speed at the design flight
condition (fuel is the control, T04 follows), reports surge margin, thrust,
TSFC, EGT and turbine inlet temperature along it, identifies the idle point
(thrust ~ 3 % of max) and the maximum-thrust point (T04 or N limited), and
plots the running line on the compressor map.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..perf import matching, closs
from ..rules import check
from .. import uncertainty as unc
from .common import inp, out

TIER = "L2"
CORE = False

DEFAULTS = {
    "N_fractions": [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05],
    "N_max_frac": 1.05,
    "idle_thrust_frac": 0.03,
    "plots": True,
    "_doc": {"N_fractions": "spool speed fractions for the running line", "N_max_frac": "mechanical speed limit / design speed",
             "idle_thrust_frac": "idle defined at this fraction of maximum thrust", "plots": "write running-line plot"},
}

READS = ["inputs.offdesign.*", "inputs.cycle.*", "outputs.maps.compressor_map", "outputs.maps.turbine_map",
         "outputs.speed.rpm", "outputs.cycle.*", "outputs.requirements.altitude_m", "outputs.requirements.mach",
         "outputs.requirements.dT_isa_K", "outputs.rotor.Ip_impeller", "outputs.rotor.Ip_turbine", "outputs.control.*"]


class _D:  # minimal adapter so EngineModel.from_design can read a doc
    def __init__(self, doc):
        self.doc = doc
    def outputs(self):
        return self.doc["outputs"]


def engine_from_doc(doc: dict) -> matching.EngineModel:
    return matching.EngineModel.from_design(_D(doc))


def run(doc: dict) -> dict:
    o = lambda k: inp(doc, "offdesign", k, DEFAULTS[k])  # noqa: E731
    E = engine_from_doc(doc)
    req = out(doc, "requirements")
    amb = matching.Ambient.at(req["altitude_m"], req["mach"], req["dT_isa_K"])
    fr = [float(x) for x in o("N_fractions")]
    line = matching.running_line(E, amb, fr)
    conv = [p for p in line if p["converged"]]
    # ghost line: the same engine without bleed / nozzle / IGV schedules (what the schedules buy)
    ghost = []
    if E.sched is not None and any(E.sched.enabled.values()):
        E_u = matching.EngineModel(**{**E.__dict__, "sched": E.sched.unscheduled()})
        ghost = [dict(N_frac=p["N_frac"], Fn=p["Fn"], SM=p["SM"], PR_c=p["PR_c"], W_corr=p["W_corr"], T04=p["T04"], converged=p["converged"])
                 for p in matching.running_line(E_u, amb, fr)]
    if len(conv) < 3:
        raise RuntimeError(f"running line did not converge ({len(conv)}/{len(line)} points)")
    mx = matching.max_power_point(E, amb, E.T04_max, float(o("N_max_frac")), x0=conv[-1]["x"])
    F_max = mx["Fn"] if mx.get("converged") else conv[-1]["Fn"]
    # idle: lowest speed whose thrust >= idle fraction of max (interpolate)
    idle_F = float(o("idle_thrust_frac")) * F_max
    Ns = np.array([p["N_frac"] for p in conv]); Fs = np.array([p["Fn"] for p in conv])
    idle_N = float(np.interp(idle_F, Fs, Ns)) if Fs.min() < idle_F < Fs.max() else float(Ns.min())
    idle = matching.solve_steady(E, amb, idle_N * E.N_design, conv[0]["x"])
    table = [dict(N_frac=p["N_frac"], N_rpm=p["N"], Fn=p["Fn"], TSFC_kg_N_h=p["TSFC"] * 3600, W=p["W"], PR_c=p["PR_c"],
                  eta_c=p["eta_c"], eta_t=p["eta_t"], T04=p["T04"], EGT=p["EGT"], SM=p["SM"], Wf=p["Wf"], beta=p["beta"],
                  W_corr=p["W_corr"], Nc_frac=p["Nc_frac"], choked=p["choked"], converged=p["converged"],
                  bleed=p.get("bleed_handling", 0.0), A8=p.get("A8"), igv_deg=p.get("igv_deg", 0.0)) for p in line]
    sm_min = min(p["SM"] for p in conv)
    p_min = min(conv, key=lambda p: p["SM"])
    sm_min_N = p_min["N_frac"]
    N_min_map = float(E.cmap.N.min()) if hasattr(E.cmap, "N") else 0.0
    band_min = unc.surge_band(igv=unc.igv_term(E.cmap, p_min["Nc_frac"], p_min["W_corr"], p_min["PR_c"], p_min.get("igv_deg", 0.0)),
                              lowspeed=p_min["Nc_frac"] < N_min_map - 1e-9)
    band_idle = unc.surge_band(igv=unc.igv_term(E.cmap, idle["Nc_frac"], idle["W_corr"], idle["PR_c"], idle.get("igv_deg", 0.0)),
                               lowspeed=idle["Nc_frac"] < N_min_map - 1e-9) if idle["converged"] else band_min
    ddir = doc.get("_design_dir")
    plots = _plot(doc, table, mx, Path(ddir) / "analysis") if bool(o("plots")) and ddir else {}
    cyc = out(doc, "cycle")
    rules = [
        unc.annotate_rule(check("OD-1", "minimum surge margin along the running line", sm_min, 0.10, "min",
              f"SAE margin from the L2 map at N {sm_min_N:.2f}; band +/-{band_min['total']:.3f} = {unc.format_terms(band_min)}",
              warn_margin=band_min["total"] / 0.10,
              note="lower the running line (larger nozzle), more backsweep, or a bleed / variable geometry"), band_min),
        check("OD-2", "max-thrust point recovers the design thrust", F_max / cyc["W_kg_s"] / (req["thrust_N"] / cyc["W_kg_s"]),
              0.95, "min", "map-based matching vs design-point cycle (consistency)", hard=False,
              note=f"max thrust {F_max:.0f} N vs design {req['thrust_N']:.0f} N ({mx.get('limit')}-limited)"),
        check("OD-3", "idle speed fraction", idle_N, 0.35, "min", "micro-turbojet idle 30-40 % (JetCat 33-35 %)", hard=False),
        unc.annotate_rule(check("OD-4", "idle surge margin", idle["SM"] if idle["converged"] else None, 0.08, "min",
              f"low-speed operability (boomsonic_v0 risk 4.2); band +/-{band_idle['total']:.3f} = {unc.format_terms(band_idle)}",
              hard=False, warn_margin=band_idle["total"] / 0.08), band_idle),
    ]
    return dict(ambient=dict(T0=amb.T0, P0=amb.P0, M0=amb.M0), running_line=table,
                max_point=dict(N_frac=mx["N"] / E.N_design, Fn=mx["Fn"], T04=mx["T04"], TSFC_kg_N_h=mx["TSFC"] * 3600,
                               SM=mx["SM"], EGT=mx["EGT"], W=mx["W"], PR_c=mx["PR_c"], limit=mx.get("limit"), converged=mx.get("converged")),
                idle=dict(N_frac=idle_N, Fn=idle["Fn"], T04=idle["T04"], SM=idle["SM"], Wf=idle["Wf"], converged=idle["converged"]),
                SM_min=sm_min, SM_min_N_frac=sm_min_N, SM_min_band=band_min, idle_band=band_idle, unscheduled_line=ghost,
                steady_schedule=dict(N=[p["N"] / E.N_design for p in conv], WfP3=[p["Wf"] / p["Pt3"] for p in conv],
                                     T04=[p["T04"] for p in conv], Wf=[p["Wf"] for p in conv], x=[list(map(float, p["x"])) for p in conv]),
                schedules_enabled=(E.sched.enabled if E.sched is not None else {}), plots=plots, _rules=rules)


def _plot(doc, table, mx, adir: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    adir.mkdir(parents=True, exist_ok=True)
    cmap = doc["outputs"]["maps"]["compressor_map"]
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    sx, sy = [], []
    for l in cmap["lines"]:
        ax[0].plot(l["W_corr"], l["PR"], "-", color="0.6", lw=1)
        sx.append(l["surge_W_corr"]); sy.append(l["surge_PR"])
    ax[0].plot(sx, sy, "r--", label="surge line")
    ok = [p for p in table if p["converged"]]
    gh = [p for p in (doc["outputs"].get("offdesign", {}).get("unscheduled_line") or []) if p["converged"]]
    if gh:
        ax[0].plot([p["W_corr"] for p in gh], [p["PR_c"] for p in gh], "-", color="0.4", lw=1, alpha=0.6, label="unscheduled (ghost)")
    ax[0].plot([p["W_corr"] for p in ok], [p["PR_c"] for p in ok], "b-o", ms=3, label="running line (scheduled)")
    ax[0].set_xlabel("corrected flow [kg/s]"); ax[0].set_ylabel("PR"); ax[0].grid(alpha=.3); ax[0].legend()
    ax[1].plot([p["N_frac"] for p in ok], [p["Fn"] for p in ok], "k-", label="thrust [N]")
    ax[1].set_xlabel("N / N_design"); ax[1].set_ylabel("thrust [N]"); ax[1].grid(alpha=.3)
    ax2 = ax[1].twinx()
    ax2.plot([p["N_frac"] for p in ok], [100 * p["SM"] for p in ok], "r-", label="SM [%]")
    ax2.plot([p["N_frac"] for p in ok], [p["T04"] for p in ok], "m--", label="T04 [K]")
    ax2.set_ylabel("SM [%] / T04 [K]"); ax2.legend(loc="center left")
    fig.suptitle("Running line at the design flight condition (L2 matching)")
    p = adir / "running_line.png"; fig.tight_layout(); fig.savefig(p, dpi=110); plt.close(fig)
    return {"running_line": str(p)}
