"""Programmatic front door: ``Design`` wraps a design directory, the stage
graph and the CAD builder.  The CLI is a thin layer over this."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .state import DesignStore, diff_docs
from .state.store import get_path
from .stages import build_graph, default_inputs, input_docs, ORDER
from .rules import format_rules, worst


def parse_value(text: str) -> Any:
    """CLI value parsing: JSON first (numbers, lists, dicts, true/false/null), else string."""
    t = text.strip()
    try:
        return json.loads(t)
    except Exception:
        low = t.lower()
        if low in ("true", "yes", "on"):
            return True
        if low in ("false", "no", "off"):
            return False
        if low in ("none", "null"):
            return None
        return t


class Design:
    def __init__(self, design_dir: str | Path):
        self.dir = Path(design_dir)
        self.store = DesignStore(self.dir)
        self.graph = build_graph()

    # ---------------------------------------------------------------- lifecycle
    @classmethod
    def create(cls, design_dir, name: str | None = None, overrides: dict | None = None) -> "Design":
        inputs = default_inputs()
        for path, value in (overrides or {}).items():
            stage, key = path.split(".", 1)
            inputs.setdefault(stage, {})[key] = value
        DesignStore.create(design_dir, name or Path(design_dir).name, inputs)
        d = cls(design_dir)
        d.load()
        return d

    def load(self) -> "Design":
        self.store.load()
        return self

    @property
    def doc(self) -> dict:
        return self.store.doc

    # ---------------------------------------------------------------- editing
    def set(self, assignments: dict[str, Any], commit: bool = True) -> dict:
        """Set inputs (``stage.key`` -> value).  Returns the invalidation report."""
        before = copy.deepcopy(self.store.doc)
        changed = []
        for path, value in assignments.items():
            if "." not in path:
                raise ValueError(f"input path must be stage.key, got '{path}'")
            stage, key = path.split(".", 1)
            if stage not in self.graph.stages:
                raise ValueError(f"unknown stage '{stage}'. Stages: {', '.join(ORDER)}")
            known = default_inputs().get(stage, {})
            if key.split(".")[0] not in known:
                raise ValueError(f"unknown input '{key}' for stage '{stage}'. Known: {', '.join(known)}")
            old, new = self.store.set_input(f"{stage}.{key}", value)
            changed.append((f"{stage}.{key}", old, new))
        affected = self.graph.changed_inputs(self.store, before)
        stale = self.graph.stale(self.store)
        if commit:
            msg = "set " + ", ".join(f"{p}={n!r}" for p, _, n in changed)
            self.store.commit(msg)
        return dict(changed=changed, directly_affected=sorted(affected), stale=stale)

    # ---------------------------------------------------------------- running
    def run(self, upto: str | None = None, force: bool = False, only: list[str] | None = None,
            commit: bool = True, verbose=None):
        rep = self.graph.run(self.store, upto=upto, force=force, only=only, verbose=verbose)
        if commit and (rep.ran or rep.failed):
            self.store.commit("run " + ", ".join(rep.ran) + (" FAILED " + ", ".join(rep.failed) if rep.failed else ""))
        return rep

    def stale(self) -> dict:
        return self.graph.stale(self.store)

    def converge(self, tol: float = 0.005, max_iter: int = 12, verbose=None) -> list[dict]:
        """Iterate the cycle efficiency assumptions to the component estimates.

        Each pass copies the compressor/turbine efficiency estimates into the
        cycle inputs (under-relaxed) and re-runs the affected stages.  Stops
        when both changes are below ``tol``."""
        hist = []
        for i in range(max_iter):
            rep = self.run(commit=False, verbose=verbose)
            if rep.failed:
                raise RuntimeError("cannot converge: " + "; ".join(f"{k}: {v}" for k, v in rep.failed.items()))
            o = self.store.outputs
            ec_a, ec_e = o["cycle"]["eta_c_assumed"], o["compressor"]["eta_tt_est"]
            et_a, et_e = o["cycle"]["eta_t_assumed"], o["turbine"]["eta_tt_est"]
            hist.append(dict(iteration=i, eta_c_assumed=ec_a, eta_c_estimate=ec_e, eta_t_assumed=et_a, eta_t_estimate=et_e))
            if abs(ec_a - ec_e) < tol and abs(et_a - et_e) < tol:
                break
            relax = 0.7
            self.store.set_input("cycle.eta_c", round(ec_a + relax * (ec_e - ec_a), 4))
            self.store.set_input("cycle.eta_t", round(et_a + relax * (et_e - et_a), 4))
        self.store.commit(f"converge ({len(hist)} passes): eta_c {hist[-1]['eta_c_assumed']:.3f}, eta_t {hist[-1]['eta_t_assumed']:.3f}")
        return hist

    # ---------------------------------------------------------------- reading
    def outputs(self, stage: str | None = None) -> dict:
        return self.store.outputs if stage is None else self.store.outputs.get(stage, {})

    def rules(self, stage: str | None = None) -> list[dict]:
        rd = self.store.doc.get("rules", {})
        if stage:
            return rd.get(stage, [])
        return [r for s in ORDER for r in rd.get(s, [])]

    def rules_text(self, only_problems: bool = True) -> str:
        parts = []
        for s in ORDER:
            rs = self.store.doc.get("rules", {}).get(s, [])
            txt = format_rules(rs, only_problems=only_problems)
            if txt:
                parts.append(f"[{s}]\n{txt}")
        return "\n".join(parts) if parts else "  (no rule problems)"

    def verdict(self) -> str:
        return worst(self.rules())

    def diff(self, v1: int | None = None, v2: int | None = None) -> list[tuple[str, Any, Any]]:
        vs = self.store.versions()
        if v2 is None:
            b = self.store.doc
            v1 = v1 if v1 is not None else (vs[-2] if len(vs) >= 2 else vs[-1])
            a = self.store.snapshot(v1)
        else:
            a, b = self.store.snapshot(v1), self.store.snapshot(v2)
        return diff_docs(a, b)

    def inputs_with_docs(self, stage: str | None = None) -> list[tuple[str, Any, str]]:
        docs = input_docs()
        rows = []
        for s in ORDER:
            if stage and s != stage:
                continue
            for k, v in self.store.inputs.get(s, {}).items():
                rows.append((f"{s}.{k}", v, docs.get(s, {}).get(k, "")))
        return rows

    def summary(self) -> dict:
        """Headline numbers for the CLI banner."""
        o = self.store.outputs
        g = lambda s, k: get_path(o, f"{s}.{k}")  # noqa: E731
        return {
            "thrust_N": g("requirements", "thrust_N"), "airflow_kg_s": g("cycle", "W_kg_s"),
            "TSFC_kg_N_h": g("cycle", "TSFC_kg_per_N_h"), "rpm": g("speed", "rpm"),
            "D2_mm": (g("compressor", "D2_m") or 0) * 1e3, "turbine_tip_mm": (g("turbine", "r_tip_rotor_m") or 0) * 2e3,
            "OD_mm": (g("layout", "OD_m") or 0) * 1e3, "length_mm": (g("layout", "length_m") or 0) * 1e3,
            "mass_kg": g("geometry", "mass_total_kg"), "bearing": g("rotor", "bearing_id"),
            "verdict": self.verdict(),
        }
