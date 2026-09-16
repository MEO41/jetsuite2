"""Design-space studies on the fast chain: sweeps, DOE, multi-objective
optimisation, uncertainty quantification and sensitivity ranking.

A study runs the core chain (~0.4 s) on copies of the design's inputs, never
touching the design itself, and stores results under ``<design>/studies/``.
Every study records the hash of the base inputs it was run from (minus the
varied variables), so ``jet study list`` flags studies that are stale after
the design changed.

Optimisation: a compact NSGA-II (non-dominated sorting, crowding distance,
SBX crossover, polynomial mutation) with the design rules as constraints
(fail = infeasible; warn allowed).  Surrogate: RBF (thin-plate) with a
leave-one-out error estimate, trained on the DOE for proposing the points
worth an L2 (`jet analyze`) evaluation.  UQ: Latin-hypercube Monte Carlo
over the efficiency/loss/material/tolerance uncertainties with the
validation errors as the default model-form bands.  Sensitivity: Morris
elementary effects (screening) plus first-order Sobol indices (Saltelli)
when asked.
"""
from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path
from typing import Callable

import numpy as np
from scipy.stats import qmc

from .state import DesignStore, canonical_hash
from .state.store import get_path, set_path, flatten
from .stages import build_graph, CORE, ORDER

# ------------------------------------------------------------------ evaluation
DEFAULT_OBJECTIVES = {
    "mass_kg": "outputs.geometry.mass_total_kg",
    "TSFC": "outputs.cycle.TSFC_kg_per_N_h",
    "thrust_N": "outputs.requirements.thrust_N",
    "OD_mm": "outputs.geometry.envelope_OD_mm",
    "length_mm": "outputs.geometry.length_mm",
    "eta_c": "outputs.compressor.eta_tt_est",
    "eta_t": "outputs.turbine.eta_tt_est",
    "rpm": "outputs.speed.rpm",
    "T04": "outputs.cycle.T04_K",
    "choke_margin": "outputs.compressor.choke_margin",
    "impeller_burst": "outputs.mechanical.impeller.burst_ratio",
    "turbine_burst": "outputs.mechanical.turbine.burst_ratio",
    "bending_margin": "outputs.rotor.bending_margin",
}

# default uncertainty bands (1-sigma, relative unless noted) from the validation results and handbook scatter
DEFAULT_UQ = {
    "cycle.eta_c": {"sigma": 0.02, "kind": "abs", "source": "closs vs TurboFlow 1-3 pts; Balje band"},
    "cycle.eta_t": {"sigma": 0.03, "kind": "abs", "source": "tloss vs TurboFlow 5 pts at design"},
    "cycle.eta_b": {"sigma": 0.01, "kind": "abs", "source": "Lefebvre theta correlation"},
    "cycle.dp_burner": {"sigma": 0.01, "kind": "abs", "source": "liner loss estimate"},
    "cycle.intake_recovery": {"sigma": 0.005, "kind": "abs", "source": "bellmouth / duct"},
    "cycle.nozzle_Cv": {"sigma": 0.005, "kind": "abs", "source": "convergent nozzle practice"},
    "compressor.power_input_factor": {"sigma": 0.01, "kind": "abs", "source": "disc friction / recirculation"},
    "compressor.aero_blockage_exit": {"sigma": 0.02, "kind": "abs", "source": "two-zone wake fraction"},
    "compressor.tip_clearance_mm": {"sigma": 0.03, "kind": "abs", "source": "tolerance stack-up (RSS)"},
    "turbine.tip_clearance_mm": {"sigma": 0.03, "kind": "abs", "source": "tolerance stack-up (RSS)"},
    "mechanical.k_peak_bored": {"sigma": 0.15, "kind": "abs", "source": "disc stress concentration (conceptual factor)"},
    "mechanical.k_peak_boreless": {"sigma": 0.1, "kind": "abs", "source": "as above"},
    "compressor.blade_load_relief": {"sigma": 0.08, "kind": "abs", "source": "plate relief calibrated on one FE"},
}


class Evaluator:
    """Runs the core chain on a modified copy of the design inputs (in memory, no disk)."""

    def __init__(self, design, stages: list[str] | None = None):
        self.base = copy.deepcopy(design.doc)
        self.graph = build_graph()
        self.stages = stages or CORE

    def run(self, assignments: dict) -> dict:
        doc = copy.deepcopy(self.base)
        doc["outputs"], doc["stamps"], doc["rules"] = {}, {}, {}
        for k, v in assignments.items():
            set_path(doc, "inputs." + k, v)
        st = _MemStore(doc)
        rep = self.graph.run(st, only=self.stages, force=True)
        return dict(doc=doc, failed=dict(rep.failed), rules=doc.get("rules", {}))


class _MemStore:
    def __init__(self, doc):
        self.doc = doc

    @property
    def outputs(self):
        return self.doc.setdefault("outputs", {})

    @property
    def stamps(self):
        return self.doc.setdefault("stamps", {})


def _get(doc, path):
    v = get_path(doc, path)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else float("nan")


def _rule_summary(rules: dict) -> tuple[int, int, list[str]]:
    fails, warns, ids = 0, 0, []
    for s, rs in rules.items():
        for r in rs:
            if r["verdict"] == "fail":
                fails += 1; ids.append(r["id"])
            elif r["verdict"] == "warn":
                warns += 1
    return fails, warns, ids


def evaluate_point(ev: Evaluator, assignments: dict, objectives: dict, ignore_rules=("COMP-12", "TURB-10")) -> dict:
    t0 = time.perf_counter()
    r = ev.run(assignments)
    row = dict(inputs=assignments, elapsed_s=time.perf_counter() - t0, failed=bool(r["failed"]))
    if r["failed"]:
        row.update({k: float("nan") for k in objectives}); row["n_fail"] = 99; row["fail_ids"] = list(r["failed"])
        return row
    for k, p in objectives.items():
        row[k] = _get(r["doc"], p)
    f, w, ids = _rule_summary(r["rules"])
    ids = [i for i in ids if i not in ignore_rules]
    row["n_fail"], row["n_warn"], row["fail_ids"] = len(ids), w, ids
    return row


# ------------------------------------------------------------------ study kinds
def _base_hash(design, variables: list[str]) -> str:
    inputs = copy.deepcopy(design.doc["inputs"])
    for v in variables:
        stage, key = v.split(".", 1)
        inputs.get(stage, {}).pop(key, None)
    return canonical_hash(inputs)


def sweep(design, spec: dict, verbose=None) -> dict:
    """spec: {"variables": {"cycle.OPR": [3, 3.5, 4]}, "objectives": {...}} -- full factorial."""
    ev = Evaluator(design)
    objs = spec.get("objectives") or DEFAULT_OBJECTIVES
    vars_ = spec["variables"]
    names = list(vars_)
    grids = [list(vars_[n]) for n in names]
    rows = []
    idx = [0] * len(names)
    total = int(np.prod([len(g) for g in grids]))
    for i in range(total):
        assign = {}
        rem = i
        for j, gvals in enumerate(grids):
            assign[names[j]] = gvals[rem % len(gvals)]; rem //= len(gvals)
        rows.append(evaluate_point(ev, assign, objs))
        if verbose and (i + 1) % 10 == 0:
            verbose(f"  sweep {i+1}/{total}")
    return dict(kind="sweep", variables=vars_, objectives=list(objs), rows=rows)


def doe(design, spec: dict, verbose=None) -> dict:
    """spec: {"variables": {"cycle.OPR": [3.0, 4.5], ...}, "n": 40, "method": "lhs"|"sobol", "objectives": {...}}"""
    ev = Evaluator(design)
    objs = spec.get("objectives") or DEFAULT_OBJECTIVES
    vars_ = spec["variables"]; names = list(vars_)
    n = int(spec.get("n", 32)); method = spec.get("method", "lhs")
    lo = np.array([vars_[k][0] for k in names], float); hi = np.array([vars_[k][1] for k in names], float)
    if method == "sobol":
        m = int(math.ceil(math.log2(max(n, 2))))
        U = qmc.Sobol(d=len(names), scramble=True, seed=int(spec.get("seed", 1))).random_base2(m)[:n]
    else:
        U = qmc.LatinHypercube(d=len(names), seed=int(spec.get("seed", 1))).random(n)
    X = lo + U * (hi - lo)
    rows = []
    for i, x in enumerate(X):
        assign = {k: _cast(design, k, float(v)) for k, v in zip(names, x)}
        rows.append(evaluate_point(ev, assign, objs))
        if verbose and (i + 1) % 10 == 0:
            verbose(f"  doe {i+1}/{n}")
    res = dict(kind="doe", method=method, variables=vars_, objectives=list(objs), rows=rows)
    res["surrogate"] = fit_surrogates(res)
    return res


def _cast(design, key: str, v: float):
    """Integers stay integers (blade counts etc.)."""
    cur = get_path(design.doc, "inputs." + key)
    if isinstance(cur, int) and not isinstance(cur, bool):
        return int(round(v))
    return v


# ------------------------------------------------------------------ surrogates (RBF)
def fit_surrogates(res: dict) -> dict:
    names = list(res["variables"])
    rows = [r for r in res["rows"] if not r["failed"]]
    if len(rows) < len(names) + 3:
        return {}
    X = np.array([[r["inputs"][k] for k in names] for r in rows], float)
    lo, hi = X.min(0), X.max(0)
    Xn = (X - lo) / np.maximum(hi - lo, 1e-12)
    out = {}
    for obj in res["objectives"]:
        y = np.array([r[obj] for r in rows], float)
        if not np.all(np.isfinite(y)) or np.ptp(y) == 0:
            continue
        loo = _rbf_loo(Xn, y)
        out[obj] = dict(loo_rms_error=loo, y_range=[float(y.min()), float(y.max())], n=len(y))
    return dict(kind="rbf-thin-plate", variables=names, lo=lo.tolist(), hi=hi.tolist(), per_objective=out)


def _rbf_fit(Xn, y, smooth=1e-6):
    n = len(y)
    D = np.linalg.norm(Xn[:, None, :] - Xn[None, :, :], axis=2)
    Phi = np.where(D > 0, D ** 2 * np.log(np.maximum(D, 1e-12)), 0.0)
    P = np.c_[np.ones(n), Xn]
    A = np.block([[Phi + smooth * np.eye(n), P], [P.T, np.zeros((P.shape[1], P.shape[1]))]])
    b = np.r_[y, np.zeros(P.shape[1])]
    sol = np.linalg.lstsq(A, b, rcond=None)[0]
    return sol[:n], sol[n:]


def _rbf_predict(Xn, w, c, Xq):
    D = np.linalg.norm(Xq[:, None, :] - Xn[None, :, :], axis=2)
    Phi = np.where(D > 0, D ** 2 * np.log(np.maximum(D, 1e-12)), 0.0)
    return Phi @ w + np.c_[np.ones(len(Xq)), Xq] @ c


def _rbf_loo(Xn, y) -> float:
    errs = []
    for i in range(len(y)):
        m = np.ones(len(y), bool); m[i] = False
        w, c = _rbf_fit(Xn[m], y[m])
        errs.append(float(_rbf_predict(Xn[m], w, c, Xn[i:i + 1])[0] - y[i]))
    return float(np.sqrt(np.mean(np.square(errs))) / max(np.std(y), 1e-12))


# ------------------------------------------------------------------ NSGA-II
def optimize(design, spec: dict, verbose=None) -> dict:
    """spec: {"variables": {"cycle.OPR": [3, 4.5], ...}, "objectives": {"mass_kg": "min", "TSFC": "min"},
    "pop": 24, "generations": 15, "constraints": "rules"}"""
    ev = Evaluator(design)
    vars_ = spec["variables"]; names = list(vars_)
    lo = np.array([vars_[k][0] for k in names], float); hi = np.array([vars_[k][1] for k in names], float)
    objs = spec.get("objectives") or {"mass_kg": "min", "TSFC": "min"}
    obj_paths = {k: DEFAULT_OBJECTIVES.get(k, k) for k in objs}
    signs = np.array([1.0 if objs[k] == "min" else -1.0 for k in objs])
    pop_n, gens = int(spec.get("pop", 24)), int(spec.get("generations", 12))
    rng = np.random.default_rng(int(spec.get("seed", 3)))
    U = qmc.LatinHypercube(d=len(names), seed=int(spec.get("seed", 3))).random(pop_n)
    X = lo + U * (hi - lo)
    evaluated = []

    def eval_pop(Xp):
        F, C, rows = [], [], []
        for x in Xp:
            assign = {k: _cast(design, k, float(v)) for k, v in zip(names, x)}
            r = evaluate_point(ev, assign, obj_paths)
            f = np.array([r[k] for k in objs], float) * signs
            cv = float(r["n_fail"]) + (1e3 if r["failed"] else 0.0)
            f = np.where(np.isfinite(f), f, 1e9)
            F.append(f); C.append(cv); rows.append(r)
        return np.array(F), np.array(C), rows

    F, Cv, rows = eval_pop(X)
    evaluated += rows
    for gen in range(gens):
        ranks, crowd = _nsga_sort(F, Cv)
        # tournament selection
        idx = np.arange(len(X))
        def better(a, b):
            if ranks[a] != ranks[b]:
                return a if ranks[a] < ranks[b] else b
            return a if crowd[a] > crowd[b] else b
        parents = [better(*rng.choice(idx, 2, replace=False)) for _ in range(pop_n)]
        children = []
        for i in range(0, pop_n - 1, 2):
            c1, c2 = _sbx(X[parents[i]], X[parents[i + 1]], lo, hi, rng)
            children.append(_poly_mut(c1, lo, hi, rng)); children.append(_poly_mut(c2, lo, hi, rng))
        Xc = np.array(children)
        Fc, Cc, rows_c = eval_pop(Xc)
        evaluated += rows_c
        Xa, Fa, Ca = np.vstack([X, Xc]), np.vstack([F, Fc]), np.r_[Cv, Cc]
        ranks, crowd = _nsga_sort(Fa, Ca)
        order = np.lexsort((-crowd, ranks))[:pop_n]
        X, F, Cv = Xa[order], Fa[order], Ca[order]
        if verbose:
            n_feas = int(np.sum(Cv == 0))
            verbose(f"  gen {gen+1}/{gens}: feasible {n_feas}/{pop_n}, best {dict(zip(objs, (F[0]*signs).round(4).tolist()))}")
    ranks, crowd = _nsga_sort(F, Cv)
    front = [dict(inputs={k: _cast(design, k, float(v)) for k, v in zip(names, X[i])},
                  objectives={k: float(F[i][j] * signs[j]) for j, k in enumerate(objs)}, feasible=bool(Cv[i] == 0))
             for i in range(len(X)) if ranks[i] == 0]
    return dict(kind="optimize", variables=vars_, objectives=objs, pop=pop_n, generations=gens, pareto=front,
                n_evaluated=len(evaluated), rows=evaluated[-pop_n * 2:])


def _nsga_sort(F, Cv):
    n = len(F)
    dom = np.zeros((n, n), bool)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if Cv[i] < Cv[j]:
                dom[i, j] = True
            elif Cv[i] == Cv[j] and np.all(F[i] <= F[j]) and np.any(F[i] < F[j]):
                dom[i, j] = True
    ranks = np.full(n, -1)
    remaining = set(range(n)); r = 0
    while remaining:
        front = [i for i in remaining if not any(dom[j, i] for j in remaining)]
        for i in front:
            ranks[i] = r
        remaining -= set(front); r += 1
    crowd = np.zeros(n)
    for rk in range(r):
        idx = np.where(ranks == rk)[0]
        if len(idx) < 3:
            crowd[idx] = np.inf; continue
        for m in range(F.shape[1]):
            order = idx[np.argsort(F[idx, m])]
            crowd[order[0]] = crowd[order[-1]] = np.inf
            span = F[order[-1], m] - F[order[0], m]
            if span <= 0:
                continue
            for k in range(1, len(order) - 1):
                crowd[order[k]] += (F[order[k + 1], m] - F[order[k - 1], m]) / span
    return ranks, crowd


def _sbx(p1, p2, lo, hi, rng, eta=15.0):
    u = rng.random(len(p1))
    beta = np.where(u <= 0.5, (2 * u) ** (1 / (eta + 1)), (1 / (2 * (1 - u))) ** (1 / (eta + 1)))
    c1 = 0.5 * ((1 + beta) * p1 + (1 - beta) * p2); c2 = 0.5 * ((1 - beta) * p1 + (1 + beta) * p2)
    return np.clip(c1, lo, hi), np.clip(c2, lo, hi)


def _poly_mut(x, lo, hi, rng, eta=20.0, p=None):
    p = p if p is not None else 1.0 / len(x)
    y = x.copy()
    for i in range(len(x)):
        if rng.random() < p:
            u = rng.random()
            d = (2 * u) ** (1 / (eta + 1)) - 1 if u < 0.5 else 1 - (2 * (1 - u)) ** (1 / (eta + 1))
            y[i] = np.clip(x[i] + d * (hi[i] - lo[i]), lo[i], hi[i])
    return y


# ------------------------------------------------------------------ UQ and sensitivity
def uq(design, spec: dict, verbose=None) -> dict:
    """Latin-hypercube Monte Carlo over the uncertain inputs; outputs as percentiles."""
    ev = Evaluator(design)
    objs = spec.get("objectives") or DEFAULT_OBJECTIVES
    unc = dict(DEFAULT_UQ); unc.update(spec.get("uncertainties", {}))
    names = [k for k in unc if get_path(design.doc, "inputs." + k) is not None and not isinstance(get_path(design.doc, "inputs." + k), str)]
    n = int(spec.get("n", 60))
    U = qmc.LatinHypercube(d=len(names), seed=int(spec.get("seed", 7))).random(n)
    from scipy.stats import norm
    Z = norm.ppf(np.clip(U, 1e-4, 1 - 1e-4))
    rows = []
    for i in range(n):
        assign = {}
        for j, k in enumerate(names):
            base = float(get_path(design.doc, "inputs." + k))
            s = unc[k]["sigma"] * (base if unc[k].get("kind") == "rel" else 1.0)
            assign[k] = base + s * Z[i, j]
        rows.append(evaluate_point(ev, assign, objs))
        if verbose and (i + 1) % 10 == 0:
            verbose(f"  uq {i+1}/{n}")
    stats = {}
    for k in objs:
        y = np.array([r[k] for r in rows if not r["failed"]], float)
        y = y[np.isfinite(y)]
        if len(y):
            stats[k] = dict(mean=float(y.mean()), std=float(y.std()), p05=float(np.percentile(y, 5)), p50=float(np.percentile(y, 50)),
                            p95=float(np.percentile(y, 95)), n=int(len(y)))
    fails = float(np.mean([1.0 if (r["failed"] or r["n_fail"] > 0) else 0.0 for r in rows]))
    return dict(kind="uq", uncertainties={k: unc[k] for k in names}, objectives=list(objs), n=n, rows=rows, stats=stats,
                probability_of_rule_failure=fails)


def sensitivity(design, spec: dict, verbose=None) -> dict:
    """Morris elementary effects (screening) over the variables; optional first-order Sobol."""
    ev = Evaluator(design)
    objs = spec.get("objectives") or DEFAULT_OBJECTIVES
    vars_ = spec.get("variables")
    if not vars_:
        vars_ = {k: [float(get_path(design.doc, "inputs." + k)) * 0.9, float(get_path(design.doc, "inputs." + k)) * 1.1]
                 for k in ("cycle.OPR", "cycle.T04_K", "cycle.eta_c", "cycle.eta_t", "compressor.backsweep_deg", "compressor.phi2",
                           "turbine.phi", "combustor.residence_time_ms")}
    names = list(vars_)
    lo = np.array([vars_[k][0] for k in names], float); hi = np.array([vars_[k][1] for k in names], float)
    r_traj = int(spec.get("trajectories", 6)); levels = 4; delta = levels / (2 * (levels - 1))
    rng = np.random.default_rng(int(spec.get("seed", 11)))
    effects = {k: {o: [] for o in objs} for k in names}
    n_eval = 0
    for _ in range(r_traj):
        x = rng.integers(0, levels - 1, len(names)) / (levels - 1)
        order = rng.permutation(len(names))
        base = evaluate_point(ev, {k: _cast(design, k, float(v)) for k, v in zip(names, lo + x * (hi - lo))}, objs); n_eval += 1
        for j in order:
            x2 = x.copy(); x2[j] = x2[j] + delta if x2[j] + delta <= 1.0 else x2[j] - delta
            nxt = evaluate_point(ev, {k: _cast(design, k, float(v)) for k, v in zip(names, lo + x2 * (hi - lo))}, objs); n_eval += 1
            for o in objs:
                if not (base["failed"] or nxt["failed"]):
                    effects[names[j]][o].append((nxt[o] - base[o]) / (x2[j] - x[j]))
            x, base = x2, nxt
        if verbose:
            verbose(f"  morris trajectory done ({n_eval} evaluations)")
    ranking = {}
    for o in objs:
        rows = []
        for k in names:
            e = np.array(effects[k][o], float)
            e = e[np.isfinite(e)]
            if len(e):
                rows.append(dict(variable=k, mu_star=float(np.mean(np.abs(e))), sigma=float(np.std(e)), n=int(len(e))))
        rows.sort(key=lambda r: -r["mu_star"])
        ranking[o] = rows
    return dict(kind="sensitivity", method="morris", variables=vars_, objectives=list(objs), ranking=ranking, n_evaluations=n_eval)


# ------------------------------------------------------------------ persistence / CLI
KINDS = {"sweep": sweep, "doe": doe, "optimize": optimize, "uq": uq, "sensitivity": sensitivity}


def run_study(design, kind: str, name: str, spec: dict, verbose=None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown study kind {kind}")
    t0 = time.perf_counter()
    res = KINDS[kind](design, spec, verbose)
    variables = list((spec.get("variables") or {}).keys()) or list(res.get("uncertainties", {}).keys())
    res.update(name=name, spec=spec, base_hash=_base_hash(design, variables), base_version=design.store.version,
               elapsed_s=time.perf_counter() - t0, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    sdir = Path(design.dir) / "studies"; sdir.mkdir(exist_ok=True)
    (sdir / f"{name}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    design.store.commit(f"study {kind} '{name}' ({res.get('n_evaluated', len(res.get('rows', [])))} evaluations)")
    return res


def list_studies(design) -> list[dict]:
    sdir = Path(design.dir) / "studies"
    out = []
    for p in sorted(sdir.glob("*.json")) if sdir.exists() else []:
        r = json.loads(p.read_text(encoding="utf-8"))
        variables = list((r.get("spec", {}).get("variables") or {}).keys()) or list(r.get("uncertainties", {}).keys())
        out.append(dict(name=r["name"], kind=r["kind"], n=r.get("n_evaluated", len(r.get("rows", []))), at=r["at"],
                        stale=_base_hash(design, variables) != r.get("base_hash")))
    return out


def load_study(design, name: str) -> dict:
    return json.loads((Path(design.dir) / "studies" / f"{name}.json").read_text(encoding="utf-8"))


def show(design, name: str) -> str:
    r = load_study(design, name)
    L = [f"study '{name}' ({r['kind']}) from v{r.get('base_version')} at {r['at']}, {r.get('elapsed_s', 0):.1f} s"]
    if r["kind"] in ("sweep", "doe"):
        objs = [o for o in r["objectives"] if o in ("mass_kg", "TSFC", "rpm", "OD_mm", "eta_c", "choke_margin")]
        names = list(r["variables"])
        L.append("  " + "  ".join(f"{n[-14:]:>14}" for n in names) + " | " + "  ".join(f"{o:>10}" for o in objs) + "  fails")
        for row in r["rows"][:60]:
            L.append("  " + "  ".join(f"{row['inputs'][n]:>14.4g}" for n in names) + " | "
                     + "  ".join(f"{row.get(o, float('nan')):>10.4g}" for o in objs) + f"  {row.get('n_fail', '-')}")
        if r.get("surrogate"):
            L.append("  surrogate (RBF) leave-one-out error / std: " + ", ".join(f"{k} {v['loo_rms_error']:.2f}" for k, v in r["surrogate"]["per_objective"].items()))
    elif r["kind"] == "optimize":
        L.append(f"  Pareto front ({len(r['pareto'])} points, {r['n_evaluated']} evaluations):")
        names = list(r["variables"])
        for p in sorted(r["pareto"], key=lambda p: list(p["objectives"].values())[0]):
            L.append("  " + ("feasible " if p["feasible"] else "INFEAS.  ") + "  ".join(f"{k}={v:.4g}" for k, v in p["objectives"].items())
                     + " | " + "  ".join(f"{n.split('.')[-1]}={p['inputs'][n]:.4g}" for n in names))
    elif r["kind"] == "uq":
        L.append(f"  {r['n']} samples; P(rule failure) = {100*r['probability_of_rule_failure']:.0f} %")
        for k, s in r["stats"].items():
            L.append(f"  {k:<16} mean {s['mean']:.4g}  std {s['std']:.3g}  p05 {s['p05']:.4g}  p50 {s['p50']:.4g}  p95 {s['p95']:.4g}")
        L.append("  uncertainties: " + ", ".join(f"{k} +/-{v['sigma']}" for k, v in r["uncertainties"].items()))
    elif r["kind"] == "sensitivity":
        for o, rows in r["ranking"].items():
            if o not in ("mass_kg", "TSFC", "rpm", "OD_mm", "eta_c", "choke_margin", "impeller_burst"):
                continue
            L.append(f"  {o}: " + ", ".join(f"{x['variable'].split('.')[-1]} (mu* {x['mu_star']:.3g})" for x in rows[:5]))
    return "\n".join(L)
