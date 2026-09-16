"""CAD build driver: per-part cache keyed on the geometry-sheet group hashes,
STEP export per part and as a coloured assembly, and assembly-level checks.

    <design>/cad/parts/<name>.step      one file per part (always current)
    <design>/cad/cache/<builder>.<hash>.brep   cached solids (fast reload)
    <design>/cad/manifest.json          what was built from which hash, volumes, masses
    <design>/cad/engine_assembly.step   the assembly
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import cadquery as cq

from ..library import materials
from ..state.store import canonical_hash
from . import cadlib
from .parts import PART_GROUPS, COLORS

DENSITY_EXTRA = {"bearing-steel": 7800.0, "FKM": 1800.0}


def _density(mat: str) -> float:
    if mat in DENSITY_EXTRA:
        return DENSITY_EXTRA[mat]
    return materials.get(mat)["rho"]


def build(design, parts: list[str] | None = None, force: bool = False, assembly: bool = True, verbose=None) -> dict:
    geo = design.outputs("geometry")
    if not geo:
        raise RuntimeError("geometry stage has not run; run `jet run` first")
    sheet, hashes = geo["sheet"], geo["hashes"]
    cad_dir = Path(design.dir) / "cad"
    (cad_dir / "parts").mkdir(parents=True, exist_ok=True)
    (cad_dir / "cache").mkdir(parents=True, exist_ok=True)
    man_path = cad_dir / "manifest.json"
    manifest = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {"builders": {}, "parts": {}}
    result = {"dir": str(cad_dir), "parts": {}, "notes": [], "checks": []}
    shapes: dict[str, tuple] = {}
    any_built = False
    for bname, (fn, groups) in PART_GROUPS.items():
        if parts and bname not in parts:
            # still load from cache for the assembly
            pass
        key = canonical_hash({g: hashes.get(g) for g in groups})
        entry = manifest["builders"].get(bname)
        cached_ok = (entry is not None and entry.get("key") == key and not force
                     and all((cad_dir / "cache" / f).exists() for f in entry.get("files", {}).values()))
        if cached_ok and (not parts or bname not in parts):
            for pname, f in entry["files"].items():
                shp = cadlib.import_brep(cad_dir / "cache" / f)
                mat = entry["materials"][pname]
                shapes[pname] = (shp, mat)
                result["parts"][pname] = dict(built=False, elapsed_s=0.0, volume_cm3=cadlib.volume(shp) / 1e3,
                                              mass_kg=cadlib.volume(shp) * 1e-9 * _density(mat), valid=entry["valid"].get(pname, True))
            continue
        if parts and bname not in parts and not cached_ok:
            continue
        if verbose:
            verbose(f"building {bname} ...")
        t0 = time.perf_counter()
        notes: list[str] = []
        try:
            out = fn(sheet, notes)
        except Exception as e:  # noqa: BLE001
            result["notes"].append(f"{bname}: FAILED {type(e).__name__}: {e}")
            manifest["builders"].pop(bname, None)
            continue
        dt = time.perf_counter() - t0
        result["notes"] += [f"{bname}: {n}" for n in notes]
        files, mats, valids = {}, {}, {}
        # stale cache files of this builder
        old = manifest["builders"].get(bname, {}).get("files", {})
        for f in old.values():
            try:
                (cad_dir / "cache" / f).unlink()
            except OSError:
                pass
        for pname, (shp, mat) in out.items():
            fname = f"{pname}.{key}.brep"
            cadlib.export_brep(shp, cad_dir / "cache" / fname)
            files[pname], mats[pname] = fname, mat
            v = cadlib.volume(shp)
            ok = cadlib.valid(shp)
            valids[pname] = ok
            shapes[pname] = (shp, mat)
            result["parts"][pname] = dict(built=True, elapsed_s=dt / max(len(out), 1), volume_cm3=v / 1e3,
                                          mass_kg=v * 1e-9 * _density(mat), valid=ok)
            cq.exporters.export(cq.Workplane().add(shp), str(cad_dir / "parts" / f"{pname}.step"))
        manifest["builders"][bname] = dict(key=key, files=files, materials=mats, valid=valids, elapsed_s=dt,
                                           built_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        any_built = True
    # ---- manifest with masses
    manifest["parts"] = {p: dict(volume_cm3=i["volume_cm3"], mass_kg=i["mass_kg"], valid=i["valid"]) for p, i in result["parts"].items()}
    manifest["mass_total_kg"] = sum(i["mass_kg"] for i in result["parts"].values())
    manifest["design_version"] = design.store.version
    man_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    result["mass_total_kg"] = manifest["mass_total_kg"]
    # ---- checks: interference of critical pairs (re-run only when something was rebuilt)
    if any_built or force or "checks" not in manifest:
        result["checks"] += interference_checks(shapes)
        manifest["checks"] = result["checks"]
        man_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    else:
        result["checks"] += ["(unchanged) " + c for c in manifest.get("checks", [])]
    # ---- assembly (skipped when nothing changed and the file exists)
    step_existing = cad_dir / "engine_assembly.step"
    if assembly and shapes and not any_built and step_existing.exists() and not force:
        result["assembly"] = str(step_existing)
        result["assembly_elapsed_s"] = 0.0
        result["notes"].append("assembly unchanged (no part rebuilt)")
    elif assembly and shapes:
        t0 = time.perf_counter()
        asm = cq.Assembly(name=design.doc["name"])
        for pname, (shp, mat) in shapes.items():
            col = COLORS.get(mat, (0.6, 0.6, 0.6))
            asm.add(shp, name=pname, color=cq.Color(*col))
        step_path = cad_dir / "engine_assembly.step"
        asm.save(str(step_path))
        result["assembly"] = str(step_path)
        try:
            asm.save(str(cad_dir / "engine_assembly.glb"), exportType="GLTF")
        except Exception as e:  # noqa: BLE001
            result["notes"].append(f"GLTF export skipped: {type(e).__name__}")
        result["assembly_elapsed_s"] = time.perf_counter() - t0
    return result


PAIRS = [("impeller", "inlet_shroud"), ("impeller", "housing_front"), ("turbine_wheel", "turbine_shroud"),
         ("turbine_wheel", "ngv_ring"), ("shaft", "shaft_tunnel"), ("shaft", "housing_front"), ("shaft", "housing_rear"),
         ("liner_outer", "outer_casing"), ("liner_inner", "inner_casing"), ("impeller", "diffuser_vanes"),
         ("impeller", "diffuser_back_plate")]


def interference_checks(shapes: dict, tol_cm3: float = 0.02) -> list[str]:
    out = []
    for a, b in PAIRS:
        if a not in shapes or b not in shapes:
            continue
        sa, sb = shapes[a][0], shapes[b][0]
        try:
            bb1, bb2 = sa.BoundingBox(), sb.BoundingBox()
            if bb1.xmax < bb2.xmin or bb2.xmax < bb1.xmin:
                out.append(f"clear  {a} / {b} (no axial overlap)")
                continue
            v = cadlib.volume(sa.intersect(sb)) / 1e3
        except Exception as e:  # noqa: BLE001
            out.append(f"?      {a} / {b}: intersect failed ({type(e).__name__})")
            continue
        out.append(("clear  " if v <= tol_cm3 else "CLASH  ") + f"{a} / {b}: common volume {v:.3f} cm3")
    return out
