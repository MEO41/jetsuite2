"""Stage registry: the design sequence as a dependency graph.

    requirements -> cycle -> speed -> compressor -> turbine -> combustor
                 -> layout -> rotor -> mechanical -> geometry -> (cad)
"""
from __future__ import annotations

import copy

from ..state import Stage, StageGraph
from . import requirements, cycle, speed, compressor, turbine, combustor, layout, rotor, mechanical, geometry

MODULES = [requirements, cycle, speed, compressor, turbine, combustor, layout, rotor, mechanical, geometry]
ORDER = [m.__name__.split(".")[-1] for m in MODULES]


def build_graph() -> StageGraph:
    stages = []
    for m in MODULES:
        name = m.__name__.split(".")[-1]
        stages.append(Stage(name=name, reads=list(m.READS), run=m.run, doc=(m.__doc__ or "").strip().splitlines()[0]))
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
