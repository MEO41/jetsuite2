"""Stage registry: the design sequence as a dependency graph.

Core chain (runs on every `jet run`, sub-second)::

    requirements -> cycle -> speed -> compressor -> turbine -> combustor
                 -> layout -> rotor -> mechanical -> geometry -> (cad)

Analysis stages (opt-in via `jet analyze`, cached and invalidated like any
other stage) hang off the core outputs::

    maps -> offdesign -> envelope -> transient -> testbench
    assess, combustor1d, life, rotordyn, manufacturing

Each module declares ``TIER`` (fidelity of its own method) and ``CORE``.
"""
from __future__ import annotations

import copy
import importlib

from ..state import Stage, StageGraph

CORE_MODULES = ["requirements", "cycle", "speed", "compressor", "turbine", "combustor", "layout",
                "rotor", "mechanical", "geometry", "control"]
ANALYSIS_MODULES = ["assess", "throughflow", "combustor1d", "maps", "offdesign", "envelope", "transient", "thermal", "life", "rotordyn",
                    "manufacturing", "testbench"]

DEFAULT_TIERS = {"requirements": "L0", "cycle": "L1", "speed": "L1", "compressor": "L1", "turbine": "L1",
                 "combustor": "L1", "layout": "L0", "rotor": "L2", "mechanical": "L1", "geometry": "L0", "control": "L1"}


def _load(name: str):
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as e:
        if e.name and e.name.endswith(name):
            return None
        raise


def modules() -> list:
    mods = []
    for n in CORE_MODULES + ANALYSIS_MODULES:
        m = _load(n)
        if m is not None:
            mods.append(m)
    return mods


MODULES = modules()
ORDER = [m.__name__.split(".")[-1] for m in MODULES]
CORE = [n for n in ORDER if n in CORE_MODULES]
ANALYSIS = [n for n in ORDER if n in ANALYSIS_MODULES]


def build_graph() -> StageGraph:
    stages = []
    for m in MODULES:
        name = m.__name__.split(".")[-1]
        stages.append(Stage(name=name, reads=list(m.READS), run=m.run,
                            doc=(m.__doc__ or "").strip().splitlines()[0],
                            tier=getattr(m, "TIER", DEFAULT_TIERS.get(name, "L1")),
                            core=getattr(m, "CORE", name in CORE_MODULES)))
    return StageGraph(stages)


def default_inputs() -> dict:
    """User-editable inputs with their defaults (the '_doc' entries are stripped)."""
    out = {}
    for m in MODULES:
        name = m.__name__.split(".")[-1]
        d = copy.deepcopy(getattr(m, "DEFAULTS", {}))
        d.pop("_doc", None)
        out[name] = d
    return out


def input_docs() -> dict:
    return {m.__name__.split(".")[-1]: dict(getattr(m, "DEFAULTS", {}).get("_doc", {})) for m in MODULES}
