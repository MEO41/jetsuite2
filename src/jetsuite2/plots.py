"""Plot suite (roadmap section 4): the compressor map as the one picture from which
operability is legible, plus turbine map, Smith/Balje placement and Campbell.

Layers on the compressor map (each is a toggleable group in the SVG/HTML output):

* speed lines (solid: stable branch, dotted: stalled branch from the loss model)
* surge line with its calibrated band (+/- ``closs.SURGE_BAND_SM`` in SM), stall region hatched
* choke line
* efficiency islands
* scheduled running line (markers filled where bleed / nozzle / IGV are acting) and the
  unscheduled running line ghosted behind it
* transient trajectories (start, slam accel, decel)
* tier tags: the fidelity of every input to the picture and the surge-band provenance

Outputs: PNG + SVG (``jet plot map``) and a dependency-free interactive HTML (layer toggles,
crosshair read-out of corrected flow / PR / nearest speed line / surge margin).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .perf import closs

LAYER_COLORS = dict(speed="0.25", surge="tab:red", choke="tab:purple", eta="tab:green", run="tab:blue",
                    ghost="0.5", start="tab:orange", accel="tab:red", decel="tab:cyan")


def _tier(doc, stage):
    st = doc.get("stamps", {}).get(stage, {})
    if st.get("tier"):
        return st["tier"]
    try:
        import importlib
        return getattr(importlib.import_module(f"jetsuite2.stages.{stage}"), "TIER", "L1")
    except Exception:
        return "L?"


def _surge_polyline(cmap):
    pts = sorted([(ln["surge_W_corr"], ln["surge_PR"], ln["N_frac"]) for ln in cmap["lines"]], key=lambda p: p[1])
    return np.array([p[0] for p in pts]), np.array([p[1] for p in pts]), [p[2] for p in pts]


def compressor_map_axes(ax, doc: dict, layers=None, annotate=True) -> dict:
    """Draw the layered compressor map on ``ax``.  Returns the layer -> artists map (for gids)."""
    o = doc["outputs"]
    mp = o.get("maps")
    if not mp:
        raise RuntimeError("no maps output: run `jet analyze maps` first")
    cmap = mp["compressor_map"]
    band = float(cmap.get("surge_band_SM", closs.SURGE_BAND_SM))
    layers = set(layers or ["speed", "surge", "choke", "eta", "run", "ghost", "transient", "tags"])
    groups: dict[str, list] = {}

    def add(layer, art):
        groups.setdefault(layer, []).extend(art if isinstance(art, (list, tuple)) else [art])
        return art

    # ---- speed lines
    W_all, PR_all, eta_all = [], [], []
    for ln in cmap["lines"]:
        W, PR, eta = np.array(ln["W_corr"]), np.array(ln["PR"]), np.array(ln["eta"])
        stable = W >= ln["surge_W_corr"] * 0.999
        if "speed" in layers:
            # drawn only between the surge and choke intercepts; the loss model's stalled branch is a separate, off-by-default layer
            add("speed", ax.plot(W[stable], PR[stable], "-", color=LAYER_COLORS["speed"], lw=1.0))
            if "stalled-branch" in layers:
                add("stalled-branch", ax.plot(W[~stable | np.roll(stable, -1)], PR[~stable | np.roll(stable, -1)], ":", color=LAYER_COLORS["speed"], lw=0.8))
            i = int(np.argmax(W[stable])) if stable.any() else 0
            add("speed", [ax.annotate(f"{ln['N_frac']:.2f}", (W[stable][i], PR[stable][i]), fontsize=7, color=LAYER_COLORS["speed"],
                                      xytext=(3, -8), textcoords="offset points")])
        W_all += list(W[stable]); PR_all += list(PR[stable]); eta_all += list(eta[stable])

    # ---- surge line, band, stall region
    Ws, PRs, Ns = _surge_polyline(cmap)
    if "surge" in layers and len(Ws) >= 2:
        lo, hi = Ws * (1 - band), Ws * (1 + band)
        add("surge", [ax.fill_betweenx(PRs, lo, hi, color=LAYER_COLORS["surge"], alpha=0.15, lw=0,
                                       label=f"surge band +/-{band:.3f} SM (rig-calibrated)")])
        add("surge", ax.plot(Ws, PRs, "-", color=LAYER_COLORS["surge"], lw=1.6, label="surge line (loss-model stall onset)"))
        xmin = min(W_all) * 0.6 if W_all else 0
        add("surge", [ax.fill_betweenx(PRs, np.full_like(Ws, xmin), lo, facecolor="none", hatch="///",
                                       edgecolor=LAYER_COLORS["surge"], alpha=0.25, lw=0, label="stalled (model)")])
    # ---- surge lines of the other IGV settings (the running line uses the map of the scheduled IGV angle)
    fam = mp.get("compressor_maps_igv") or []
    if "surge" in layers and len(fam) > 1:
        for k, m_igv in enumerate(fam[1:], 1):
            Wi, PRi, _ = _surge_polyline(m_igv)
            if len(Wi) >= 2:
                add("surge", ax.plot(Wi, PRi, "--", color=LAYER_COLORS["surge"], lw=1.0, alpha=0.5 + 0.5 * k / len(fam),
                                     label=f"surge line, IGV {m_igv.get('igv_deg', 0):.0f} deg (L2 extrapolation)"))
    # ---- choke line
    if "choke" in layers:
        ch = sorted([(ln["choke_W_corr"], min(ln["PR"]), ln["N_frac"]) for ln in cmap["lines"]], key=lambda p: p[1])
        add("choke", ax.plot([p[0] for p in ch], [p[1] for p in ch], "--", color=LAYER_COLORS["choke"], lw=1.2, label="choke line"))
    # ---- efficiency islands
    if "eta" in layers and len(cmap["lines"]) >= 3:
        # structured (speed x position-along-line) grid from surge to choke: clean islands, no cross-line triangulation
        try:
            s = np.linspace(0, 1, 30)
            Wg, PRg, Eg = [], [], []
            for ln in sorted(cmap["lines"], key=lambda l: l["N_frac"]):
                W, PR, eta = np.array(ln["W_corr"]), np.array(ln["PR"]), np.array(ln["eta"])
                k = W >= ln["surge_W_corr"] * 0.999
                if k.sum() < 3:
                    continue
                W, PR, eta = W[k], PR[k], eta[k]
                u = (W - W[0]) / max(W[-1] - W[0], 1e-9)
                Wg.append(np.interp(s, u, W)); PRg.append(np.interp(s, u, PR)); Eg.append(np.interp(s, u, eta))
            Wg, PRg, Eg = np.array(Wg), np.array(PRg), np.array(Eg)
            emax = float(Eg.max())
            levels = sorted(set([round(l, 2) for l in np.arange(0.50, emax - 0.02, 0.05)] + [round(emax - 0.03, 2), round(emax - 0.01, 2)]))
            cs = ax.contour(Wg, PRg, Eg, levels=levels, colors=LAYER_COLORS["eta"], linewidths=0.6, alpha=0.8)
            add("eta", list(cs.collections) if hasattr(cs, "collections") else [cs])
            ax.clabel(cs, fmt="%.2f", fontsize=6, inline=True)
        except Exception:
            pass
    # ---- running lines
    od = o.get("offdesign")
    if od and "ghost" in layers and od.get("unscheduled_line"):
        gh = [p for p in od["unscheduled_line"] if p["converged"]]
        add("ghost", ax.plot([p["W_corr"] for p in gh], [p["PR_c"] for p in gh], "-", color=LAYER_COLORS["ghost"], lw=1.4, alpha=0.6,
                             label="running line, unscheduled (ghost)"))
    if od and "run" in layers:
        rl = [p for p in od["running_line"] if p["converged"]]
        sched = any(p.get("bleed", 0) > 0 or (p.get("A8") and abs(p.get("A8_ratio", 1) - 1) > 1e-6) or p.get("igv_deg", 0) for p in rl)
        add("run", ax.plot([p["W_corr"] for p in rl], [p["PR_c"] for p in rl], "-", color=LAYER_COLORS["run"], lw=1.8,
                           label="running line" + (" (scheduled)" if sched else "")))
        act = [p for p in rl if p.get("bleed", 0) > 0 or p.get("igv_deg", 0)]
        nact = [p for p in rl if p not in act]
        add("run", ax.plot([p["W_corr"] for p in nact], [p["PR_c"] for p in nact], "o", color=LAYER_COLORS["run"], ms=4))
        if act:
            add("run", ax.plot([p["W_corr"] for p in act], [p["PR_c"] for p in act], "s", mfc="white", color=LAYER_COLORS["run"], ms=5,
                               label="bleed / IGV acting"))
        # SAE surge margin annotated along the running line (every other point), with the band
        for k, p in enumerate(rl):
            if k % 2 == 0 and p["N_frac"] <= 1.0:
                add("run", [ax.annotate(f"SM {p['SM']:+.2f}", (p["W_corr"], p["PR_c"]), fontsize=6, xytext=(6, -9),
                                        textcoords="offset points", color=LAYER_COLORS["run"], alpha=0.9)])
        if "SM_min" in od and od.get("SM_min") is not None:
            pmin = min(rl, key=lambda p: p["SM"])
            add("run", [ax.annotate(f"SM min {od['SM_min']:+.2f} +/-{band:.3f} @ {od['SM_min_N_frac']:.2f} N", (pmin["W_corr"], pmin["PR_c"]),
                                    fontsize=7, xytext=(-10, 14), textcoords="offset points", color=LAYER_COLORS["run"],
                                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=LAYER_COLORS["run"], alpha=0.9))])
    # ---- transients
    tr = o.get("transient", {}).get("trajectories") if o.get("transient") else None
    if tr and "transient" in layers:
        for name in ("start", "accel", "decel"):
            t = tr.get(name)
            if not t:
                continue
            W, PR = np.array(t["W_corr"]), np.array(t["PR_c"])
            ok = np.isfinite(W) & np.isfinite(PR) & (PR > 1.0)
            if ok.sum() < 2:
                continue
            add("transient", ax.plot(W[ok], PR[ok], "-", color=LAYER_COLORS[name], lw=1.0, alpha=0.9, label=f"transient: {name}"))
            k = int(ok.sum() * 0.6)
            idx = np.where(ok)[0]
            if k + 1 < len(idx):
                i0, i1 = idx[k], idx[k + 1]
                add("transient", [ax.annotate("", (W[i1], PR[i1]), (W[i0], PR[i0]),
                                              arrowprops=dict(arrowstyle="->", color=LAYER_COLORS[name], lw=1.0))])
    # ---- design point
    dp = mp.get("design_point", {})
    if dp:
        add("run", ax.plot([dp.get("W_corr", np.nan)], [dp.get("PR", np.nan)], "k*", ms=9, label="design point"))
    ax.set_xlabel("corrected flow  W sqrt(theta)/delta  [kg/s]")
    ax.set_ylabel("total pressure ratio")
    ax.grid(alpha=0.3)
    if "tags" in layers and annotate:
        tags = [f"maps {_tier(doc, 'maps')}", f"offdesign {_tier(doc, 'offdesign')}" if od else None,
                f"transient {_tier(doc, 'transient')}" if tr else None, f"surge band {_tier(doc, 'maps')} (HECC/CC3 residuals)"]
        igv = cmap.get("igv_deg", 0.0)
        txt = "  |  ".join(t for t in tags if t) + (f"  |  IGV {igv:.0f} deg" if igv else "")
        add("tags", [ax.text(0.01, 0.99, txt, transform=ax.transAxes, fontsize=7, va="top",
                             bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=0.9))])
    ax.legend(fontsize=7, loc="lower right")
    return groups


def turbine_map_axes(ax, doc: dict):
    """Turbine map: corrected flow vs total-to-static PR, speed lines, eta_tt contours, running-line points."""
    o = doc["outputs"]
    tm = o["maps"]["turbine_map"]
    lines = sorted(tm["lines"], key=lambda l: l["N_frac"])
    for ln in lines:
        ax.plot(ln["PR_ts"], ln["W_corr"], "-", lw=1.0, color="0.3")
        ax.annotate(f"{ln['N_frac']:.2f}", (ln["PR_ts"][-1], ln["W_corr"][-1]), fontsize=7, xytext=(3, 0), textcoords="offset points")
    # efficiency contours on a structured (speed x PR-position) grid
    try:
        s = np.linspace(0, 1, 30)
        X, Y, Z = [], [], []
        for ln in lines:
            pr, w, e = np.array(ln["PR_ts"]), np.array(ln["W_corr"]), np.array(ln["eta_tt"])
            if len(pr) < 3:
                continue
            u = (pr - pr[0]) / max(pr[-1] - pr[0], 1e-9)
            X.append(np.interp(s, u, pr)); Y.append(np.interp(s, u, w)); Z.append(np.interp(s, u, e))
        X, Y, Z = np.array(X), np.array(Y), np.array(Z)
        emax = float(Z.max())
        levels = sorted(set([round(l, 2) for l in np.arange(0.60, emax - 0.02, 0.05)] + [round(emax - 0.03, 2), round(emax - 0.01, 2)]))
        cs = ax.contour(X, Y, Z, levels=levels, colors=LAYER_COLORS["eta"], linewidths=0.6, alpha=0.8)
        ax.clabel(cs, fmt="%.2f", fontsize=6, inline=True)
    except Exception:
        pass
    od = o.get("offdesign")
    if od:
        pts = [p for p in od["running_line"] if p["converged"] and p.get("PR_t") and p.get("W_corr_t")]
        if pts:
            ax.plot([p["PR_t"] for p in pts], [p["W_corr_t"] for p in pts], "b-o", ms=3, lw=1.4, label="running line")
    dp = o["maps"].get("design_point", {})
    if dp.get("PR_t") and dp.get("W_corr_t"):
        ax.plot([dp["PR_t"]], [dp["W_corr_t"]], "k*", ms=9, label="design point")
    ax.set_xlabel("total-to-static pressure ratio"); ax.set_ylabel("corrected flow  W sqrt(T04)/P04  [kg/s]"); ax.grid(alpha=0.3)
    ax.text(0.01, 0.99, f"maps {_tier(doc, 'maps')}  |  AMDC / Kacker-Okapuu mean-line (validated +/-8 % flow, +/-12 pts eta at part speed)",
            transform=ax.transAxes, fontsize=7, va="top", bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=0.9))
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=7, loc="lower right")
    ax.set_title(f"{doc.get('name', 'design')} turbine map", fontsize=10)


def smith_balje_axes(ax_smith, ax_balje, doc: dict):
    """Turbine Smith placement (psi vs phi against the Smith (1965) efficiency contours, L0 correlation) and
    compressor Balje/Cordier placement (Ns vs Ds against the achievable-efficiency band, L0/L1)."""
    o = doc["outputs"]
    t = o["turbine"]
    # Smith chart: eta_tt contours approximated as ellipses around (phi 0.6, psi 1.0), eta_max 0.94 (Smith 1965, zero clearance)
    phi = np.linspace(0.3, 1.2, 120); psi = np.linspace(0.5, 3.0, 120)
    PH, PS = np.meshgrid(phi, psi)
    ETA = 0.94 - 0.10 * ((PH - 0.62) / 0.35) ** 2 - 0.045 * ((PS - 1.1) / 0.9) ** 2 - 0.02 * np.maximum(PS - 1.6, 0)
    cs = ax_smith.contour(PH, PS, ETA, levels=[0.80, 0.84, 0.86, 0.88, 0.90, 0.92, 0.93], colors=LAYER_COLORS["eta"], linewidths=0.6)
    ax_smith.clabel(cs, fmt="%.2f", fontsize=6, inline=True)
    eta_t = o["cycle"].get("eta_t") or doc["inputs"]["cycle"].get("eta_t")
    ax_smith.plot([t["phi"]], [t["psi"]], "r*", ms=11, label=f"design: phi {t['phi']:.2f}, psi {t['psi']:.2f}")
    ax_smith.set_xlabel("flow coefficient  phi = Cm / U"); ax_smith.set_ylabel("loading  psi = dh0 / U^2"); ax_smith.grid(alpha=0.3)
    ax_smith.legend(fontsize=7, loc="upper right")
    ax_smith.set_title("turbine Smith placement (L0 contours, zero clearance; micro scale sits 5-8 pts lower)", fontsize=8)
    # Balje / Cordier: compressor Ns-Ds against the Cordier line and the achievable-efficiency band
    b = o.get("assess", {}).get("balje")
    Ns = np.logspace(-1, 0.6, 100)
    Ds_cordier = 2.3 / Ns ** 0.85       # Cordier line (Balje 1981, radial machines)
    ax_balje.loglog(Ns, Ds_cordier, "-", color="0.4", lw=1.2, label="Cordier line (radial)")
    ax_balje.fill_between(Ns, Ds_cordier * 0.8, Ds_cordier * 1.25, color=LAYER_COLORS["eta"], alpha=0.12, label="eta_max band (Balje: 0.80-0.88 centrifugal)")
    if b:
        ax_balje.loglog([b["Ns"]], [b["Ds"]], "r*", ms=11, label=f"design: Ns {b['Ns']:.2f}, Ds {b['Ds']:.2f}, eta_achievable {b['eta_achievable']:.2f}")
    ax_balje.set_xlabel("specific speed Ns"); ax_balje.set_ylabel("specific diameter Ds"); ax_balje.grid(alpha=0.3, which="both")
    ax_balje.legend(fontsize=7, loc="upper right")
    ax_balje.set_title(f"compressor Balje / Cordier placement (assess {_tier(doc, 'assess')})", fontsize=8)


def campbell_axes(ax, doc: dict):
    """Campbell diagram: whirl frequencies vs speed, engine-order lines, operating range and blade-mode crossings."""
    o = doc["outputs"]
    rd = o.get("rotordyn")
    if not rd:
        raise RuntimeError("no rotordyn output: run `jet analyze rotordyn` first")
    cb = rd["campbell"]
    rpm = np.array(cb["rpm"], float)

    def _pad(rows):  # mode count may vary per speed (modal reduction): pad with nan
        n = max((len(r) for r in rows), default=0)
        return np.array([list(r) + [np.nan] * (n - len(r)) for r in rows], float)
    fw, bw = _pad(cb["forward"]) / 60.0, _pad(cb["backward"]) / 60.0     # stored in cpm -> Hz
    N_design = o["speed"]["rpm"]
    rpm_max = float(rpm.max())
    fmax = 2.5 * rpm_max / 60.0
    for j in range(fw.shape[1] if fw.ndim == 2 else 0):
        ax.plot(rpm / 1e3, fw[:, j], "-", color="tab:blue", lw=1.0, label="forward whirl" if j == 0 else None)
        ax.plot(rpm / 1e3, bw[:, j], "--", color="tab:cyan", lw=0.8, label="backward whirl" if j == 0 else None)
    orders = rd.get("blade_modes", {}).get("orders", {"1x": 1})
    for name, k in orders.items():
        f = rpm / 60.0 * k
        m = f <= fmax
        if m.any():
            ax.plot(rpm[m] / 1e3, f[m], ":", color="0.5", lw=0.8)
            ax.annotate(f"{k}x {name}", (rpm[m][-1] / 1e3, f[m][-1]), fontsize=6, color="0.4", xytext=(2, 0), textcoords="offset points")
    idle = o.get("control", {}).get("idle_N", 0.5)
    nmax = o.get("control", {}).get("N_max_frac", 1.05)
    ax.axvspan(idle * N_design / 1e3, nmax * N_design / 1e3, color="tab:orange", alpha=0.12, label=f"operating range {idle:.2f}-{nmax:.2f} N")
    ax.axvline(N_design / 1e3, color="k", lw=0.8)
    # blade-mode crossings inside the plotted range (the stage lists all crossings, many far above max speed)
    bm = rd.get("blade_modes", {})
    for key in ("exducer_f1_Hz", "turbine_blade_f1_Hz"):
        if bm.get(key) and bm[key] <= fmax:
            ax.axhline(bm[key], color="tab:red", lw=0.7, ls="-.", alpha=0.7)
            ax.annotate(key.replace("_Hz", ""), (0.02 * rpm_max / 1e3, bm[key]), fontsize=6, color="tab:red", xytext=(0, 2), textcoords="offset points")
    for c in bm.get("crossings", []):
        if c.get("rpm") and c.get("f_Hz") and c["rpm"] <= rpm_max and c["f_Hz"] <= fmax:
            ax.plot([c["rpm"] / 1e3], [c["f_Hz"]], "rx", ms=7, mew=1.5)
    ax.set_xlabel("spool speed [krpm]"); ax.set_ylabel("frequency [Hz]"); ax.grid(alpha=0.3)
    ax.set_xlim(0, rpm_max / 1e3); ax.set_ylim(0, fmax)
    ax.legend(fontsize=7, loc="upper left")
    ax.set_title(f"{doc.get('name', 'design')} Campbell diagram (rotordyn {_tier(doc, 'rotordyn')}; x = blade-mode crossings)", fontsize=9)


def _inject_html(svg_text: str, groups: list[str], data: dict, title: str) -> str:
    """Wrap the matplotlib SVG in an HTML page with layer toggles and a crosshair read-out."""
    toggles = "\n".join(f'<label><input type="checkbox" checked data-layer="{g}"> {g}</label>' for g in groups)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;margin:12px}} #ctl label{{margin-right:12px;font-size:13px}}
#ro{{font:12px monospace;background:#f4f4f4;padding:6px;border-radius:4px;display:inline-block;min-width:520px}}
svg{{max-width:100%;height:auto}} .hidden{{display:none}}</style></head><body>
<h3>{title}</h3><div id="ctl">{toggles}</div><div id="ro">hover the map</div>
<div id="wrap">{svg_text}</div>
<script>
const D={json.dumps(data)};
document.querySelectorAll('#ctl input').forEach(cb=>cb.addEventListener('change',()=>{{
  document.querySelectorAll('svg [id^="layer-'+cb.dataset.layer+'"]').forEach(g=>g.classList.toggle('hidden',!cb.checked));}}));
const svg=document.querySelector('svg');
function toData(ev){{
  const pt=svg.createSVGPoint(); pt.x=ev.clientX; pt.y=ev.clientY;
  const p=pt.matrixTransform(svg.getScreenCTM().inverse());
  const b=D.axes; const W=b.x0+(p.x-b.px0)/(b.px1-b.px0)*(b.x1-b.x0); const PR=b.y0+(b.py0-p.y)/(b.py0-b.py1)*(b.y1-b.y0);
  return [W,PR];}}
function interp(xs,ys,x){{ if(x<=xs[0])return ys[0]; if(x>=xs[xs.length-1])return ys[ys.length-1];
  for(let i=1;i<xs.length;i++) if(x<=xs[i]){{const t=(x-xs[i-1])/(xs[i]-xs[i-1]);return ys[i-1]+t*(ys[i]-ys[i-1]);}} return ys[ys.length-1];}}
svg.addEventListener('mousemove',ev=>{{
  const [W,PR]=toData(ev); if(!(W>0&&PR>0))return;
  let best=null;
  for(const ln of D.lines){{ for(let i=0;i<ln.W.length;i++){{ const d=Math.hypot((ln.W[i]-W)/D.scale.W,(ln.PR[i]-PR)/D.scale.PR);
      if(!best||d<best.d) best={{d,N:ln.N,eta:ln.eta[i],W:ln.W[i],PR:ln.PR[i],Ws:ln.Ws,PRs:ln.PRs}};}} }}
  let txt=`W_corr ${{W.toFixed(3)}} kg/s   PR ${{PR.toFixed(3)}}`;
  if(best){{ const SM=(best.PRs*W)/(PR*best.Ws)-1; txt+=`   nearest line N ${{best.N.toFixed(2)}}  eta ${{best.eta.toFixed(3)}}  SM vs its surge point ${{(SM*100).toFixed(1)}} % (+/-${{(D.band*100).toFixed(1)}})`; }}
  document.getElementById('ro').textContent=txt;}});
</script></body></html>"""


def plot_compressor_map(design, out_dir: Path | None = None, formats=("png", "svg", "html"), igv_index: int | None = None) -> dict:
    """Write the layered compressor map.  Returns the written paths."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    doc = design.doc
    out_dir = Path(out_dir or (Path(design.dir) / "analysis" / "plots"))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    fig, ax = plt.subplots(figsize=(8.5, 6.2), dpi=130)
    ax.set_title(f"{doc.get('name', 'design')} compressor map", fontsize=10)
    groups = compressor_map_axes(ax, doc)
    for name, arts in groups.items():
        for i, a in enumerate(arts):
            try:
                a.set_gid(f"layer-{name}-{i}")
            except Exception:
                pass
    fig.tight_layout()
    if "png" in formats:
        p = out_dir / "compressor_map.png"; fig.savefig(p); written["png"] = str(p)
    if "svg" in formats or "html" in formats:
        p = out_dir / "compressor_map.svg"; fig.savefig(p, format="svg"); written["svg"] = str(p)
    if "html" in formats:
        fig.canvas.draw()
        bb = ax.get_window_extent()
        H = fig.get_figheight() * fig.dpi
        x0, x1 = ax.get_xlim(); y0, y1 = ax.get_ylim()
        cmap = doc["outputs"]["maps"]["compressor_map"]
        data = dict(axes=dict(px0=bb.x0 * 72 / fig.dpi, px1=bb.x1 * 72 / fig.dpi, py0=(H - bb.y0) * 72 / fig.dpi, py1=(H - bb.y1) * 72 / fig.dpi,
                              x0=x0, x1=x1, y0=y0, y1=y1),
                    band=float(cmap.get("surge_band_SM", closs.SURGE_BAND_SM)), scale=dict(W=(x1 - x0), PR=(y1 - y0)),
                    lines=[dict(N=ln["N_frac"], W=ln["W_corr"], PR=ln["PR"], eta=ln["eta"], Ws=ln["surge_W_corr"], PRs=ln["surge_PR"])
                           for ln in cmap["lines"]])
        svg_text = Path(written["svg"]).read_text(encoding="utf-8")
        svg_text = svg_text[svg_text.index("<svg"):]
        p = out_dir / "compressor_map.html"
        p.write_text(_inject_html(svg_text, list(groups.keys()), data, f"{doc.get('name', 'design')} compressor map"), encoding="utf-8")
        written["html"] = str(p)
    plt.close(fig)
    return written


def plot_turbine_map(design, out_dir=None, formats=("png", "svg")) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out_dir = Path(out_dir or (Path(design.dir) / "analysis" / "plots")); out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 5), dpi=130)
    turbine_map_axes(ax, design.doc)
    fig.tight_layout()
    written = {}
    for f in formats:
        p = out_dir / f"turbine_map.{f}"; fig.savefig(p, format=f); written[f] = str(p)
    plt.close(fig)
    return written


def _figure_writer(name, draw, figsize):
    def write(design, out_dir=None, formats=("png", "svg")) -> dict:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        out_dir = Path(out_dir or (Path(design.dir) / "analysis" / "plots")); out_dir.mkdir(parents=True, exist_ok=True)
        fig = plt.figure(figsize=figsize, dpi=130)
        draw(fig, design.doc)
        fig.tight_layout()
        written = {}
        for f in formats:
            p = out_dir / f"{name}.{f}"; fig.savefig(p, format=f); written[f] = str(p)
        plt.close(fig)
        return written
    return write


plot_smith_balje = _figure_writer("smith_balje", lambda fig, doc: smith_balje_axes(*fig.subplots(1, 2), doc), (11, 4.6))
plot_campbell = _figure_writer("campbell", lambda fig, doc: campbell_axes(fig.subplots(), doc), (7.5, 5))


def plot_all(design, out_dir=None) -> dict:
    """Every plot whose inputs exist; the others are reported, not raised."""
    w = dict(compressor=plot_compressor_map(design, out_dir))
    for name, fn in (("turbine", plot_turbine_map), ("smith_balje", plot_smith_balje), ("campbell", plot_campbell)):
        try:
            w[name] = fn(design, out_dir)
        except Exception as e:
            w[name] = dict(skipped=str(e))
    _write_manifest(design, out_dir)
    return w


def _write_manifest(design, out_dir=None):
    """Record which stage stamps the plots were made from, so `jet status` / `jet plot` can flag them stale."""
    out_dir = Path(out_dir or (Path(design.dir) / "analysis" / "plots"))
    st = design.doc.get("stamps", {})
    man = {s: (st.get(s, {}).get("inputs_hash")) for s in ("maps", "offdesign", "transient", "assess", "rotordyn")}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")


def plots_stale(design) -> list[str]:
    """Stages whose stamp changed since the plots were written (empty if the plots are current or absent)."""
    p = Path(design.dir) / "analysis" / "plots" / "manifest.json"
    if not p.exists():
        return []
    man = json.loads(p.read_text(encoding="utf-8"))
    st = design.doc.get("stamps", {})
    return [s for s, h in man.items() if h and (st.get(s, {}).get("inputs_hash")) != h]
