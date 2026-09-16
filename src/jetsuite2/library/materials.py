"""Engineering materials used by the sizing, stress and CAD stages.

Each material carries density, modulus, a yield-strength-vs-temperature table
(0.2 % proof, *typical* handbook values unless noted) and a maximum service
temperature.  ``yield_at(T)`` interpolates the table; the stress rules apply
their own knock-down (``min_basis``) to move from typical to a minimum basis.

Sources: MMPDS / MIL-HDBK-5 typical curves, ASM Handbook vol. 2, Special
Metals data sheets (IN718 / IN625), Howmet/PCC cast-alloy sheets (IN-713LC,
MAR-M247).  Conceptual-design fidelity; verify before hardware.
"""
from __future__ import annotations

import numpy as np

MATERIALS: dict[str, dict] = {
    # ------------------------------------------------------------- aluminium
    "Al2618-T61": dict(
        family="aluminium", rho=2760.0, E=74.0e9, nu=0.33, alpha=22.0e-6, k=146.0,
        yield_table=[(293, 372), (373, 350), (423, 320), (473, 255), (523, 165)],
        uts_table=[(293, 441), (423, 385), (473, 300)],
        T_max=473.0, min_basis=0.90, machinability="good",
        note="Forged impeller alloy (RR58). Typical values, MMPDS.",
        cad_color=(0.75, 0.78, 0.82)),
    "Al7075-T6": dict(
        family="aluminium", rho=2810.0, E=71.7e9, nu=0.33, alpha=23.6e-6, k=130.0,
        yield_table=[(293, 503), (373, 450), (423, 330), (473, 150)],
        uts_table=[(293, 572), (423, 380)],
        T_max=393.0, min_basis=0.92, machinability="good",
        note="High-strength wrought alloy; loses strength fast above 120 C.",
        cad_color=(0.72, 0.75, 0.80)),
    "Al6061-T6": dict(
        family="aluminium", rho=2700.0, E=68.9e9, nu=0.33, alpha=23.6e-6, k=167.0,
        yield_table=[(293, 276), (373, 262), (423, 214), (473, 103)],
        uts_table=[(293, 310), (423, 235)],
        T_max=393.0, min_basis=0.92, machinability="excellent",
        note="General-purpose; casings, housings, inlet.",
        cad_color=(0.80, 0.82, 0.85)),
    # -------------------------------------------------------------- titanium
    "Ti-6Al-4V": dict(
        family="titanium", rho=4430.0, E=113.8e9, nu=0.342, alpha=9.2e-6, k=6.7,
        yield_table=[(293, 880), (423, 700), (523, 620), (673, 560), (773, 480)],
        uts_table=[(293, 950), (523, 681), (673, 620)],
        T_max=673.0, min_basis=0.90, machinability="fair",
        note="Annealed. 523 K row taken as minimum basis (AMS 4928 ratio) as in boomsonic_v0.",
        cad_color=(0.55, 0.58, 0.62)),
    # ------------------------------------------------------------------ steel
    "AISI4340": dict(
        family="steel", rho=7850.0, E=205.0e9, nu=0.29, alpha=12.3e-6, k=44.5,
        yield_table=[(293, 1100), (473, 1000), (573, 900), (673, 750)],
        uts_table=[(293, 1250), (573, 1000)],
        T_max=573.0, min_basis=0.90, machinability="fair",
        note="Q&T shaft steel (~40 HRC).",
        cad_color=(0.45, 0.45, 0.48)),
    "17-4PH-H900": dict(
        family="steel", rho=7800.0, E=196.5e9, nu=0.27, alpha=10.8e-6, k=17.9,
        yield_table=[(293, 1170), (473, 1070), (573, 1000), (673, 900)],
        uts_table=[(293, 1310), (573, 1130)],
        T_max=588.0, min_basis=0.90, machinability="fair",
        note="Precipitation-hardened stainless; shafts, high-strength fittings.",
        cad_color=(0.50, 0.50, 0.53)),
    "AISI321": dict(
        family="steel", rho=7900.0, E=193.0e9, nu=0.30, alpha=16.6e-6, k=16.1,
        yield_table=[(293, 205), (673, 140), (873, 115), (1073, 90)],
        uts_table=[(293, 515), (873, 350)],
        T_max=1073.0, min_basis=0.90, machinability="good",
        note="Stabilised austenitic stainless: hot casings, jet pipe, sheet parts.",
        cad_color=(0.62, 0.62, 0.64)),
    "AISI316": dict(
        family="steel", rho=8000.0, E=193.0e9, nu=0.30, alpha=16.0e-6, k=16.3,
        yield_table=[(293, 205), (673, 135), (873, 105)],
        uts_table=[(293, 515)],
        T_max=1073.0, min_basis=0.90, machinability="good",
        note="Misc. fittings, brackets, screws.",
        cad_color=(0.65, 0.65, 0.66)),
    # ------------------------------------------------------- nickel superalloy
    "IN718": dict(
        family="nickel", rho=8190.0, E=200.0e9, nu=0.29, alpha=13.0e-6, k=11.4,
        yield_table=[(293, 1030), (673, 980), (873, 930), (923, 880), (973, 760)],
        uts_table=[(293, 1240), (923, 1000)],
        T_max=923.0, min_basis=0.90, machinability="poor",
        note="Wrought turbine disc / bolt alloy. Creep-limited above ~650 C.",
        cad_color=(0.58, 0.52, 0.42)),
    "IN625": dict(
        family="nickel", rho=8440.0, E=207.0e9, nu=0.31, alpha=12.8e-6, k=9.8,
        yield_table=[(293, 450), (873, 320), (1073, 280), (1173, 200)],
        uts_table=[(293, 870), (1073, 550)],
        T_max=1253.0, min_basis=0.90, machinability="poor",
        note="Sheet for combustor liners, vaporisers, NGV rings (annealed).",
        cad_color=(0.70, 0.60, 0.45)),
    "IN713LC": dict(
        family="nickel", rho=8000.0, E=197.0e9, nu=0.30, alpha=11.0e-6, k=10.9,
        yield_table=[(293, 750), (873, 740), (1073, 700), (1173, 500), (1223, 350)],
        uts_table=[(293, 900), (1073, 880), (1223, 500)],
        T_max=1223.0, min_basis=0.85, machinability="cast-only",
        # creep allowable: stress for 1 % creep / 1000 h ~ 350 MPa at 1050 K (conceptual, boomsonic A3.2)
        creep_table=[(973, 560), (1023, 450), (1073, 350), (1123, 250), (1173, 170)],
        note="Investment-cast integral turbine wheel alloy (micro-turbojet standard).",
        cad_color=(0.55, 0.45, 0.35)),
    "MAR-M247": dict(
        family="nickel", rho=8540.0, E=214.0e9, nu=0.30, alpha=11.5e-6, k=10.0,
        yield_table=[(293, 830), (873, 820), (1073, 780), (1173, 600), (1223, 450)],
        uts_table=[(293, 970), (1073, 950)],
        T_max=1273.0, min_basis=0.85, machinability="cast-only",
        creep_table=[(973, 700), (1023, 560), (1073, 430), (1123, 320), (1173, 230)],
        note="Higher-temperature cast wheel alloy; costlier than IN-713LC.",
        cad_color=(0.50, 0.42, 0.33)),
}


def get(name: str) -> dict:
    if name not in MATERIALS:
        raise KeyError(f"unknown material '{name}'. Known: {', '.join(sorted(MATERIALS))}")
    return MATERIALS[name]


def _interp(table, T):
    t = np.array([r[0] for r in table], dtype=float)
    v = np.array([r[1] for r in table], dtype=float)
    return float(np.interp(T, t, v))  # clamps at both ends


def yield_at(name: str, T: float, minimum_basis: bool = True) -> float:
    """0.2 % proof stress [Pa] at temperature T [K]."""
    m = get(name)
    s = _interp(m["yield_table"], T) * 1e6
    return s * (m["min_basis"] if minimum_basis else 1.0)


def uts_at(name: str, T: float, minimum_basis: bool = True) -> float:
    m = get(name)
    s = _interp(m["uts_table"], T) * 1e6
    return s * (m["min_basis"] if minimum_basis else 1.0)


def creep_allowable_at(name: str, T: float) -> float | None:
    """Creep-rupture-based allowable [Pa] if the material has a creep table, else None."""
    m = get(name)
    if "creep_table" not in m or T < m["creep_table"][0][0]:
        return None   # below the table creep is not the limiting mechanism
    return _interp(m["creep_table"], T) * 1e6


def allowable_at(name: str, T: float) -> float:
    """Design allowable: min(yield, creep allowable) at temperature."""
    y = yield_at(name, T)
    c = creep_allowable_at(name, T)
    return min(y, c) if c is not None else y


def list_materials(family: str | None = None) -> list[str]:
    return sorted(k for k, v in MATERIALS.items() if family is None or v["family"] == family)
