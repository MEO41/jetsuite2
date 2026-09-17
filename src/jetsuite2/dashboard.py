"""Single self-contained HTML dashboard per design (roadmap section 8): headline, freeze state, every rule with
its verdict and band arithmetic, stage status and provenance, and every plot the analyses wrote, embedded
as base64 so the file travels on its own.  ``jet dashboard`` writes ``dashboard.html`` in the design folder."""
from __future__ import annotations

import base64
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .stages import ORDER

PLOT_ORDER = ["analysis/plots/compressor_map.png", "analysis/plots/turbine_map.png", "analysis/plots/smith_balje.png",
              "analysis/plots/campbell.png", "analysis/envelope.png", "analysis/transient.png", "analysis/offdesign.png",
              "analysis/rotordynamics.png", "analysis/testbench_run.png", "analysis/maps.png", "analysis/compare_vs_p500.png"]


def _img(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<figure><img src="data:image/png;base64,{data}" alt="{html.escape(path.name)}"><figcaption>{html.escape(str(path.name))}</figcaption></figure>'


def render(design) -> str:
    from .compare import freeze_status
    from .plots import plots_stale
    doc = design.doc
    s = design.summary()
    fz = freeze_status(design)
    rules = design.rules()
    status = design.status()
    L = ["<!DOCTYPE html><html><head><meta charset='utf-8'>", f"<title>{html.escape(doc['name'])} dashboard</title>",
         "<style>body{font-family:system-ui,sans-serif;margin:18px;color:#222} h1,h2{margin:.6em 0 .3em} table{border-collapse:collapse;font-size:13px}"
         "td,th{border:1px solid #ccc;padding:3px 6px;text-align:left;vertical-align:top} th{background:#f3f3f3} .fail{background:#fde2e2} .warn{background:#fff3cd}"
         " .pass{background:#e6f4ea} .info{color:#666} figure{display:inline-block;margin:8px;max-width:48%} img{max-width:100%;border:1px solid #ddd}"
         " figcaption{font-size:11px;color:#666} .band{font-family:monospace;font-size:12px;color:#444} .tag{display:inline-block;padding:1px 6px;border-radius:3px;background:#eee;font-size:12px;margin-right:6px}"
         " details{margin:6px 0}</style></head><body>"]
    L.append(f"<h1>{html.escape(doc['name'])} <span class='tag'>v{design.store.version:04d}</span> <span class='tag'>{html.escape(s['verdict'])}</span> "
             f"<span class='tag'>{'FROZEN' if fz['frozen'] else 'not frozen'}</span></h1>")
    L.append(f"<p class='info'>Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}. {html.escape(fz['reason'])}. "
             f"Every number carries its tier; a margin that mixes tiers is reported at the lowest one.</p>")
    L.append("<h2>Headline</h2><table><tr>" + "".join(f"<th>{html.escape(k)}</th>" for k in s) + "</tr><tr>"
             + "".join(f"<td>{(f'{v:.4g}' if isinstance(v, float) else html.escape(str(v)))}</td>" for v in s.values()) + "</tr></table>")
    # rules
    L.append("<h2>Rules</h2><table><tr><th>id</th><th>rule</th><th>value</th><th>limit</th><th>margin</th><th>verdict</th><th>tier</th><th>source / band</th></tr>")
    for r in rules:
        v = r.get("value"); lim = r.get("limit"); m = r.get("margin")
        band = f"<div class='band'>{html.escape(r['band_statement'])}</div>" if r.get("band_statement") else ""
        L.append(f"<tr class='{r['verdict']}'><td>{r['id']}</td><td>{html.escape(r['name'])}</td><td>{(f'{v:.4g}' if isinstance(v, (int, float)) else '-')}</td>"
                 f"<td>{(f'{lim:.4g}' if isinstance(lim, (int, float)) else '-')} {html.escape(r.get('unit') or '')}</td>"
                 f"<td>{(f'{100*m:+.1f} %' if isinstance(m, (int, float)) else '-')}</td><td>{r['verdict']}</td><td>{html.escape(str(r.get('tier') or '-'))}</td>"
                 f"<td>{html.escape(r.get('source') or '')}{band}</td></tr>")
    L.append("</table>")
    # status / provenance
    ps = plots_stale(design)
    L.append("<h2>Stages</h2><table><tr><th>stage</th><th>kind</th><th>tier</th><th>last run</th><th>stale</th><th>overrides (L3)</th></tr>")
    for r in status:
        ov = ", ".join(f"{k} [{t}]" for k, t in r["overrides"].items()) or "-"
        L.append(f"<tr class='{'warn' if r['stale'] else ''}'><td>{r['stage']}</td><td>{'core' if r['core'] else 'analysis'}</td><td>{r['tier']}</td>"
                 f"<td>{html.escape(r['at'] or 'never')}</td><td>{html.escape(r['stale'] or '')}</td><td>{html.escape(ov)}</td></tr>")
    L.append("</table>")
    if ps:
        L.append(f"<p class='warn'>plots stale: inputs changed in {', '.join(ps)} (run `jet plot all`)</p>")
    # plots
    root = Path(design.dir)
    figs = [root / p for p in PLOT_ORDER if (root / p).exists()]
    figs += sorted(p for p in (root / "analysis").glob("*.png") if p not in figs) if (root / "analysis").exists() else []
    if figs:
        L.append("<h2>Plots</h2>" + "".join(_img(p) for p in figs))
    # open findings from the roadmap-style rule notes
    fails = [r for r in rules if r["verdict"] == "fail"]
    if fails:
        L.append("<h2>Open findings (failed rules)</h2><ul>" + "".join(
            f"<li><b>{r['id']}</b> {html.escape(r['name'])}: {html.escape(r.get('note') or '')}</li>" for r in fails) + "</ul>")
    L.append("</body></html>")
    return "\n".join(L)


def write(design, out=None) -> str:
    out = Path(out or (Path(design.dir) / "dashboard.html"))
    out.write_text(render(design), encoding="utf-8")
    return str(out)
