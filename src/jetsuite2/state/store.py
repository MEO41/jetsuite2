"""Design state: one JSON document per design, versioned by snapshots.

Layout on disk::

    <design_dir>/design.json        current state
    <design_dir>/history/v0001.json snapshots (full state, one per version)
    <design_dir>/history/log.txt    one line per version: what changed
    <design_dir>/cad/               CAD outputs and per-part cache

State document::

    {"name", "version", "created", "updated",
     "inputs":  {stage: {field: value}},   # user-editable, grouped by owning stage
     "outputs": {stage: {...}},            # computed by stages
     "stamps":  {stage: {"inputs_hash", "outputs_hash", "at", "elapsed_s"}},
     "rules":   {stage: [verdicts]}}
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:  # pragma: no cover
        pass
    raise TypeError(f"not JSON serialisable: {type(o)}")


def _clean(o):
    """Round-trip through JSON semantics: numpy -> python, NaN/inf -> None."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, bool):
        return o
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return _clean(o.item())
        if isinstance(o, np.ndarray):
            return _clean(o.tolist())
    except ImportError:  # pragma: no cover
        pass
    return o


def canonical_hash(obj: Any) -> str:
    """Stable hash of a JSON-able value (numbers rounded to 12 significant digits)."""
    def norm(x):
        if isinstance(x, dict):
            return {k: norm(x[k]) for k in sorted(x)}
        if isinstance(x, (list, tuple)):
            return [norm(v) for v in x]
        if isinstance(x, bool):
            return x
        if isinstance(x, float):
            return float(f"{x:.12g}")
        return x
    s = json.dumps(norm(_clean(obj)), sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def get_path(doc: dict, path: str, default=None):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def project(doc: dict, paths: Iterable[str]) -> dict:
    """Extract the values at the given dotted paths.  A path ending in '.*' takes the
    whole sub-dict; a missing path contributes None (so adding a field later is a change)."""
    out = {}
    for p in paths:
        if p.endswith(".*"):
            out[p] = get_path(doc, p[:-2])
        else:
            out[p] = get_path(doc, p)
    return out


class DesignStore:
    """Load / save / snapshot one design directory."""

    def __init__(self, design_dir: str | os.PathLike):
        self.dir = Path(design_dir)
        self.file = self.dir / "design.json"
        self.history = self.dir / "history"
        self.doc: dict = {}

    # ---------------------------------------------------------------- basics
    @classmethod
    def create(cls, design_dir, name: str, inputs: dict) -> "DesignStore":
        st = cls(design_dir)
        if st.file.exists():
            raise FileExistsError(f"{st.file} already exists")
        st.dir.mkdir(parents=True, exist_ok=True)
        st.history.mkdir(exist_ok=True)
        st.doc = {"name": name, "version": 0, "created": _now(), "updated": _now(),
                  "inputs": copy.deepcopy(inputs), "outputs": {}, "stamps": {}, "rules": {}}
        st.commit("created")
        return st

    def load(self) -> "DesignStore":
        with open(self.file, encoding="utf-8") as f:
            self.doc = json.load(f)
        self.doc["_design_dir"] = str(self.dir)     # transient: never persisted
        return self

    def _persistable(self) -> dict:
        return {k: v for k, v in self.doc.items() if not k.startswith("_")}

    def save(self) -> None:
        self.doc["updated"] = _now()
        tmp = self.file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_clean(self._persistable()), f, indent=1, default=_json_default)
        os.replace(tmp, self.file)

    def commit(self, message: str) -> int:
        """Bump the version, snapshot the full state and append to the log."""
        self.doc["version"] = int(self.doc.get("version", 0)) + 1
        self.save()
        self.history.mkdir(exist_ok=True)
        snap = self.history / f"v{self.doc['version']:04d}.json"
        with open(snap, "w", encoding="utf-8") as f:
            json.dump(_clean(self._persistable()), f, indent=1, default=_json_default)
        with open(self.history / "log.txt", "a", encoding="utf-8") as f:
            f.write(f"v{self.doc['version']:04d}  {_now()}  {message}\n")
        return self.doc["version"]

    # -------------------------------------------------------------- accessors
    @property
    def version(self) -> int:
        return int(self.doc.get("version", 0))

    @property
    def inputs(self) -> dict:
        return self.doc.setdefault("inputs", {})

    @property
    def outputs(self) -> dict:
        return self.doc.setdefault("outputs", {})

    @property
    def stamps(self) -> dict:
        return self.doc.setdefault("stamps", {})

    def get(self, path: str, default=None):
        return get_path(self.doc, path, default)

    def set_input(self, path: str, value) -> tuple[Any, Any]:
        """Set inputs.<path>; returns (old, new)."""
        full = f"inputs.{path}" if not path.startswith("inputs.") else path
        old = get_path(self.doc, full)
        set_path(self.doc, full, value)
        return old, value

    # ----------------------------------------------------------------- history
    def snapshot(self, version: int) -> dict:
        p = self.history / f"v{version:04d}.json"
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def versions(self) -> list[int]:
        return sorted(int(p.stem[1:]) for p in self.history.glob("v*.json"))

    def log_lines(self) -> list[str]:
        p = self.history / "log.txt"
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    def checkout(self, version: int, message: str | None = None) -> int:
        """Restore a snapshot as the new current state (kept as a new version)."""
        snap = self.snapshot(version)
        keep_version = self.version
        self.doc = snap
        self.doc["version"] = keep_version
        self.doc["_design_dir"] = str(self.dir)
        return self.commit(message or f"checkout v{version:04d}")


def diff_docs(a: dict, b: dict, sections=("inputs", "outputs")) -> list[tuple[str, Any, Any]]:
    """Field-level diff [(path, old, new)] between two state documents."""
    out = []
    for sec in sections:
        fa, fb = flatten(a.get(sec, {})), flatten(b.get(sec, {}))
        for k in sorted(set(fa) | set(fb)):
            va, vb = fa.get(k), fb.get(k)
            if _differs(va, vb):
                out.append((f"{sec}.{k}", va, vb))
    return out


def _differs(a, b, rel=1e-9) -> bool:
    if (isinstance(a, (int, float)) and isinstance(b, (int, float))
            and not isinstance(a, bool) and not isinstance(b, bool)):
        return abs(a - b) > rel * max(1.0, abs(a), abs(b))
    return a != b
