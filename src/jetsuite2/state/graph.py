"""Stage dependency graph with value-hash invalidation.

A ``Stage`` declares the state paths it reads (``reads``) and writes its
results to ``outputs.<name>``.  Its input hash is the canonical hash of exactly
those values.  A stage is *stale* when its stored stamp differs from the
current input hash -- so editing prose, reordering keys, or re-running an
upstream stage that produced identical numbers does **not** re-run it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .store import DesignStore, canonical_hash, flatten, project, _differs, set_path


TIER_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L2.5": 2.5, "L3": 3}


@dataclass
class Stage:
    name: str
    reads: list[str]                       # dotted paths into the state doc
    run: Callable[[dict], dict]            # full doc -> outputs dict (may include "_rules")
    doc: str = ""
    after: list[str] = field(default_factory=list)   # explicit ordering hints (usually inferred)
    tier: str = "L1"                       # fidelity tier of the stage's own method
    core: bool = True                      # core stages run by default; analysis stages are opt-in

    def input_hash(self, state: dict) -> str:
        # overrides (ingested L3 results) for this stage are part of its inputs
        return canonical_hash(project(state, list(self.reads) + [f"overrides.{self.name}.*"]))

    def upstream(self) -> set[str]:
        """Stage names whose outputs this stage reads."""
        ups = set(self.after)
        for p in self.reads:
            parts = p.split(".")
            if parts[0] == "outputs" and len(parts) > 1:
                ups.add(parts[1])
        return ups


@dataclass
class RunReport:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict = field(default_factory=dict)          # stage -> error text
    changes: dict = field(default_factory=dict)         # stage -> [(path, old, new)]
    timings: dict = field(default_factory=dict)         # stage -> seconds

    def summary(self) -> str:
        lines = []
        for s in self.ran:
            n = len(self.changes.get(s, []))
            lines.append(f"  ran     {s:<12} {self.timings.get(s, 0):7.3f} s  {n} output value(s) changed")
        for s in self.skipped:
            lines.append(f"  skipped {s:<12} (inputs unchanged)")
        for s, e in self.failed.items():
            lines.append(f"  FAILED  {s:<12} {e}")
        return "\n".join(lines)


class StageGraph:
    def __init__(self, stages: list[Stage]):
        self.stages = {s.name: s for s in stages}
        self.order = self._toposort()

    def _toposort(self) -> list[str]:
        order, seen, temp = [], set(), set()

        def visit(n):
            if n in seen:
                return
            if n in temp:
                raise ValueError(f"cycle in stage graph at {n}")
            temp.add(n)
            for u in sorted(self.stages[n].upstream()):
                if u in self.stages:
                    visit(u)
            temp.discard(n)
            seen.add(n)
            order.append(n)

        for n in self.stages:
            visit(n)
        return order

    def downstream(self, name: str) -> list[str]:
        out = []
        for n in self.order:
            ups = self.stages[n].upstream()
            if name in ups or any(d in ups for d in out):
                out.append(n)
        return out

    # ------------------------------------------------------------ staleness
    def stale(self, store: DesignStore) -> dict[str, str]:
        """Map stage -> reason for every stage that would re-run now."""
        res = {}
        for n in self.order:
            st = self.stages[n]
            stamp = store.stamps.get(n)
            if stamp is None:
                res[n] = "never run"
                continue
            ups = [u for u in st.upstream() if u in res]
            if ups:
                res[n] = "upstream stale: " + ", ".join(sorted(ups))
            elif stamp.get("inputs_hash") != st.input_hash(store.doc):
                res[n] = "inputs changed"
        return res

    def changed_inputs(self, store: DesignStore, before: dict) -> dict[str, list[str]]:
        """Which stage-input paths differ between `before` (a doc) and the store now."""
        out = {}
        for n, st in self.stages.items():
            pa, pb = project(before, st.reads), project(store.doc, st.reads)
            diffs = [p for p in st.reads if canonical_hash(pa[p]) != canonical_hash(pb[p])]
            if diffs:
                out[n] = diffs
        return out

    # ---------------------------------------------------------------- run
    def run(self, store: DesignStore, upto: str | None = None, force: bool = False,
            only: list[str] | None = None, verbose: Callable[[str], None] | None = None,
            include_analysis: bool = False) -> RunReport:
        rep = RunReport()
        for n in self.order:
            if only and n not in only:
                continue
            st = self.stages[n]
            if not st.core and not include_analysis and not (only and n in only):
                continue
            h = st.input_hash(store.doc)
            stamp = store.stamps.get(n)
            if not force and stamp and stamp.get("inputs_hash") == h:
                rep.skipped.append(n)
                if upto == n:
                    break
                continue
            missing = [u for u in st.upstream() if u in rep.failed]
            if missing:
                rep.failed[n] = "blocked by failed upstream: " + ", ".join(missing)
                continue
            if verbose:
                verbose(f"running {n} ...")
            t0 = time.perf_counter()
            old = store.outputs.get(n, {})
            try:
                out = st.run(store.doc)
            except Exception as e:  # noqa: BLE001 - reported, not hidden
                rep.failed[n] = f"{type(e).__name__}: {e}"
                store.stamps.pop(n, None)
                continue
            dt = time.perf_counter() - t0
            rules = out.pop("_rules", None)
            # ingested higher-tier results replace the stage's own values (provenance recorded)
            prov = {}
            for fld, ov in (store.doc.get("overrides", {}).get(n, {}) or {}).items():
                if ov.get("value") is None:
                    continue
                set_path(out, fld, ov["value"])      # dotted fields address nested outputs (e.g. impeller.sigma_peak_Pa)
                prov[fld] = {"tier": ov.get("tier", "L3"), "source": ov.get("source", ""), "at": ov.get("at", "")}
            out["_provenance"] = prov
            store.outputs[n] = out
            if rules is not None:
                for r in rules:
                    r.setdefault("tier", st.tier)
                store.doc.setdefault("rules", {})[n] = rules
            store.stamps[n] = {"inputs_hash": h, "outputs_hash": canonical_hash(out),
                               "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "elapsed_s": round(dt, 4),
                               "tier": st.tier, "overridden": sorted(prov)}
            rep.ran.append(n)
            rep.timings[n] = dt
            rep.changes[n] = _diff_flat(old, out)
            if upto == n:
                break
        return rep


def _diff_flat(a: dict, b: dict) -> list[tuple[str, object, object]]:
    fa, fb = flatten(a), flatten(b)
    out = []
    for k in sorted(set(fa) | set(fb)):
        if k.startswith("_") or k.endswith("_note") or k.endswith("_source"):
            continue
        if _differs(fa.get(k), fb.get(k), rel=1e-6):
            out.append((k, fa.get(k), fb.get(k)))
    return out
