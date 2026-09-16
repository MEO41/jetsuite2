"""Design-rule verdicts.

Every stage returns a ``_rules`` list built with :func:`check`.  A verdict is
``pass`` / ``warn`` / ``fail`` with the value, the limit, the margin and the
source of the limit, so the CLI can print *why* something failed and the
report can cite it.
"""
from __future__ import annotations

import math


def check(rule_id: str, name: str, value: float | None, limit: float | None, kind: str,
          source: str, warn_margin: float = 0.05, unit: str = "", note: str = "",
          hard: bool = True) -> dict:
    """Build a verdict.

    kind: 'max' (value <= limit), 'min' (value >= limit), 'info' (no verdict).
    warn_margin: fraction of the limit inside which the verdict is 'warn'.
    hard=False turns a would-be 'fail' into 'warn' (advisory rules).
    """
    v = dict(id=rule_id, name=name, value=value, limit=limit, kind=kind, unit=unit,
             source=source, note=note)
    if kind == "info" or value is None or limit is None or (isinstance(value, float) and math.isnan(value)):
        v["verdict"] = "info"
        v["margin"] = None
        return v
    if kind == "max":
        margin = (limit - value) / abs(limit) if limit else (limit - value)
    elif kind == "min":
        margin = (value - limit) / abs(limit) if limit else (value - limit)
    else:
        raise ValueError(kind)
    v["margin"] = margin
    if margin < 0:
        v["verdict"] = "fail" if hard else "warn"
    elif margin < warn_margin:
        v["verdict"] = "warn"
    else:
        v["verdict"] = "pass"
    return v


def worst(rules: list[dict]) -> str:
    order = {"fail": 3, "warn": 2, "pass": 1, "info": 0}
    return max((r["verdict"] for r in rules), key=lambda k: order[k], default="info")


def format_rules(rules: list[dict], only_problems: bool = False) -> str:
    lines = []
    for r in rules:
        if only_problems and r["verdict"] in ("pass", "info"):
            continue
        val = _fmt(r["value"])
        lim = _fmt(r["limit"])
        mrg = "" if r["margin"] is None else f"{100*r['margin']:+6.1f} %"
        sym = {"pass": "ok  ", "warn": "WARN", "fail": "FAIL", "info": "info"}[r["verdict"]]
        rel = {"max": "<=", "min": ">=", "info": "  "}[r["kind"]]
        lines.append(f"  {sym} {r['id']:<10} {r['name']:<44} {val:>10} {rel} {lim:<10} {r['unit']:<6} {mrg:>9}  [{r['source']}]")
        if r.get("note") and r["verdict"] in ("warn", "fail"):
            lines.append(f"       -> {r['note']}")
    return "\n".join(lines)


def _fmt(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, str):
        return x
    if isinstance(x, bool):
        return str(x)
    ax = abs(x)
    if ax == 0:
        return "0"
    if ax >= 1e5 or ax < 1e-3:
        return f"{x:.3e}"
    if ax >= 100:
        return f"{x:.1f}"
    return f"{x:.3f}"
