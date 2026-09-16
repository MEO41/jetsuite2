"""Analysis stage - flight envelope (L2): maximum-thrust performance over
altitude, Mach and ambient-temperature deviation on the component maps.

At every grid point the engine runs at the highest speed that respects the
T04 and N limits (fuel-controlled); thrust lapse, TSFC, spool speed, turbine
inlet temperature, EGT and surge margin are tabulated, and the operability
envelope (points where a steady solution exists with SM above the floor)
is reported.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..perf import matching
from ..rules import check
from .common import inp, out
from .offdesign import engine_from_doc

TIER = "L2"
CORE = False

DEFAULTS = {
    "altitudes_m": [0, 1500, 3000, 5000, 7000, 9000],
    "machs": [0.0, 0.3, 0.6, 0.8],
    "dT_isa_K": [-20, 0, 20, 35],
    "N_max_frac": 1.05,
    "SM_floor": 0.08,
    "plots": True,
    "_doc": {"altitudes_m": "altitude grid", "machs": "flight Mach grid", "dT_isa_K": "ambient temperature deviations",
             "N_max_frac": "mechanical speed limit / design speed", "SM_floor": "minimum surge margin for a cleared point",
             "plots": "write envelope plots"},
}

READS = ["inputs.envelope.*", "inputs.cycle.*", "outputs.maps.compressor_map", "outputs.maps.turbine_map",
         "outputs.speed.rpm", "outputs.cycle.*", "outputs.requirements.thrust_N", "outputs.rotor.Ip_impeller",
         "outputs.rotor.Ip_turbine"]


def run(doc: dict) -> dict:
    e = lambda k: inp(doc, "envelope", k, DEFAULTS[k])  # noqa: E731
    E = engine_from_doc(doc)
    alts = [float(a) for a in e("altitudes_m")]
    machs = [float(m) for m in e("machs")]
    dTs = [float(d) for d in e("dT_isa_K")]
    Nmax = float(e("N_max_frac"))
    floor = float(e("SM_floor"))
    grid = []
    x0 = None
    for dT in dTs:
        for M in machs:
            for alt in alts:
                amb = matching.Ambient.at(alt, M, dT)
                try:
                    r = matching.max_power_point(E, amb, E.T04_max, Nmax, x0=x0)
                except Exception as ex:  # noqa: BLE001
                    grid.append(dict(alt=alt, M=M, dT=dT, ok=False, reason=f"{type(ex).__name__}"))
                    continue
                ok = bool(r.get("converged"))
                if ok:
                    x0 = r["x"]
                grid.append(dict(alt=alt, M=M, dT=dT, ok=ok, limit=r.get("limit"), N_frac=r["N"] / E.N_design, Fn=r["Fn"],
                                 TSFC_kg_N_h=r["TSFC"] * 3600, T04=r["T04"], EGT=r["EGT"], SM=r["SM"], W=r["W"],
                                 PR_c=r["PR_c"], Nc_frac=r["Nc_frac"], cleared=ok and r["SM"] >= floor))
    ok_pts = [g for g in grid if g["ok"]]
    sls = next((g for g in ok_pts if g["alt"] == 0 and g["M"] == 0 and g["dT"] == 0), None)
    F_sls = sls["Fn"] if sls else float("nan")
    worst = min(ok_pts, key=lambda g: g["SM"]) if ok_pts else None
    cleared = [g for g in grid if g.get("cleared")]
    ddir = doc.get("_design_dir")
    plots = _plot(grid, alts, machs, Path(ddir) / "analysis") if bool(e("plots")) and ddir else {}
    F_req = out(doc, "requirements", "thrust_N")
    rules = [
        check("ENV-1", "fraction of envelope grid points cleared (converged, SM >= floor)", len(cleared) / max(len(grid), 1), 0.9, "min",
              f"SM floor {floor:.2f}; L2 maps", hard=False, note="see the envelope table for the failing corners"),
        check("ENV-2", "worst-case surge margin over the envelope", worst["SM"] if worst else None, floor, "min",
              f"at alt {worst['alt'] if worst else '-'} m, M {worst['M'] if worst else '-'}, dT {worst['dT'] if worst else '-'} K",
              note="hot-day / high-Mach corners load the compressor: consider a variable nozzle or bleed"),
        check("ENV-3", "sea-level static max thrust vs design thrust", F_sls / F_req if sls else None, 0.95, "min",
              "envelope max-power point at SLS (T04- or N-limited)", hard=False),
    ]
    return dict(grid=grid, n_points=len(grid), n_converged=len(ok_pts), n_cleared=len(cleared), F_sls=F_sls,
                worst_SM=(worst["SM"] if worst else None), worst_point=worst, plots=plots, _rules=rules)


def _plot(grid, alts, machs, adir: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    adir.mkdir(parents=True, exist_ok=True)
    g0 = [g for g in grid if g["ok"] and g["dT"] == 0]
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    for M in machs:
        pts = sorted([g for g in g0 if g["M"] == M], key=lambda g: g["alt"])
        if not pts:
            continue
        ax[0].plot([p["alt"] for p in pts], [p["Fn"] for p in pts], "-o", ms=3, label=f"M {M}")
        ax[1].plot([p["alt"] for p in pts], [p["TSFC_kg_N_h"] for p in pts], "-o", ms=3)
        ax[2].plot([p["alt"] for p in pts], [100 * p["SM"] for p in pts], "-o", ms=3)
    ax[0].set_ylabel("max thrust [N]"); ax[1].set_ylabel("TSFC [kg/N/h]"); ax[2].set_ylabel("surge margin [%]")
    for a in ax:
        a.set_xlabel("altitude [m]"); a.grid(alpha=.3)
    ax[0].legend(fontsize=8)
    fig.suptitle("Flight envelope, ISA (L2 matching, T04 / N limited)")
    p = adir / "envelope.png"; fig.tight_layout(); fig.savefig(p, dpi=110); plt.close(fig)
    return {"envelope": str(p)}
