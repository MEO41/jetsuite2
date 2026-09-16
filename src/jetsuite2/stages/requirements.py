"""Stage 1 - requirements: thrust target, design flight condition, envelope constraints.

Outputs the ambient and ram (total) conditions the cycle starts from.
"""
from __future__ import annotations

import math

from .. import gas
from ..rules import check
from .common import isa, inp

DEFAULTS = {
    "thrust_N": 500.0,
    "altitude_m": 0.0,
    "mach": 0.0,
    "dT_isa_K": 0.0,
    "max_diameter_mm": None,      # optional envelope limits (None = unconstrained)
    "max_length_mm": None,
    "max_mass_kg": None,
    "design_life_h": 25.0,        # hot-section life target (informational, drives creep allowables)
    "_doc": {
        "thrust_N": "net thrust at the design point [N], 100-1000 supported",
        "altitude_m": "design-point pressure altitude [m]",
        "mach": "design-point flight Mach number",
        "dT_isa_K": "ambient temperature offset from ISA [K] (hot day +20)",
        "max_diameter_mm": "outer envelope limit (optional)",
        "max_length_mm": "engine length limit (optional)",
        "max_mass_kg": "dry mass limit (optional)",
        "design_life_h": "hot-section life target [h]",
    },
}

READS = ["inputs.requirements.*"]


def run(doc: dict) -> dict:
    F = float(inp(doc, "requirements", "thrust_N"))
    alt = float(inp(doc, "requirements", "altitude_m", 0.0))
    M0 = float(inp(doc, "requirements", "mach", 0.0))
    dT = float(inp(doc, "requirements", "dT_isa_K", 0.0))
    T0, P0, rho0 = isa(alt, dT)
    a0 = gas.a_sound(T0)
    V0 = M0 * a0
    # ram conditions (isentropic, variable cp)
    Tt0 = gas.T_from_h(gas.h(T0) + 0.5 * V0 * V0)
    Pt0 = P0 * math.exp((gas.phi(Tt0) - gas.phi(T0)) / gas.R_AIR)
    rules = [
        check("REQ-1", "thrust target inside supported range", F, 1000.0, "max", "brief: 100-1000 N", unit="N",
              note="above 1000 N a single centrifugal stage needs OPR/size outside the calibrated range"),
        check("REQ-2", "thrust target above minimum", F, 100.0, "min", "brief: 100-1000 N", unit="N"),
        check("REQ-3", "design Mach subsonic (pitot intake model)", M0, 1.0, "max", "intake model: normal shock + duct",
              warn_margin=0.0, hard=False, note="supersonic design points use a normal-shock recovery; check intake separately"),
    ]
    return dict(
        thrust_N=F, altitude_m=alt, mach=M0, dT_isa_K=dT,
        T0_K=T0, P0_Pa=P0, rho0=rho0, a0=a0, V0=V0, Tt0_K=Tt0, Pt0_Pa=Pt0,
        max_diameter_mm=inp(doc, "requirements", "max_diameter_mm"),
        max_length_mm=inp(doc, "requirements", "max_length_mm"),
        max_mass_kg=inp(doc, "requirements", "max_mass_kg"),
        design_life_h=float(inp(doc, "requirements", "design_life_h", 25.0)),
        _rules=rules,
    )
