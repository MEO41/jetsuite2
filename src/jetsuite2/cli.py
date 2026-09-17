"""``jet`` command line.

    jet new <dir> [--thrust N] [--alt m] [--mach M] [--set stage.key=value ...]
    jet run [-d dir] [--force] [--upto stage]
    jet set [-d dir] stage.key=value ... [--run]
    jet show [-d dir] [stage] [--json]
    jet inputs [-d dir] [stage]
    jet rules [-d dir] [--all]
    jet stale [-d dir]
    jet diff [-d dir] [v1] [v2]
    jet history [-d dir]
    jet checkout [-d dir] <version>
    jet converge [-d dir] [--tol 0.005]
    jet library <bearings|screws|retaining_rings|locknuts|o_rings|materials> [--bore 12]
    jet cad [-d dir] [--parts a,b] [--force] [--no-assembly]
    jet report [-d dir]

The design directory defaults to the current directory (or $JET_DESIGN).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .api import Design, parse_value
from .stages import ORDER
from .rules import format_rules


def _design(args) -> Design:
    d = args.dir or os.environ.get("JET_DESIGN") or "."
    p = Path(d)
    if not (p / "design.json").exists():
        sys.exit(f"no design.json in {p.resolve()} (use `jet new <dir>` or -d <dir>)")
    return Design(p).load()


def _fmt(v):
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        a = abs(v)
        if a == 0:
            return "0"
        if a >= 1e5 or a < 1e-3:
            return f"{v:.4e}"
        return f"{v:.5g}"
    if isinstance(v, (list, tuple)):
        if len(v) > 6:
            return f"[{len(v)} items]"
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_fmt(x)}" for k, x in list(v.items())[:6]) + ("...}" if len(v) > 6 else "}")
    return str(v)


def _banner(d: Design):
    s = d.summary()
    print(f"design '{d.doc['name']}' v{d.store.version}  [{s['verdict']}]")
    if s["airflow_kg_s"]:
        print(f"  thrust {s['thrust_N']:.0f} N  airflow {s['airflow_kg_s']:.3f} kg/s  TSFC {s['TSFC_kg_N_h']:.4f} kg/N/h  "
              f"rpm {s['rpm'] or 0:.0f}")
        print(f"  impeller D2 {s['D2_mm']:.1f} mm  turbine tip {s['turbine_tip_mm']:.1f} mm  envelope OD {s['OD_mm']:.1f} x L {s['length_mm']:.0f} mm  "
              f"mass {s['mass_kg'] or 0:.2f} kg  bearing {s['bearing']}")


def _print_report(rep, d: Design):
    print(rep.summary())
    for s, ch in rep.changes.items():
        ch = [c for c in ch if c[1] is not None]   # first-run "None -> x" rows are noise
        if ch:
            top = ch[:8]
            print(f"  {s}: " + "; ".join(f"{k} {_fmt(a)} -> {_fmt(b)}" for k, a, b in top) + (" ..." if len(ch) > 8 else ""))
    print(d.rules_text(only_problems=True))
    _banner(d)


# ------------------------------------------------------------------ commands
def cmd_new(args):
    overrides = {}
    if args.thrust is not None:
        overrides["requirements.thrust_N"] = float(args.thrust)
    if args.alt is not None:
        overrides["requirements.altitude_m"] = float(args.alt)
    if args.mach is not None:
        overrides["requirements.mach"] = float(args.mach)
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        overrides[k] = parse_value(v)
    d = Design.create(args.dir, args.name, overrides)
    print(f"created {Path(args.dir).resolve()}")
    if not args.no_run:
        t0 = time.perf_counter()
        rep = d.run()
        print(f"ran design chain in {time.perf_counter()-t0:.2f} s")
        _print_report(rep, d)


def cmd_run(args):
    d = _design(args)
    t0 = time.perf_counter()
    rep = d.run(upto=args.upto, force=args.force, only=args.only.split(",") if args.only else None)
    print(f"run finished in {time.perf_counter()-t0:.2f} s")
    _print_report(rep, d)


def cmd_set(args):
    d = _design(args)
    assignments = {}
    for kv in args.assign:
        if "=" not in kv:
            sys.exit(f"expected stage.key=value, got '{kv}'")
        k, v = kv.split("=", 1)
        assignments[k] = parse_value(v)
    res = d.set(assignments)
    for p, old, new in res["changed"]:
        print(f"  {p}: {_fmt(old)} -> {_fmt(new)}")
    print("  directly affected stages: " + (", ".join(res["directly_affected"]) or "none"))
    stale = [s for s in ORDER if s in res["stale"]]
    print("  will re-run: " + (", ".join(stale) or "nothing"))
    if args.run:
        t0 = time.perf_counter()
        rep = d.run()
        print(f"re-ran in {time.perf_counter()-t0:.2f} s")
        _print_report(rep, d)


def cmd_show(args):
    d = _design(args)
    if args.stage is None:
        _banner(d)
        for s in ORDER:
            st = d.store.stamps.get(s)
            n = len(d.outputs(s))
            print(f"  {s:<13} {'ran ' + st['at'] if st else 'not run':<24} {n} outputs  {'stale' if s in d.stale() else ''}")
        return
    if args.stage not in ORDER:
        sys.exit(f"unknown stage {args.stage}. Stages: {', '.join(ORDER)}")
    o = d.outputs(args.stage)
    if args.json:
        print(json.dumps(o, indent=1, default=str))
        return
    for k, v in o.items():
        if k.startswith("_") or k in ("stations", "sheet", "holes", "eta_estimate_parts"):
            continue
        print(f"  {k:<34} {_fmt(v)}")


def cmd_inputs(args):
    d = _design(args)
    for path, v, doc in d.inputs_with_docs(args.stage):
        print(f"  {path:<40} {_fmt(v):<16} {doc}")


def cmd_rules(args):
    d = _design(args)
    print(d.rules_text(only_problems=not args.all))
    print(f"overall: {d.verdict()}")


def cmd_stale(args):
    d = _design(args)
    st = d.stale()
    if not st:
        print("  everything up to date")
    for s in ORDER:
        if s in st:
            print(f"  {s:<13} {st[s]}")


def cmd_diff(args):
    d = _design(args)
    rows = d.diff(args.v1, args.v2)
    if not rows:
        print("  no differences")
    for p, a, b in rows:
        print(f"  {p:<48} {_fmt(a):>14} -> {_fmt(b)}")


def cmd_history(args):
    d = _design(args)
    for line in d.store.log_lines():
        print("  " + line)


def cmd_checkout(args):
    d = _design(args)
    v = d.store.checkout(int(args.version))
    print(f"restored v{int(args.version):04d} as v{v:04d}")


def cmd_converge(args):
    d = _design(args)
    t0 = time.perf_counter()
    hist = d.converge(tol=args.tol)
    for h in hist:
        print(f"  pass {h['iteration']}: eta_c {h['eta_c_assumed']:.4f} (est {h['eta_c_estimate']:.4f})  "
              f"eta_t {h['eta_t_assumed']:.4f} (est {h['eta_t_estimate']:.4f})")
    print(f"converged in {time.perf_counter()-t0:.2f} s")
    print(d.rules_text(only_problems=True))
    _banner(d)


def cmd_library(args):
    from .library import components, materials
    kind = args.kind
    if kind == "materials":
        for name in materials.list_materials():
            m = materials.get(name)
            print(f"  {name:<14} {m['family']:<10} rho {m['rho']:.0f}  E {m['E']/1e9:.0f} GPa  "
                  f"Fty(RT) {m['yield_table'][0][1]:.0f} MPa  T_max {m['T_max']:.0f} K  {m['note']}")
        return
    if kind == "bearings":
        items = components.bearings(bore=args.bore)
        for b in items:
            print(f"  {b['id']:<12} {b['type']:<16} {b['bore']:>3}x{b['od']:>3}x{b['width']:<3} "
                  f"C {b['C']:.1f} kN  DN {b['dn_limit']:.1e}  Tmax {b['T_max']} K  hybrid {b.get('hybrid', False)}")
        return
    print(components.describe(kind))


def cmd_cad(args):
    d = _design(args)
    from .compare import require_frozen
    require_frozen(d, getattr(args, "unfrozen_ok", False), "CAD build")
    from .cad import build as cad_build
    t0 = time.perf_counter()
    res = cad_build.build(d, parts=args.parts.split(",") if args.parts else None, force=args.force,
                          assembly=not args.no_assembly, verbose=print)
    print(f"CAD finished in {time.perf_counter()-t0:.1f} s -> {res['dir']}")
    for name, info in res["parts"].items():
        flag = "built" if info["built"] else "cached"
        print(f"  {flag:<6} {name:<22} {info['elapsed_s']:6.2f} s  {info['volume_cm3']:8.2f} cm3  {info['mass_kg']:.3f} kg  "
              f"{'valid' if info['valid'] else 'INVALID'}")
    if res.get("assembly"):
        print(f"  assembly: {res['assembly']}  ({res['assembly_elapsed_s']:.1f} s)")
    if res.get("checks"):
        for c in res["checks"]:
            print("  " + c)


def cmd_analyze(args):
    d = _design(args)
    from .stages import ANALYSIS
    names = None if (not args.names or args.names == "all") else args.names.split(",")
    t0 = time.perf_counter()
    rep = d.analyze(names, force=args.force, verbose=print, parallel=not args.serial, workers=args.workers)
    print(f"analysis finished in {time.perf_counter()-t0:.1f} s  (available: {', '.join(ANALYSIS)})")
    print(rep.summary())
    print(d.rules_text(only_problems=True))


def cmd_status(args):
    d = _design(args)
    print(f"design '{d.doc['name']}' v{d.store.version}")
    print(f"  {'stage':<14} {'kind':<9} {'tier':<5} {'last run':<20} {'stale':<32} overrides")
    for r in d.status():
        ov = ", ".join(f"{k}[{t}]" for k, t in r["overrides"].items()) or "-"
        print(f"  {r['stage']:<14} {'core' if r['core'] else 'analysis':<9} {r['tier']:<5} {r['at'] or 'never':<20} {r['stale'][:32]:<32} {ov}")
    from .plots import plots_stale
    ps = plots_stale(d)
    if ps:
        print(f"  plots (analysis/plots) stale: inputs changed in {', '.join(ps)} -> `jet plot all`")


def cmd_ingest(args):
    d = _design(args)
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    entries = payload if isinstance(payload, list) else [payload]
    for e in entries:
        res = d.ingest(e["stage"], e["fields"], tier=e.get("tier", "L3"), source=e.get("source", Path(args.file).name))
        print(f"  ingested {e['stage']}: {', '.join(e['fields'])} as {e.get('tier', 'L3')} from {e.get('source', args.file)}")
    stale = [s for s in ORDER if s in res["stale"]]
    print("  will re-run: " + (", ".join(stale) or "nothing"))
    if args.run:
        rep = d.run()
        _print_report(rep, d)


def cmd_study(args):
    d = _design(args)
    from . import studies
    if args.action == "list":
        for s in studies.list_studies(d):
            print(f"  {s['name']:<28} {s['kind']:<12} {s['n']:>5} pts  {s['at']}  {'STALE' if s['stale'] else 'current'}")
        return
    if args.action == "show":
        print(studies.show(d, args.name))
        return
    spec = json.loads(args.spec) if args.spec and args.spec.strip().startswith("{") else \
        (json.loads(Path(args.spec).read_text(encoding="utf-8")) if args.spec else {})
    t0 = time.perf_counter()
    res = studies.run_study(d, args.action, args.name, spec, verbose=print)
    print(f"study '{args.name}' ({args.action}) finished in {time.perf_counter()-t0:.1f} s")
    print(studies.show(d, args.name))


def cmd_validate(args):
    from .validation import cases
    from .api import Design as _D
    import tempfile
    rows = []
    if args.what in ("all", "compressor"):
        rows += cases.validate_compressor_model()
    if args.what in ("all", "turbine"):
        rows += cases.validate_turbine_model()
    if args.what in ("all", "rigs"):
        rows += cases.validate_rigs()
    if args.what in ("all", "fleet"):
        def factory(e):
            tmp = Path(tempfile.mkdtemp(prefix="jet_val_"))
            ov = {"requirements.thrust_N": e["thrust_N"], "cycle.OPR": e["PR"], "speed.rpm": e["rpm"]}
            d = _D.create(tmp / "d", e["model"], ov)
            d.run()
            return d
        rows += cases.validate_design_chain(factory)
    if args.what in ("all", "paper"):
        def paper_factory(e):
            tmp = Path(tempfile.mkdtemp(prefix="jet_paper_"))
            ov = {"requirements.thrust_N": e["design"]["thrust_N"], "cycle.OPR": e["design"]["OPR"], "speed.rpm": e["design"]["rpm"]}
            d = _D.create(tmp / "d", e["name"], ov)
            d.run()
            try:
                d.converge(verbose=None)      # cycle efficiencies consistent with the loss models before matching
            except Exception:  # noqa: BLE001
                pass
            # the real engine's turbine inlet temperature is not published; back it out from the published max EGT
            # (secant on cycle.T04_K so that the design-point Tt5 matches), so thrust / fuel / flow test the sizing
            # and matching rather than a guessed T04
            egt = next((p.get("EGT_K") for p in e["points"] if p.get("name") == "max" and p.get("EGT_K")), None)
            if egt:
                T = float(d.doc["inputs"]["cycle"].get("T04_K", 1150.0)); prev = None
                for _ in range(8):
                    f = d.outputs("cycle")["Tt5_K"] - egt
                    if abs(f) < 1.0:
                        break
                    if prev is not None and abs(f - prev[1]) > 1e-6:
                        T_new = T - f * (T - prev[0]) / (f - prev[1])
                    else:
                        T_new = T - f * 1.15          # Tt5 moves ~0.87 K per K of T04
                    prev = (T, f)
                    T = min(max(T_new, 900.0), 1400.0)
                    d.set({"cycle.T04_K": T}); d.run()
                e["design"]["T04_K_solved"] = T
                print(f"    T04 backed out from EGT {egt:.0f} K: {T:.0f} K (design-point Tt5 {d.outputs('cycle')['Tt5_K']:.0f} K)")
            rep = d.analyze(["maps"], verbose=None)
            if rep.failed:
                raise RuntimeError(f"maps failed: {rep.failed}")
            return d
        rows += cases.validate_paper(paper_factory, verbose=print)
    print(cases.format_results(rows))
    n_out = sum(1 for r in rows if r["error"] is not None and abs(r["error"]) > r["tolerance"])
    print(f"{len(rows)} comparisons, {n_out} outside tolerance")
    if args.write:
        Path(args.write).write_text(json.dumps(rows, indent=1), encoding="utf-8")


def cmd_export(args):
    d = _design(args)
    from .compare import require_frozen
    require_frozen(d, getattr(args, "unfrozen_ok", False), f"{args.kind} export")
    from . import handoff
    if args.kind == "cfd":
        res = handoff.export_cfd(d, args.component)
    else:
        res = handoff.export_fea(d, args.component)
    print(f"exported {args.kind} package for {args.component} -> {res['dir']}")
    for k, v in res["files"].items():
        print(f"  {k}: {v}")
    print("  fill ingest_template.json with the solver results and run `jet ingest <file> --run`")


def cmd_correlate(args):
    d = _design(args)
    from . import correlation
    pts = correlation.read_test_csv(args.csv)
    if args.calibrate:
        res = correlation.calibrate(d, pts, tune=args.tune.split(",") if args.tune else None, verbose=print if args.verbose else None)
        print(correlation.format_comparison(res["before"], "as-designed vs as-tested (before calibration)"))
        print(correlation.format_comparison(res["after"], "after calibration"))
        print("  tuned coefficients:")
        for k, m in res["moves"].items():
            print(f"    {k:<20} {m['before']:.4f} -> {m['after']:.4f}  ({m['change']:+.4f}; bounds {m['bounds']})")
        print("  held: " + ", ".join(res["held"]))
        if args.apply:
            d.set(res["tuned"])
            d.run()
            print("  applied to the design (versioned); re-run analyses to propagate")
        out = Path(d.dir) / "analysis" / "correlation.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        print(f"  written {out}")
    else:
        res = correlation.compare(d, pts)
        print(correlation.format_comparison(res, "as-designed vs as-tested"))


def cmd_readiness(args):
    d = _design(args)
    from .report import readiness
    text = readiness(d)
    out = Path(d.dir) / "test_readiness.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n(written to {out})")


def cmd_freeze(args):
    d = _design(args)
    from . import compare as cmp
    if args.verify:
        vs = cmp.frozen_versions(d)
        if not vs:
            print("no frozen versions"); return
        for v in vs:
            r = cmp.verify_frozen(d, v)
            print(f"  v{v:04d}  {'OK   ' if r['ok'] else 'BAD  '} file-hash {r.get('file_hash_ok')}  content-hash {r.get('content_hash_ok')}  by {r.get('by')}  at {r.get('at')}  {r.get('note') or ''}")
        return
    if args.status or not args.by:
        st = cmp.freeze_status(d)
        print(f"design '{d.doc['name']}' v{d.store.version}: {'FROZEN' if st['frozen'] else 'not frozen'} -- {st['reason']}")
        if st.get("record"):
            rec = st["record"]
            print(f"  open risks at freeze: {rec['n_fail']} fail, {rec['n_warn']} warn; analyses present: {', '.join(rec.get('analyses_present') or []) or 'none'}")
        if not args.status and not args.by:
            print("  (to freeze: jet freeze --by <name> [--note ...])")
        return
    rec = cmp.freeze(d, args.by, args.note or "")
    print(f"frozen '{d.doc['name']}' as v{rec['version']:04d} by {rec['by']} ({rec['at']})  content {rec['content_hash']}")
    print(f"  open risks recorded: {rec['n_fail']} fail, {rec['n_warn']} warn")
    for r in rec["open_risks"]:
        print(f"    {r['verdict']:<4} {r['id']:<8} {r['name']}  [{r.get('tier') or '-'}]")
    print(f"  snapshot: frozen/v{rec['version']:04d}.json (+ .sha256)")


def cmd_compare(args):
    from . import compare as cmp
    doc_a, name_a = cmp.load_spec(args.a)
    doc_b, name_b = cmp.load_spec(args.b)
    res = cmp.compare(doc_a, doc_b, name_a, name_b)
    text = cmp.render(res)
    out = Path(args.out) if args.out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        png = cmp.plot_compare(doc_a, doc_b, name_a, name_b, out.with_suffix(".png"))
        if png:
            text += "\n![map overlay](" + Path(png).name + ")\n"
        out.write_text(text, encoding="utf-8")
        print(text)
        print(f"(written to {out}{' and ' + png if png else ''})")
    else:
        print(text)


def cmd_fe(args):
    d = _design(args)
    if args.what in ("impeller", "all"):
        from .fea import disc
        t0 = time.perf_counter()
        res = disc.run_impeller_case(d, cell_mm=args.cell)
        print(f"impeller hub: solver {res['solver'].get('mode')}  run ok: {res['run']['ok']}  ({time.perf_counter()-t0:.1f} s)  mesh {res['mesh']['n_elements']} CAX4")
        if not res["run"]["ok"]:
            sys.exit(f"CalculiX run failed, see {res['run']['log']}")
        print(f"  L1 reference: sigma_peak {res['reference_L1']['sigma_peak_Pa']/1e6:.0f} MPa (k_peak disc factor), sigma_avg {res['reference_L1']['sigma_avg_Pa']/1e6:.0f} MPa")
        for name, st in res["steps"].items():
            print(f"  {name:<22} vM max {st['vm_max_Pa']/1e6:7.1f} MPa at corner (singular)  | >= 1 mm from corners: vM {st['vm_max_away_Pa']/1e6:7.1f} MPa "
                  f"at (r {st['peak_away_r_m']*1e3:.1f}, x {st['peak_away_x_m']*1e3:.1f} mm)  hoop mean {st['hoop_mean_Pa']/1e6:7.1f}")
        if args.ingest and res.get("ingest_file"):
            for e in json.loads(Path(res["ingest_file"]).read_text(encoding="utf-8")):
                r = d.ingest(e["stage"], e["fields"], tier=e.get("tier", "L3"), source=e.get("source", "impeller FE"))
                print(f"  ingested into {e['stage']}: {', '.join(e['fields'])} -> stale: {', '.join(r['stale']) or 'nothing'}")
    if args.what in ("disc", "all"):
        from .fea import disc
        t0 = time.perf_counter()
        res = disc.run_disc_case(d, cell_mm=args.cell, variant=args.variant)
        print(f"variant: {res['variant']}")
        print(f"solver: {res['solver']}  run ok: {res['run']['ok']}  ({time.perf_counter()-t0:.1f} s)  mesh {res['mesh']['n_elements']} CAX4 elements")
        if not res["run"]["ok"]:
            sys.exit(f"CalculiX run failed, see {res['run']['log']}")
        ref = res["reference_L1"]
        print(f"  L1 reference: sigma_peak {ref['sigma_peak_Pa']/1e6:.0f} MPa, sigma_avg {ref['sigma_avg_Pa']/1e6:.0f} MPa")
        for name, st in res["steps"].items():
            print(f"  {name:<26} vM max {st['vm_max_Pa']/1e6:7.1f} MPa at corner (r {st['peak_r_m']*1e3:.1f}, x {st['peak_x_m']*1e3:.1f} mm; singular)  "
                  f"| >= 1 mm from corners: vM {st['vm_max_away_Pa']/1e6:7.1f} MPa at (r {st['peak_away_r_m']*1e3:.1f}, x {st['peak_away_x_m']*1e3:.1f})  "
                  f"hoop max {st['hoop_max_away_Pa']/1e6:7.1f}  hoop mean {st['hoop_mean_Pa']/1e6:7.1f}")
        th = res["loads"]["thermal"]
        print(f"  start thermal state at dT_max: rim {th['T_rim_K']:.0f} K, bore {th['T_bore_K']:.0f} K (dT {th['dT_max_K']:.0f} K at t {th['t_s']:.1f} s)")
        print(f"  ingest file: {res.get('ingest_file')}")
        if args.ingest and res.get("ingest_file"):
            payload = json.loads(Path(res["ingest_file"]).read_text(encoding="utf-8"))
            for e in payload:
                r = d.ingest(e["stage"], e["fields"], tier=e.get("tier", "L3"), source=e.get("source", "disc FE"))
                print(f"  ingested into {e['stage']}: {', '.join(e['fields'])} -> stale: {', '.join(r['stale']) or 'nothing'}")
            t0 = time.perf_counter()
            d.run()
            rep = d.analyze(["life"], verbose=None)
            print(f"  re-ran core + life in {time.perf_counter()-t0:.1f} s")
            print(d.rules_text(only_problems=True))
    if args.what not in ("disc", "impeller", "all"):
        sys.exit("unknown FE case")


def cmd_rig(args):
    d = _design(args)
    from . import rig
    if not d.outputs("maps"):
        sys.exit("the rig definition needs the compressor map: run `jet analyze maps` first")
    res = rig.write(d)
    print(f"cold-flow compressor rig written -> {res['dir']} ({', '.join(res['files'])}; {res['n_lines']} speed lines in the run matrix)")
    print((Path(res["dir"]) / "compressor_rig.md").read_text(encoding="utf-8"))


def cmd_l3(args):
    """Roadmap 5: one command from design state to ingested solver results and the delta report."""
    d = _design(args)
    from .fea import disc
    from . import compare as cmp
    v_before = d.store.version
    t0 = time.perf_counter()
    ingested = []
    for what, fn in (("impeller", disc.run_impeller_case), ("disc", disc.run_disc_case)):
        if args.only and what not in args.only.split(","):
            continue
        res = fn(d, cell_mm=args.cell)
        print(f"  {what:<9} FE: {'ok' if res['run']['ok'] else 'FAILED'}  mesh {res['mesh']['n_elements']} CAX4  "
              + (", ".join(f"{k} vM {v['vm_max_away_Pa']/1e6:.0f} MPa" for k, v in res.get("steps", {}).items())))
        if not res["run"]["ok"]:
            sys.exit(f"CalculiX failed, see {res['run']['log']}")
        for e in json.loads(Path(res["ingest_file"]).read_text(encoding="utf-8")):
            d.ingest(e["stage"], e["fields"], tier=e.get("tier", "L3"), source=e.get("source", f"{what} FE"))
            ingested += [f"{e['stage']}.{k}" for k in e["fields"]]
    print(f"  ingested: {', '.join(ingested)}")
    d.run()
    rep = d.analyze(["life"], verbose=None)
    if rep.failed:
        print(f"  life stage failed: {rep.failed}")
    v_after = d.store.version
    print(f"  L3 loop done in {time.perf_counter()-t0:.1f} s: v{v_before:04d} -> v{v_after:04d}")
    doc_a, na = cmp.load_spec(f"{d.dir}@v{v_before}")
    doc_b, nb = cmp.load_spec(str(d.dir))
    res = cmp.compare(doc_a, doc_b, f"before L3 (v{v_before:04d})", f"after L3 (v{v_after:04d})")
    changed = [r for r in res["rules"] if r["changed"] and r["a"] and r["b"]]
    print("  what moved when L3 replaced L1:")
    for r in changed:
        print(f"    {r['id']:<8} {r['name'][:52]:<52} {r['a']['value']:.4g} ({r['a']['verdict']}) -> {r['b']['value']:.4g} ({r['b']['verdict']})")
    out = Path(d.dir) / "analysis" / "l3_delta.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(cmp.render(res), encoding="utf-8")
    print(f"  delta report: {out}")


def cmd_dashboard(args):
    d = _design(args)
    from . import dashboard
    out = dashboard.write(d)
    print(f"dashboard written -> {out} ({Path(out).stat().st_size/1e6:.1f} MB, self-contained)")


def cmd_ecu(args):
    d = _design(args)
    from . import ecu
    res = ecu.export(d)
    print(f"ECU tables written -> {res['dir']} ({', '.join(res['files'])}; {res['rows']} schedule rows)")
    print((Path(res["dir"]) / "logic.md").read_text(encoding="utf-8")[:1500])


def cmd_drawings(args):
    d = _design(args)
    from . import drawings
    res = drawings.write(d)
    print(f"drawings written -> {res['dir']}: {', '.join(sorted(res['files']))}")
    for name, rows in res["tables"].items():
        print(f"  {name}: " + "; ".join(f"{r['feature']} {r['fit']}" for r in rows))


def cmd_cam(args):
    d = _design(args)
    from .compare import require_frozen
    require_frozen(d, getattr(args, "unfrozen_ok", False), "CAM package")
    from . import cam
    t0 = time.perf_counter()
    res = cam.write(d, try_fillet=not args.no_fillet, verbose=print if args.verbose else None)
    print(f"CAM package written -> {res['dir']} ({time.perf_counter()-t0:.1f} s): {', '.join(sorted(res['files']))}")
    print(f"  fillet r {res['fillet']['radius_mm']} mm: {'applied' if res['fillet']['applied'] else 'NOT applied'} -- {res['fillet']['note']}")


def cmd_cfd(args):
    d = _design(args)
    from .cfd import impeller as cfd_imp
    t0 = time.perf_counter()
    case = cfd_imp.run_case(d, iters=args.iters, threads=args.threads, size_mm=args.size, size_blade_mm=args.size_blade,
                            verbose=print, solve=not args.mesh_only, mesher=args.mesher, euler=args.euler)
    m = case["mesh"]
    print(f"mesher {case['domain'].get('mesher')}: {m['n_tets']} cells / {m['n_nodes']} nodes, markers {m['markers']}  ({time.perf_counter()-t0:.0f} s)")
    if args.mesh_only:
        print(f"mesh-only: config written to {case['config']} (outlet p {case['p_out_Pa']:.0f} Pa)")
        return
    run = case.get("run", {})
    print(f"SU2: {'ok' if run.get('ok') else 'FAILED'} ({run.get('exe')}), log {run.get('log')}")
    r = case.get("result") or {}
    if r.get("ok"):
        print(f"  inlet W {r['W_in']:.4f} kg/s (target {case['target_mass_flow_kg_s']:.4f} per passage), PR_tt {r['PR_tt']:.3f}, T ratio {r['T_ratio']:.4f}, eta_tt {r['eta_tt']:.3f}, rms rho {r['rms_rho_last']}")
        print(f"  L1 reference: eta_impeller_assumed {case['reference_L1']['eta_impeller_assumed']}, PR_impeller_tt {case['reference_L1']['PR_impeller_tt']}")
        if args.ingest and case.get("ingest_file"):
            for e in json.loads(Path(case["ingest_file"]).read_text(encoding="utf-8")):
                rr = d.ingest(e["stage"], e["fields"], tier=e.get("tier", "L3"), source=e.get("source", "impeller CFD"))
                print(f"  ingested into {e['stage']}: {', '.join(e['fields'])} -> stale: {', '.join(rr['stale']) or 'nothing'}")
            d.run()
    else:
        print(f"  post-processing: {r.get('error', 'no result')}")


def cmd_plot(args):
    d = _design(args)
    from . import plots
    what = args.what
    if what == "map":
        w = plots.plot_compressor_map(d, formats=("png", "svg", "html"))
    elif what == "turbine":
        w = plots.plot_turbine_map(d)
    else:
        w = plots.plot_all(d)
    print(json.dumps(w, indent=2))


def cmd_report(args):
    d = _design(args)
    from .report import render
    text = render(d)
    out = Path(d.dir) / "report.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n(written to {out})")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("-d", "--dir", default=None, help="design directory (default: . or $JET_DESIGN)")

    p = sub.add_parser("new", help="create a design and run the chain")
    p.add_argument("dir")
    p.add_argument("--name")
    p.add_argument("--thrust", type=float)
    p.add_argument("--alt", type=float)
    p.add_argument("--mach", type=float)
    p.add_argument("--set", action="append", metavar="stage.key=value")
    p.add_argument("--no-run", action="store_true")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("run", help="run stale stages"); common(p)
    p.add_argument("--force", action="store_true"); p.add_argument("--upto"); p.add_argument("--only")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("set", help="change inputs; shows what it invalidates"); common(p)
    p.add_argument("assign", nargs="+", metavar="stage.key=value"); p.add_argument("--run", action="store_true")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("show", help="show outputs of a stage"); common(p)
    p.add_argument("stage", nargs="?"); p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("inputs", help="list inputs with documentation"); common(p)
    p.add_argument("stage", nargs="?"); p.set_defaults(fn=cmd_inputs)

    p = sub.add_parser("rules", help="design-rule verdicts"); common(p)
    p.add_argument("--all", action="store_true"); p.set_defaults(fn=cmd_rules)

    p = sub.add_parser("stale", help="which stages would re-run"); common(p); p.set_defaults(fn=cmd_stale)

    p = sub.add_parser("diff", help="diff two versions (default: previous vs current)"); common(p)
    p.add_argument("v1", nargs="?", type=int); p.add_argument("v2", nargs="?", type=int); p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("history", help="version log"); common(p); p.set_defaults(fn=cmd_history)

    p = sub.add_parser("checkout", help="restore a version"); common(p)
    p.add_argument("version", type=int); p.set_defaults(fn=cmd_checkout)

    p = sub.add_parser("converge", help="iterate cycle efficiencies to component estimates"); common(p)
    p.add_argument("--tol", type=float, default=0.005); p.set_defaults(fn=cmd_converge)

    p = sub.add_parser("library", help="browse the component / material library")
    p.add_argument("kind", choices=["bearings", "screws", "retaining_rings", "locknuts", "o_rings", "igniters", "sensors",
                                    "seals", "materials"])
    p.add_argument("--bore", type=float); p.set_defaults(fn=cmd_library)

    p = sub.add_parser("cad", help="build the CAD (only parts whose geometry changed); refuses on an unfrozen design"); common(p)
    p.add_argument("--parts"); p.add_argument("--force", action="store_true"); p.add_argument("--no-assembly", action="store_true")
    p.add_argument("--unfrozen-ok", action="store_true", help="override the freeze gate")
    p.set_defaults(fn=cmd_cad)

    p = sub.add_parser("report", help="write a markdown design report"); common(p); p.set_defaults(fn=cmd_report)

    p = sub.add_parser("plot", help="layered compressor map (surge band, choke, islands, running lines, transients) and turbine map"); common(p)
    p.add_argument("what", nargs="?", default="map", choices=["map", "turbine", "all"]); p.set_defaults(fn=cmd_plot)

    p = sub.add_parser("analyze", help="run analysis stages (maps, offdesign, envelope, transient, assess, life, ...)"); common(p)
    p.add_argument("names", nargs="?", default="all", help="comma-separated stage names or 'all'")
    p.add_argument("--force", action="store_true"); p.add_argument("--serial", action="store_true", help="one stage at a time")
    p.add_argument("--workers", type=int, default=4); p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("status", help="fidelity tier, staleness and overrides per stage"); common(p); p.set_defaults(fn=cmd_status)

    p = sub.add_parser("ingest", help="ingest external (CFD/FEA/test) results as higher-tier overrides"); common(p)
    p.add_argument("file", help="JSON: {stage, fields:{name:value}, tier, source} or a list of such")
    p.add_argument("--run", action="store_true"); p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("export", help="L3 hand-off package (geometry + BCs + material card) for CFD / FEA"); common(p)
    p.add_argument("kind", choices=["cfd", "fea"]); p.add_argument("component", help="compressor|turbine (cfd), impeller|turbine (fea)")
    p.add_argument("--unfrozen-ok", action="store_true", help="override the freeze gate")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("fe", help="run an in-suite L3 finite-element case (CalculiX): disc"); common(p)
    p.add_argument("what", choices=["disc", "impeller", "all"]); p.add_argument("--cell", type=float, default=0.5, help="mesh cell size [mm]")
    p.add_argument("--ingest", action="store_true", help="ingest the result as L3 overrides and re-run life (as-designed variant only)")
    p.add_argument("--variant", default="as-designed", choices=["as-designed", "boreless"], help="what-if geometry (no ingest)")
    p.set_defaults(fn=cmd_fe)

    p = sub.add_parser("rig", help="define the cold-flow compressor test article, drive, instrumentation and run matrix"); common(p)
    p.add_argument("what", nargs="?", default="compressor", choices=["compressor"]); p.set_defaults(fn=cmd_rig)

    p = sub.add_parser("l3", help="run every in-suite L3 solve (impeller + disc FE), ingest, re-run, and report what moved"); common(p)
    p.add_argument("--only", help="comma-separated subset: impeller,disc"); p.add_argument("--cell", type=float, default=0.5)
    p.set_defaults(fn=cmd_l3)

    p = sub.add_parser("dashboard", help="single self-contained HTML: headline, rules with bands, stage status, every plot"); common(p)
    p.set_defaults(fn=cmd_dashboard)

    p = sub.add_parser("ecu", help="export the controller: schedules.csv, limits.json, logic.md, ecu_tables.json"); common(p)
    p.set_defaults(fn=cmd_ecu)

    p = sub.add_parser("drawings", help="2D drawings with tolerances (shaft, housings, casing) -> handoff/drawings/"); common(p)
    p.set_defaults(fn=cmd_drawings)

    p = sub.add_parser("cam", help="CAM-ready impeller package (surface grids, STEP, fillet spec / attempt); needs a frozen design"); common(p)
    p.add_argument("what", nargs="?", default="impeller", choices=["impeller"]); p.add_argument("--no-fillet", action="store_true")
    p.add_argument("--unfrozen-ok", action="store_true"); p.add_argument("--verbose", action="store_true"); p.set_defaults(fn=cmd_cam)

    p = sub.add_parser("cfd", help="impeller passage CFD (SU2 RANS, rotating frame) from the design state; --mesh-only to build the case without solving"); common(p)
    p.add_argument("what", nargs="?", default="impeller", choices=["impeller"]); p.add_argument("--mesh-only", action="store_true")
    p.add_argument("--iters", type=int, default=1500); p.add_argument("--threads", type=int, default=4)
    p.add_argument("--size", type=float, default=1.5, help="far-field cell size [mm]"); p.add_argument("--size-blade", type=float, default=0.5, help="blade / shroud cell size [mm]")
    p.add_argument("--mesher", default="hmesh", choices=["hmesh", "cad"]); p.add_argument("--euler", action="store_true", help="inviscid check run")
    p.add_argument("--ingest", action="store_true"); p.set_defaults(fn=cmd_cfd)

    p = sub.add_parser("freeze", help="freeze the design (sign-off snapshot, hash-verifiable); no args = status"); common(p)
    p.add_argument("--by", help="who signs off"); p.add_argument("--note", help="what this freeze is for")
    p.add_argument("--status", action="store_true"); p.add_argument("--verify", action="store_true", help="verify every frozen snapshot")
    p.set_defaults(fn=cmd_freeze)

    p = sub.add_parser("compare", help="side-by-side of two designs / versions: dir, dir@vNNNN or dir@frozen")
    p.add_argument("a"); p.add_argument("b"); p.add_argument("--out", help="write markdown (+ map overlay png) here")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("correlate", help="compare / calibrate the model against test data (CSV)"); common(p)
    p.add_argument("csv"); p.add_argument("--calibrate", action="store_true"); p.add_argument("--tune", help="comma-separated coefficients")
    p.add_argument("--apply", action="store_true"); p.add_argument("--verbose", action="store_true"); p.set_defaults(fn=cmd_correlate)

    p = sub.add_parser("readiness", help="write the test-readiness report"); common(p); p.set_defaults(fn=cmd_readiness)

    p = sub.add_parser("validate", help="run the analysis methods against the validation database")
    p.add_argument("what", nargs="?", default="all", choices=["all", "compressor", "turbine", "rigs", "fleet", "paper"])
    p.add_argument("--write", help="write the comparison rows to a JSON file"); p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("study", help="design-space studies: sweep / doe / optimize / uq / sensitivity"); common(p)
    p.add_argument("action", choices=["sweep", "doe", "optimize", "uq", "sensitivity", "list", "show"])
    p.add_argument("name", nargs="?"); p.add_argument("--spec", help="JSON string or file with the study specification")
    p.set_defaults(fn=cmd_study)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
