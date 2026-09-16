"""Test-data correlation: ingest measured steady points (N, thrust, fuel flow,
EGT, P3, T3, airflow), compare with the model's running line
("as-designed vs as-tested"), and calibrate a small, declared set of model
coefficients by least squares while holding everything else.

Tuned coefficients (default): cycle.eta_c, cycle.eta_t, cycle.eta_b,
cycle.dp_burner, cycle.nozzle_Cd.  Each is bounded to a physically plausible
band; the report states the move of every coefficient and the residuals
before / after so the calibration is auditable.

CSV columns (SI unless noted): N_rpm, thrust_N, Wf_kg_h, EGT_K, P3_Pa, T3_K,
W_kg_s (optional), T_amb_K, P_amb_Pa.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from . import gas
from .perf import matching
from .stages.offdesign import engine_from_doc

TUNABLE = {"cycle.eta_c": (0.6, 0.9), "cycle.eta_t": (0.7, 0.93), "cycle.eta_b": (0.85, 0.995),
           "cycle.dp_burner": (0.02, 0.12), "cycle.nozzle_Cd": (0.85, 1.0)}
WEIGHTS = {"thrust_N": 1.0, "Wf_kg_h": 1.0, "EGT_K": 1.0, "P3_Pa": 1.0, "T3_K": 1.0, "W_kg_s": 1.0}


def read_test_csv(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = {}
            for k, v in r.items():
                try:
                    d[k.strip()] = float(v)
                except (TypeError, ValueError):
                    d[k.strip()] = v
            rows.append(d)
    return rows


def _predict(design, doc_inputs: dict, points: list[dict]) -> list[dict]:
    """Model prediction at each test point's speed and ambient (steady matching on the maps)."""
    import copy
    doc = copy.deepcopy(design.doc)
    for k, v in doc_inputs.items():
        st, key = k.split(".", 1)
        doc["inputs"][st][key] = v
    E = engine_from_doc(doc)
    # the cycle coefficients enter the matching model through EngineModel.from_design: rebuild with the tuned values
    ci = doc["inputs"]["cycle"]
    E.eta_b, E.dp_b, E.nozzle_Cv = float(ci["eta_b"]), float(ci["dp_burner"]), float(ci["nozzle_Cv"])
    E.A8 = design.outputs()["cycle"]["A8_geo_m2"] * float(ci["nozzle_Cd"])
    out = []
    x0 = None
    for p in points:
        amb = matching.Ambient(float(p.get("T_amb_K", 288.15)), float(p.get("P_amb_Pa", 101325.0)), 0.0)
        r = matching.solve_steady_robust(E, amb, float(p["N_rpm"]), x0)
        if r["converged"]:
            x0 = r["x"]
        out.append(dict(N_rpm=p["N_rpm"], thrust_N=r["Fn"], Wf_kg_h=r["Wf"] * 3600, EGT_K=r["EGT"], P3_Pa=r["Pt3"], T3_K=r["Tt3"],
                        W_kg_s=r["W"], T04_K=r["T04"], SM=r["SM"], converged=r["converged"]))
    return out


def compare(design, points: list[dict], inputs: dict | None = None) -> dict:
    pred = _predict(design, inputs or {}, points)
    cols = [c for c in WEIGHTS if any(c in p and isinstance(p[c], float) for p in points)]
    rows, res = [], {c: [] for c in cols}
    for p, q in zip(points, pred):
        row = dict(N_rpm=p["N_rpm"], converged=q["converged"])
        for c in cols:
            if c in p and isinstance(p[c], float):
                row[c] = dict(test=p[c], model=q[c], error=(q[c] - p[c]) / max(abs(p[c]), 1e-9))
                if q["converged"]:
                    res[c].append(row[c]["error"])
        rows.append(row)
    rms = {c: float(np.sqrt(np.mean(np.square(v)))) if v else None for c, v in res.items()}
    return dict(rows=rows, rms_rel_error=rms, columns=cols)


def calibrate(design, points: list[dict], tune: list[str] | None = None, verbose=None) -> dict:
    """Least-squares fit of the tunable coefficients to the test points; returns before/after and the moves."""
    tune = tune or list(TUNABLE)
    base = {k: float(design.doc["inputs"][k.split(".")[0]][k.split(".", 1)[1]]) for k in tune}
    before = compare(design, points)
    cols = before["columns"]
    lo = np.array([TUNABLE[k][0] for k in tune]); hi = np.array([TUNABLE[k][1] for k in tune])
    x0 = np.array([base[k] for k in tune])
    n_eval = [0]

    def resid(x):
        n_eval[0] += 1
        inputs = {k: float(v) for k, v in zip(tune, x)}
        cmp_ = compare(design, points, inputs)
        r = []
        for row in cmp_["rows"]:
            for c in cols:
                if c in row:
                    r.append(WEIGHTS[c] * row[c]["error"] if row["converged"] else 1.0)
        if verbose:
            verbose(f"  calibration eval {n_eval[0]}: rms {np.sqrt(np.mean(np.square(r))):.4f}")
        return np.array(r)

    sol = least_squares(resid, x0, bounds=(lo, hi), diff_step=0.02, max_nfev=40, xtol=1e-4, ftol=1e-4)
    tuned = {k: float(v) for k, v in zip(tune, sol.x)}
    after = compare(design, points, tuned)
    moves = {k: dict(before=base[k], after=tuned[k], change=tuned[k] - base[k], bounds=TUNABLE[k]) for k in tune}
    held = [k for k in TUNABLE if k not in tune]
    return dict(tuned=tuned, moves=moves, held=held, before=before, after=after, n_evaluations=n_eval[0], success=bool(sol.success))


def format_comparison(cmp_: dict, title: str) -> str:
    L = [title]
    cols = cmp_["columns"]
    L.append("  " + f"{'N_rpm':>8} " + " ".join(f"{c:>22}" for c in cols))
    for row in cmp_["rows"]:
        L.append("  " + f"{row['N_rpm']:>8.0f} " + " ".join(
            (f"{row[c]['test']:>8.4g}/{row[c]['model']:>8.4g} {100*row[c]['error']:+5.1f}%" if c in row else f"{'-':>22}") for c in cols)
                 + ("" if row["converged"] else "  (model unconverged)"))
    L.append("  rms relative error: " + ", ".join(f"{c} {100*v:.1f} %" for c, v in cmp_["rms_rel_error"].items() if v is not None))
    return "\n".join(L)
