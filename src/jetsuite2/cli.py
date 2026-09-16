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

    p = sub.add_parser("cad", help="build the CAD (only parts whose geometry changed)"); common(p)
    p.add_argument("--parts"); p.add_argument("--force", action="store_true"); p.add_argument("--no-assembly", action="store_true")
    p.set_defaults(fn=cmd_cad)

    p = sub.add_parser("report", help="write a markdown design report"); common(p); p.set_defaults(fn=cmd_report)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
