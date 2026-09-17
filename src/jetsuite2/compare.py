"""Freeze and compare (roadmap section 3).

* ``freeze``: snapshot the design with sign-off and the open risks, hash-verifiable and immutable
  (``frozen/vNNNN.json`` + ``.sha256``).  A design *is frozen* while its inputs, outputs and overrides
  still hash to the frozen record; any later change unfreezes it (the record stays as history).
* ``require_frozen``: the gate CAD and export use.
* ``compare``: side-by-side of two designs or versions (``dir``, ``dir@vNNNN``, ``dir@frozen``):
  headline numbers, inputs that differ, every rule (value / margin / verdict A vs B), the surge margins
  with their band, the running line, and a map overlay figure.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .state.store import canonical_hash, diff_docs, get_path, _clean, _json_default

SM_RULES = ("MAP-1", "OD-1", "OD-4", "ENV-2", "TRN-4")
HEADLINE = [("thrust N", "requirements.thrust_N", 0), ("airflow kg/s", "cycle.W_kg_s", 3), ("OPR", "cycle.OPR", 2),
            ("T04 K", "cycle.T04_K", 0), ("TSFC kg/N/h", "cycle.TSFC_kg_per_N_h", 4), ("rpm", "speed.rpm", 0),
            ("D2 mm", "compressor.D2_m", 1, 1e3), ("turbine tip mm", "turbine.r_tip_rotor_m", 1, 2e3),
            ("OD mm", "layout.OD_m", 1, 1e3), ("length mm", "layout.length_m", 0, 1e3), ("mass kg", "geometry.mass_total_kg", 2),
            ("idle SM", "offdesign.idle.SM", 3), ("SM min (running line)", "offdesign.SM_min", 3),
            ("max thrust N", "offdesign.max_point.Fn", 0), ("slam accel t95 s", "transient.scenarios.accel.t_95pct_s", 2),
            ("slam accel SM min", "transient.scenarios.accel.SM_min", 3), ("start T04 peak K", "transient.scenarios.start.T04_peak", 0),
            ("hot start T04 peak K", "transient.scenarios.hot_start.T04_peak", 0),
            ("turbine bore LCF cycles (with thermal)", "life.lcf.turbine_cycles_with_thermal", 0), ("envelope worst SM", "envelope.worst_SM", 3)]


# ----------------------------------------------------------------------------- freeze
def _content_hash(doc: dict) -> str:
    return canonical_hash(dict(inputs=doc.get("inputs", {}), outputs=doc.get("outputs", {}), overrides=doc.get("overrides", {})))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def freeze(design, by: str, note: str = "") -> dict:
    """Snapshot the current state as a frozen, signed-off version.  Refuses if any core stage is stale."""
    stale = {k: v for k, v in design.stale().items() if k in design.graph.core_names()} if hasattr(design.graph, "core_names") else {}
    if not stale:
        from .stages import CORE
        stale = {k: v for k, v in design.stale().items() if k in CORE}
    if stale:
        raise RuntimeError(f"cannot freeze: core stages stale ({', '.join(stale)}) -- run `jet run` first")
    doc = design.doc
    open_risks = [dict(id=r["id"], name=r["name"], verdict=r["verdict"], value=r.get("value"), limit=r.get("limit"),
                       margin=r.get("margin"), tier=r.get("tier")) for r in design.rules() if r.get("verdict") in ("fail", "warn")]
    analyses = [s for s in doc.get("stamps", {}) if s in design.graph.stages and not design.graph.stages[s].core] if hasattr(design.graph, "stages") else []
    rec = dict(at=datetime.now(timezone.utc).isoformat(timespec="seconds"), by=by, note=note, content_hash=_content_hash(doc),
               open_risks=open_risks, n_fail=sum(1 for r in open_risks if r["verdict"] == "fail"),
               n_warn=sum(1 for r in open_risks if r["verdict"] == "warn"), analyses_present=analyses,
               tiers={s: st.get("tier") for s, st in doc.get("stamps", {}).items()})
    doc["freeze"] = rec
    v = design.store.commit(f"freeze by {by}: {note}" if note else f"freeze by {by}")
    rec["version"] = v
    fdir = Path(design.dir) / "frozen"
    fdir.mkdir(exist_ok=True)
    snap = fdir / f"v{v:04d}.json"
    snap.write_text(json.dumps(_clean(design.store._persistable()), indent=1, default=_json_default), encoding="utf-8")
    (fdir / f"v{v:04d}.sha256").write_text(_sha256(snap) + "\n", encoding="utf-8")
    try:  # immutable on disk (best effort; Windows honours the read-only bit)
        import os, stat
        for p in (snap, fdir / f"v{v:04d}.sha256"):
            os.chmod(p, stat.S_IREAD)
    except OSError:
        pass
    design.store.save()
    return rec


def frozen_versions(design) -> list[int]:
    fdir = Path(design.dir) / "frozen"
    return sorted(int(p.stem[1:]) for p in fdir.glob("v*.json")) if fdir.exists() else []


def verify_frozen(design, version: int) -> dict:
    """Recompute the file hash and the content hash of a frozen snapshot."""
    fdir = Path(design.dir) / "frozen"
    snap, sig = fdir / f"v{version:04d}.json", fdir / f"v{version:04d}.sha256"
    if not snap.exists() or not sig.exists():
        return dict(version=version, ok=False, reason="missing snapshot or signature")
    file_ok = _sha256(snap) == sig.read_text(encoding="utf-8").strip()
    doc = json.loads(snap.read_text(encoding="utf-8"))
    rec = doc.get("freeze", {})
    content_ok = rec.get("content_hash") == _content_hash(doc)
    return dict(version=version, ok=bool(file_ok and content_ok), file_hash_ok=file_ok, content_hash_ok=content_ok,
                by=rec.get("by"), at=rec.get("at"), note=rec.get("note"))


def freeze_status(design) -> dict:
    rec = design.doc.get("freeze")
    if not rec:
        return dict(frozen=False, reason="never frozen", record=None)
    cur = _content_hash(design.doc)
    if cur == rec.get("content_hash"):
        return dict(frozen=True, reason=f"frozen v{rec.get('version', '?'):04d} by {rec.get('by')} at {rec.get('at')}", record=rec)
    # name what moved since the freeze
    changed = []
    try:
        snap = design.store.snapshot(int(rec["version"]))
        changed = [p for p, _, _ in diff_docs(snap, design.doc, sections=("inputs",))][:8]
    except Exception:  # noqa: BLE001
        pass
    return dict(frozen=False, record=rec,
                reason=f"changed since freeze v{rec.get('version', '?'):04d}" + (f" ({', '.join(changed)}{'...' if len(changed) >= 8 else ''})" if changed else ""))


def require_frozen(design, override: bool, what: str) -> None:
    st = freeze_status(design)
    if st["frozen"]:
        return
    if override:
        print(f"WARNING: {what} on an unfrozen design ({st['reason']}) -- --unfrozen-ok given")
        return
    raise SystemExit(f"{what} refused: design is not frozen ({st['reason']}). Run `jet freeze --by <name>` first, "
                     f"or pass --unfrozen-ok to override.")


# ----------------------------------------------------------------------------- compare
def load_spec(spec: str) -> tuple[dict, str]:
    """``dir`` (current state), ``dir@vNNNN`` (history snapshot) or ``dir@frozen`` (latest frozen)."""
    from .api import Design
    path, _, ver = spec.partition("@")
    d = Design(path).load()
    label = Path(path).resolve().name          # directory name: copies keep the original design name
    if not ver:
        return d.doc, f"{label} v{d.store.version:04d}"
    if ver == "frozen":
        fv = frozen_versions(d)
        if not fv:
            raise SystemExit(f"{path} has no frozen version")
        doc = json.loads((Path(path) / "frozen" / f"v{fv[-1]:04d}.json").read_text(encoding="utf-8"))
        return doc, f"{label} frozen v{fv[-1]:04d}"
    v = int(ver.lstrip("v"))
    return d.store.snapshot(v), f"{label} v{v:04d}"


def _fmt(x, nd=3):
    if x is None:
        return "-"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, (int, float)):
        return f"{x:.{nd}f}" if isinstance(x, float) else str(x)
    return str(x)


def _rules_by_id(doc):
    out = {}
    for stage, rs in doc.get("rules", {}).items():
        for r in rs:
            out[r["id"]] = dict(r, stage=stage)
    return out


def compare(doc_a: dict, doc_b: dict, name_a: str = "A", name_b: str = "B") -> dict:
    res = dict(names=(name_a, name_b))
    # headline numbers
    head = []
    for row in HEADLINE:
        label, path, nd = row[0], row[1], row[2]
        scale = row[3] if len(row) > 3 else 1.0
        a, b = get_path(doc_a.get("outputs", {}), path), get_path(doc_b.get("outputs", {}), path)
        a = a * scale if isinstance(a, (int, float)) else a
        b = b * scale if isinstance(b, (int, float)) else b
        delta = (b - a) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        head.append(dict(label=label, a=a, b=b, delta=delta, nd=nd))
    res["headline"] = head
    # inputs that differ
    res["inputs_diff"] = [dict(path=p, a=x, b=y) for p, x, y in diff_docs(doc_a, doc_b, sections=("inputs",))]
    res["overrides_diff"] = [dict(path=p, a=x, b=y) for p, x, y in diff_docs(doc_a, doc_b, sections=("overrides",))]
    # rules
    ra, rb = _rules_by_id(doc_a), _rules_by_id(doc_b)
    rules = []
    for rid in sorted(set(ra) | set(rb), key=lambda k: (k.split("-")[0], int(k.split("-")[1]) if k.split("-")[-1].isdigit() else 0)):
        x, y = ra.get(rid), rb.get(rid)
        rules.append(dict(id=rid, name=(x or y)["name"], stage=(x or y)["stage"],
                          a=dict(value=x.get("value"), margin=x.get("margin"), verdict=x.get("verdict"), limit=x.get("limit")) if x else None,
                          b=dict(value=y.get("value"), margin=y.get("margin"), verdict=y.get("verdict"), limit=y.get("limit")) if y else None,
                          changed=(x is None) != (y is None) or (x and y and (x.get("verdict") != y.get("verdict") or
                                   (isinstance(x.get("value"), (int, float)) and isinstance(y.get("value"), (int, float)) and
                                    abs(x["value"] - y["value"]) > 1e-6 * max(1.0, abs(x["value"]))))),
                          tier=(y or x).get("tier")))
    res["rules"] = rules
    # surge margins with their band
    band_a = get_path(doc_a, "outputs.maps.compressor_map.surge_band_SM")
    band_b = get_path(doc_b, "outputs.maps.compressor_map.surge_band_SM")
    def _band(r, default):
        if not r:
            return None, None, None
        return r.get("band", default), r.get("band_dominant", "rig" if default else None), r.get("pass_with_band")
    res["surge"] = []
    for rid in SM_RULES:
        if rid not in ra and rid not in rb:
            continue
        ba, da, pa = _band(ra.get(rid), band_a)
        bb, db, pb = _band(rb.get(rid), band_b)
        res["surge"].append(dict(id=rid, a=(ra[rid].get("value") if rid in ra else None), b=(rb[rid].get("value") if rid in rb else None),
                                 band_a=ba, band_b=bb, dom_a=(da or "").split(" (")[0] if da else None, dom_b=(db or "").split(" (")[0] if db else None,
                                 with_band_a=pa, with_band_b=pb, limit=(rb.get(rid) or ra.get(rid) or {}).get("limit")))
    # running line
    la = {round(p["N_frac"], 2): p for p in get_path(doc_a, "outputs.offdesign.running_line", []) or [] if p.get("converged")}
    lb = {round(p["N_frac"], 2): p for p in get_path(doc_b, "outputs.offdesign.running_line", []) or [] if p.get("converged")}
    res["running_line"] = [dict(N=n, SM_a=la.get(n, {}).get("SM"), SM_b=lb.get(n, {}).get("SM"), Fn_a=la.get(n, {}).get("Fn"), Fn_b=lb.get(n, {}).get("Fn"),
                                PR_a=la.get(n, {}).get("PR_c"), PR_b=lb.get(n, {}).get("PR_c"),
                                sched_b=dict(bleed=lb.get(n, {}).get("bleed"), igv=lb.get(n, {}).get("igv_deg")))
                           for n in sorted(set(la) | set(lb))]
    # tiers / freeze state
    res["tiers"] = {s: (get_path(doc_a, f"stamps.{s}.tier"), get_path(doc_b, f"stamps.{s}.tier"))
                    for s in sorted(set(doc_a.get("stamps", {})) | set(doc_b.get("stamps", {})))}
    res["freeze"] = (doc_a.get("freeze", {}).get("version"), doc_b.get("freeze", {}).get("version"))
    return res


def render(res: dict) -> str:
    A, B = res["names"]
    L = [f"# Compare: {A}  vs  {B}\n", f"Frozen versions: A {res['freeze'][0] or '-'}, B {res['freeze'][1] or '-'}.\n",
         "## Headline\n", f"| quantity | {A} | {B} | delta |", "|---|---|---|---|"]
    for h in res["headline"]:
        L.append(f"| {h['label']} | {_fmt(h['a'], h['nd'])} | {_fmt(h['b'], h['nd'])} | {('%+.*f' % (h['nd'], h['delta'])) if h['delta'] is not None else '-'} |")
    L.append("\n## Inputs that differ\n")
    if res["inputs_diff"]:
        L += ["| input | A | B |", "|---|---|---|"] + [f"| {d['path']} | {d['a']} | {d['b']} |" for d in res["inputs_diff"]]
    else:
        L.append("(none)")
    if res["overrides_diff"]:
        L += ["\n### Overrides (ingested L3) that differ\n", "| path | A | B |", "|---|---|---|"] + [f"| {d['path']} | {d['a']} | {d['b']} |" for d in res["overrides_diff"]]
    L.append("\n## Surge margins with their band (SAE SM, absolute)\n")
    L += ["| rule | A | band A (dominant) | A with band | B | band B (dominant) | B with band | limit |", "|---|---|---|---|---|---|---|---|"]
    wb = lambda v, b, p: ("-" if v is None or b is None else f"{v - b:+.3f} {'pass' if p else 'FAIL'}" if p is not None else f"{v - b:+.3f}")  # noqa: E731
    for s in res["surge"]:
        L.append(f"| {s['id']} | {_fmt(s['a'])} | +/-{_fmt(s['band_a'])} ({s['dom_a'] or '-'}) | {wb(s['a'], s['band_a'], s['with_band_a'])} | "
                 f"{_fmt(s['b'])} | +/-{_fmt(s['band_b'])} ({s['dom_b'] or '-'}) | {wb(s['b'], s['band_b'], s['with_band_b'])} | {_fmt(s['limit'])} |")
    L.append("\n## Running line\n")
    L += [f"| N/N_d | SM A | SM B | thrust A | thrust B | PR A | PR B | B schedule |", "|---|---|---|---|---|---|---|---|"]
    for r in res["running_line"]:
        sb = r["sched_b"]
        sched = ", ".join(f"{k} {v:.2f}" for k, v in (("bleed", sb.get("bleed")), ("igv", sb.get("igv"))) if v)
        L.append(f"| {r['N']:.2f} | {_fmt(r['SM_a'])} | {_fmt(r['SM_b'])} | {_fmt(r['Fn_a'], 0)} | {_fmt(r['Fn_b'], 0)} | {_fmt(r['PR_a'], 2)} | {_fmt(r['PR_b'], 2)} | {sched} |")
    L.append("\n## Rules that changed\n")
    ch = [r for r in res["rules"] if r["changed"]]
    if ch:
        L += ["| rule | stage | A value (verdict) | B value (verdict) | margin A -> B | tier |", "|---|---|---|---|---|---|"]
        for r in ch:
            a, b = r["a"], r["b"]
            fa = f"{_fmt(a['value'])} ({a['verdict']})" if a else "-"
            fb = f"{_fmt(b['value'])} ({b['verdict']})" if b else "-"
            ma = f"{a['margin']:+.1%}" if a and isinstance(a.get("margin"), (int, float)) else "-"
            mb = f"{b['margin']:+.1%}" if b and isinstance(b.get("margin"), (int, float)) else "-"
            L.append(f"| {r['id']} {r['name']} | {r['stage']} | {fa} | {fb} | {ma} -> {mb} | {r['tier'] or '-'} |")
    else:
        L.append("(no rule differs)")
    verd = {}
    for r in res["rules"]:
        for side, key in ((r["a"], "A"), (r["b"], "B")):
            if side:
                verd.setdefault(key, {}).setdefault(side["verdict"], 0)
                verd[key][side["verdict"]] += 1
    L.append(f"\nVerdict counts: A {verd.get('A', {})}; B {verd.get('B', {})}.")
    tiers_diff = {s: t for s, t in res["tiers"].items() if t[0] != t[1]}
    if tiers_diff:
        L.append("\nTier differences: " + ", ".join(f"{s} {a}->{b}" for s, (a, b) in tiers_diff.items()))
    return "\n".join(L) + "\n"


def plot_compare(doc_a: dict, doc_b: dict, name_a: str, name_b: str, out: Path) -> str | None:
    """Overlay: A's full map with B's running line and surge line(s)."""
    if not get_path(doc_a, "outputs.maps.compressor_map") or not get_path(doc_b, "outputs.maps.compressor_map"):
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .plots import compressor_map_axes, _surge_polyline
    fig, ax = plt.subplots(figsize=(8.5, 6.2), dpi=130)
    compressor_map_axes(ax, doc_a, layers=["speed", "surge", "choke", "eta", "run", "ghost", "tags"])
    cm_b = get_path(doc_b, "outputs.maps.compressor_map")
    Ws, PRs, _ = _surge_polyline(cm_b)
    if len(Ws) >= 2:
        ax.plot(Ws, PRs, "--", color="tab:orange", lw=1.4, label=f"surge line {name_b}")
    rl = [p for p in get_path(doc_b, "outputs.offdesign.running_line", []) or [] if p.get("converged")]
    if rl:
        ax.plot([p["W_corr"] for p in rl], [p["PR_c"] for p in rl], "-s", color="tab:orange", ms=4, lw=1.8, label=f"running line {name_b}")
    ax.set_title(f"{name_a} (blue) vs {name_b} (orange)", fontsize=10)
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return str(out)
