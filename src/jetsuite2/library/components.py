"""Standard component library: bearings, retaining rings, screws, locknuts,
O-rings, igniters, sensors, seals.

Data lives in ``library/data/*.json``.  Extra catalogue files can be dropped
into any directory named by the ``JETSUITE2_LIBRARY`` environment variable
(same JSON layout); they are merged on top of the built-in data (an item with
the same ``id`` overrides).

Every item exposes the parameters that constrain the surrounding design:
bore / od / width, DN limit, temperature rating, load ratings, thread pitch,
groove dimensions.  The rotor stage picks bearings from here; the CAD stage
draws the real part envelope from the same numbers.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).with_name("data")


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def catalogue() -> dict:
    """Merged catalogue: {'bearings': [...], 'retaining_rings': [...], 'screws': [...], ...}."""
    cat: dict[str, list | dict] = {"bearings": _load_json(DATA_DIR / "bearings.json")["items"]}
    hw = _load_json(DATA_DIR / "hardware.json")
    for k, v in hw.items():
        if k.startswith("_"):
            continue
        cat[k] = v
    extra = os.environ.get("JETSUITE2_LIBRARY")
    if extra:
        for p in sorted(Path(extra).glob("*.json")):
            d = _load_json(p)
            items = d.get("items", None)
            if items is not None and "bearings" in p.stem:
                _merge(cat, "bearings", items)
            for k, v in d.items():
                if k.startswith("_") or k == "items":
                    continue
                if isinstance(v, list):
                    _merge(cat, k, v)
                elif isinstance(v, dict):
                    cat.setdefault(k, {}).update(v)
    return cat


def _merge(cat: dict, key: str, items: list) -> None:
    base = {i["id"]: i for i in cat.get(key, [])}
    for it in items:
        base[it["id"]] = it
    cat[key] = list(base.values())


def by_id(kind: str, item_id: str) -> dict:
    for it in catalogue()[kind]:
        if it["id"] == item_id:
            return it
    raise KeyError(f"no {kind} item '{item_id}'")


# ------------------------------------------------------------------ bearings
def bearings(bore: float | None = None, min_bore: float | None = None, hybrid: bool | None = None,
             btype: str | None = None, max_od: float | None = None) -> list[dict]:
    out = []
    for b in catalogue()["bearings"]:
        if bore is not None and abs(b["bore"] - bore) > 1e-9:
            continue
        if min_bore is not None and b["bore"] < min_bore - 1e-9:
            continue
        if hybrid is not None and bool(b.get("hybrid")) != hybrid:
            continue
        if btype is not None and b["type"] != btype:
            continue
        if max_od is not None and b["od"] > max_od + 1e-9:
            continue
        out.append(b)
    return sorted(out, key=lambda b: (b["bore"], b["od"], b["width"]))


def select_bearing(rpm: float, min_bore: float, T_bearing: float = 393.0, hybrid: bool = True,
                   dn_margin: float = 0.85, btype: str | None = "angular_contact") -> dict:
    """Smallest bearing whose DN limit (with margin) and temperature rating admit `rpm`.

    Raises ValueError with the nearest candidates when nothing qualifies.
    """
    cands = bearings(min_bore=min_bore, hybrid=hybrid, btype=btype)
    ok = [b for b in cands if b["bore"] * rpm <= dn_margin * b["dn_limit"] and T_bearing <= b["T_max"]]
    if not ok:
        near = ", ".join(f"{b['id']} (DN {b['bore']*rpm:.2e} vs limit {dn_margin*b['dn_limit']:.2e}, Tmax {b['T_max']} K)"
                         for b in cands[:4])
        raise ValueError(f"no bearing with bore >= {min_bore} mm admits {rpm:.0f} rpm at {T_bearing:.0f} K; nearest: {near}")
    return sorted(ok, key=lambda b: (b["bore"], b["od"]))[0]


# ------------------------------------------------------------- shaft hardware
def retaining_ring(d: float, kind: str = "external") -> dict:
    items = [r for r in catalogue()["retaining_rings"] if r["kind"] == kind]
    exact = [r for r in items if abs(r["d"] - d) < 1e-9]
    if exact:
        return exact[0]
    bigger = sorted([r for r in items if r["d"] >= d], key=lambda r: r["d"])
    if not bigger:
        raise KeyError(f"no {kind} retaining ring for d >= {d}")
    return bigger[0]


def locknut(shaft_d: float) -> dict:
    items = sorted(catalogue()["locknuts"], key=lambda n: n["d"])
    for n in items:
        if n["d"] >= shaft_d - 1e-9:
            return n
    return items[-1]


def screw(size: str) -> dict:
    return by_id("screws", size)


def screw_for_flange(clamp_load_N: float, n_screws: int, cls: str = "12.9", safety: float = 2.0) -> dict:
    """Smallest ISO 4762 screw whose proof load covers the per-screw clamp load."""
    proof = catalogue()["screw_classes"][cls]["proof_MPa"]
    per = clamp_load_N / n_screws * safety
    for s in sorted(catalogue()["screws"], key=lambda s: s["d"]):
        if s["A_s_mm2"] * proof >= per:
            return s
    return sorted(catalogue()["screws"], key=lambda s: s["d"])[-1]


def o_ring(id_mm: float, cs: float | None = None) -> dict:
    items = sorted(catalogue()["o_rings"], key=lambda o: o["cs"])
    if cs is not None:
        return min(items, key=lambda o: abs(o["cs"] - cs))
    # choose cross-section by diameter: small bores 1.78, medium 2.62, large 3.53
    if id_mm < 40:
        return items[0]
    if id_mm < 120:
        return items[1]
    return items[2]


def igniter() -> dict:
    return catalogue()["igniters"][0]


def egt_probe() -> dict:
    return catalogue()["sensors"][0]


def seal(kind: str = "labyrinth") -> dict:
    for s in catalogue()["seals"]:
        if s["kind"] == kind:
            return s
    raise KeyError(kind)


def describe(kind: str) -> str:
    """Human-readable table of one catalogue section."""
    items = catalogue()[kind]
    if isinstance(items, dict):
        return "\n".join(f"  {k}: {v}" for k, v in items.items())
    keys = [k for k in items[0] if k not in ("note", "lengths")]
    lines = ["  " + "  ".join(f"{k:>10}" for k in keys)]
    for it in items:
        lines.append("  " + "  ".join(f"{str(it.get(k, '')):>10}" for k in keys))
    return "\n".join(lines)
