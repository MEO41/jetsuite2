"""Stage 3 - spool speed selection.

The single design speed is bounded by three mechanical limits and one
aerodynamic limit, each computable from the cycle alone:

* inducer shroud relative Mach number (compressor inlet sizing),
* turbine blade-root stress (AN^2 with the turbine material's allowable),
* bearing DN with the smallest journal the torque allows,
* impeller tip speed against the impeller material (reported; it is set by
  the work, not the speed, so it bounds OPR rather than rpm).

``rpm: auto`` takes the lowest of the limits with their margins; a number
overrides it and the rules report the margins.  Changing a material here is
the cheapest way to see a spool-speed (and therefore size) consequence.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq, minimize_scalar

from .. import gas
from ..library import materials, components
from ..rules import check
from .common import inp, out, is_auto, journal_rule

DEFAULTS = {
    "rpm": "auto",
    "inducer_M_rel_target": 1.20,   # shroud relative Mach at design (auto mode aims here)
    "inducer_M_rel_max": 1.30,
    "mcs_factor": 1.05,             # maximum continuous speed / design speed
    "turbine_stress_margin": 1.25,  # allowable / stress at MCS
    "dn_margin": 0.85,              # fraction of the bearing DN limit used at MCS
    "_doc": {
        "rpm": "'auto' or design spool speed [rpm]",
        "inducer_M_rel_target": "inducer shroud relative Mach the auto speed aims for (fielded micro-turbojets 1.1-1.3)",
        "inducer_M_rel_max": "hard limit on inducer shroud relative Mach",
        "mcs_factor": "max continuous speed as a fraction of design speed",
        "turbine_stress_margin": "required allowable/stress ratio for the turbine blade root at MCS",
        "dn_margin": "fraction of the bearing DN rating used at MCS",
    },
}

READS = ["inputs.speed.*", "inputs.compressor.hub_tip_ratio", "inputs.compressor.material",
         "inputs.turbine.material", "inputs.turbine.hub_tip_ratio_min", "inputs.turbine.taper_factor",
         "inputs.turbine.T_metal_offset_K", "inputs.turbine.hub_tip_ratio_target",
         "inputs.mechanical.k_peak_bored", "inputs.mechanical.k_peak_boreless", "inputs.mechanical.turbine_mount",
         "inputs.mechanical.turbine_disc_bore_T_K",
         "inputs.rotor.shaft_material", "inputs.rotor.journal_d_mm", "inputs.rotor.bearing_hybrid",
         "outputs.cycle.W_kg_s", "outputs.cycle.Tt2_K", "outputs.cycle.Pt2_Pa", "outputs.cycle.W4_kg_s",
         "outputs.cycle.Tt5_K", "outputs.cycle.Pt5_Pa", "outputs.cycle.far", "outputs.cycle.T04_K",
         "outputs.cycle.P_turb_W", "outputs.cycle.dh_c_J_kg"]


def inducer_min_mrel(W: float, Tt2: float, Pt2: float, omega: float, nu: float,
                     blockage: float = 0.02) -> tuple[float, float, float, float]:
    """Minimise the inducer shroud relative Mach over the shroud radius.

    Returns (M_rel_shroud, r1s [m], C1 [m/s], M1 axial)."""
    def mrel(r1s):
        A1 = math.pi * r1s ** 2 * (1 - nu ** 2) * (1 - blockage)
        try:
            M1 = gas.mach_from_area(W, Tt2, Pt2, A1)
        except ValueError:
            return 10.0
        T1, P1, g = gas.static_from_total(Tt2, Pt2, M1)
        a1 = math.sqrt(g * gas.R_AIR * T1)
        C1 = M1 * a1
        return math.sqrt(C1 ** 2 + (omega * r1s) ** 2) / a1

    # bracket: smallest radius that passes the flow ... generous upper bound
    A_choke = W / gas.mass_flow_function(Tt2, Pt2, 1.0, 1.0)
    r_lo = math.sqrt(A_choke / (math.pi * (1 - nu ** 2) * (1 - blockage))) * 1.02
    r_hi = r_lo * 4.0
    res = minimize_scalar(mrel, bounds=(r_lo, r_hi), method="bounded", options={"xatol": 1e-6})
    r1s = float(res.x)
    A1 = math.pi * r1s ** 2 * (1 - nu ** 2) * (1 - blockage)
    M1 = gas.mach_from_area(W, Tt2, Pt2, A1)
    T1, P1, g = gas.static_from_total(Tt2, Pt2, M1)
    C1 = M1 * math.sqrt(g * gas.R_AIR * T1)
    return float(res.fun), r1s, C1, M1


def run(doc: dict) -> dict:
    s = lambda k: inp(doc, "speed", k, DEFAULTS[k])  # noqa: E731
    W, Tt2, Pt2 = out(doc, "cycle", "W_kg_s"), out(doc, "cycle", "Tt2_K"), out(doc, "cycle", "Pt2_Pa")
    W4, Tt5, Pt5, far = (out(doc, "cycle", "W4_kg_s"), out(doc, "cycle", "Tt5_K"),
                         out(doc, "cycle", "Pt5_Pa"), out(doc, "cycle", "far"))
    T04, P_turb = out(doc, "cycle", "T04_K"), out(doc, "cycle", "P_turb_W")
    dh_c = out(doc, "cycle", "dh_c_J_kg")
    nu = float(inp(doc, "compressor", "hub_tip_ratio", 0.35))
    mcs = float(s("mcs_factor"))
    M_target, M_max = float(s("inducer_M_rel_target")), float(s("inducer_M_rel_max"))

    # ---- limit 1: inducer relative Mach -> rpm
    def mrel_at(rpm):
        return inducer_min_mrel(W, Tt2, Pt2, rpm * 2 * math.pi / 60.0, nu)[0]
    rpm_inducer = brentq(lambda n: mrel_at(n) - M_target, 5000.0, 400000.0, xtol=1.0)

    # ---- limit 2: turbine blade root stress at MCS (AN^2)
    t_mat = inp(doc, "turbine", "material", "IN713LC")
    ht_min = float(inp(doc, "turbine", "hub_tip_ratio_min", 0.60))
    k_taper = float(inp(doc, "turbine", "taper_factor", 0.6))
    T_metal = T04 - float(inp(doc, "turbine", "T_metal_offset_K", 120.0))
    sig_allow_t = materials.allowable_at(t_mat, T_metal)
    rho_t = materials.get(t_mat)["rho"]
    # exit annulus area from the cycle (rotor-exit Mach ~0.45 assumption for the limit estimate;
    # the turbine stage re-checks with its real annulus)
    A5 = W4 / gas.mass_flow_function(Tt5, Pt5, 0.45, 1.0, far)
    # sigma = k rho w^2 (rt^2 - rh^2)/2 = k rho w^2 A/(2 pi)  -> w_max
    sm = float(s("turbine_stress_margin"))
    omega_t_mcs = math.sqrt(sig_allow_t / sm * 2 * math.pi / (k_taper * rho_t * A5))
    rpm_turbine = omega_t_mcs * 60 / (2 * math.pi) / mcs

    # ---- limit 2b: turbine disc bore stress (bored wheel): sigma_peak ~ k_peak * k_avg * rho * (omega r_hub)^2
    ht_t = float(inp(doc, "turbine", "hub_tip_ratio_target", 0.62))
    r_hub_est = ht_t * math.sqrt(A5 / (math.pi * (1 - ht_t ** 2)))
    t_bored = str(inp(doc, "mechanical", "turbine_mount", "stub")).lower() == "bore"
    k_peak = float(inp(doc, "mechanical", "k_peak_bored" if t_bored else "k_peak_boreless", 1.6 if t_bored else 1.3))
    T_bore = float(inp(doc, "mechanical", "turbine_disc_bore_T_K", 750.0))
    sig_allow_bore = materials.allowable_at(t_mat, T_bore)
    k_avg = 0.80   # average tangential stress / rho (omega r_hub)^2 for the default disc profile incl. blade load
    omega_disc_mcs = math.sqrt(sig_allow_bore / (1.08 * k_peak * k_avg * rho_t * r_hub_est ** 2))
    rpm_disc = omega_disc_mcs * 60 / (2 * math.pi) / mcs

    # ---- limit 3: bearing DN with the smallest torque-capable journal
    sh_mat = inp(doc, "rotor", "shaft_material", "AISI4340")
    hybrid = bool(inp(doc, "rotor", "bearing_hybrid", True))
    dn_margin = float(s("dn_margin"))
    j_in = inp(doc, "rotor", "journal_d_mm", "auto")
    # torque-based minimum journal (tau_allow = 0.577 sigma_y / SF 3) at a provisional speed
    tau_allow = 0.577 * materials.yield_at(sh_mat, 400.0) / 3.0
    def journal_for(rpm):
        omega = rpm * 2 * math.pi / 60
        T_shaft = P_turb / omega
        d = (16 * T_shaft / (math.pi * tau_allow)) ** (1 / 3)
        return max(d * 1e3, 8.0)   # mm, never below 8 mm (smallest catalogue bore)
    # turbine tip diameter estimate (hub/tip 0.62) for the stiffness rule of thumb
    D_t_est = 2 * math.sqrt(A5 / (math.pi * (1 - 0.62 ** 2)))
    if is_auto(j_in):
        d_j = journal_rule(journal_for(min(rpm_inducer, rpm_turbine)), D_t_est)
    else:
        d_j = float(j_in)
    cands = components.bearings(min_bore=d_j, hybrid=hybrid, btype="angular_contact")
    if not cands:
        cands = components.bearings(min_bore=d_j, hybrid=hybrid)
    best_rpm_dn, best_b = 0.0, None
    for b in cands:
        n_dn = dn_margin * b["dn_limit"] / b["bore"] / mcs
        if n_dn > best_rpm_dn:
            best_rpm_dn, best_b = n_dn, b
    rpm_dn = best_rpm_dn

    # ---- choose
    rpm_in = s("rpm")
    limits = {"inducer_M_rel": rpm_inducer, "turbine_AN2": rpm_turbine, "turbine_disc": rpm_disc, "bearing_DN": rpm_dn}
    binding = min(limits, key=limits.get)
    if is_auto(rpm_in):
        rpm = float(math.floor(0.97 * limits[binding] / 500.0) * 500.0)   # 3 % below the binding limit
        mode = f"auto (binding: {binding})"
    else:
        rpm = float(rpm_in)
        mode = "user"
    omega = rpm * 2 * math.pi / 60.0

    # ---- impeller tip speed vs material (work-set, reported here for orientation)
    c_mat = inp(doc, "compressor", "material", "Ti-6Al-4V")
    Tt3 = gas.T_from_h(gas.h(Tt2) + dh_c)
    sig_c = materials.yield_at(c_mat, Tt3)
    rho_c = materials.get(c_mat)["rho"]
    # disc stress ~ (3+nu)/8 rho U2^2 (solid disc) x 1.25 blade-load allowance; allow 1/1.15 SF at MCS
    U2_allow = math.sqrt(sig_c / 1.15 / (1.25 * (3 + 0.33) / 8 * rho_c)) / mcs
    mrel_final = mrel_at(rpm)

    rules = [
        check("SPD-1", "inducer shroud relative Mach at design", mrel_final, M_max, "max",
              "fielded micro-turbojet band 1.10-1.33 (boomsonic_v0 A3R.1)", warn_margin=0.03,
              note="lower rpm, larger hub/tip ratio or higher inlet Mach margin"),
        check("SPD-2", "design rpm vs turbine AN2 limit", rpm, rpm_turbine, "max",
              f"AN2 with {t_mat} allowable {sig_allow_t/1e6:.0f} MPa at {T_metal:.0f} K, margin {sm}", unit="rpm",
              warn_margin=0.02, note="lower rpm, stronger turbine material, or lower T04"),
        check("SPD-2b", "design rpm vs turbine disc bore-stress limit", rpm, rpm_disc, "max",
              f"bored {t_mat} wheel, allowable {sig_allow_bore/1e6:.0f} MPa at {T_bore:.0f} K, k_peak {k_peak}", unit="rpm",
              warn_margin=0.02, note="lower rpm, smaller hub/tip target, boreless wheel or stronger material"),
        check("SPD-3", "design rpm vs bearing DN limit", rpm, rpm_dn, "max",
              f"bearing {best_b['id'] if best_b else '-'} DN {best_b['dn_limit'] if best_b else 0:.1e} x {dn_margin}", unit="rpm",
              warn_margin=0.02, note="smaller journal (if torque allows), hybrid bearing, or lower rpm"),
        check("SPD-4", "impeller tip speed allowed by material (info: set by work, see COMP-3)", U2_allow, None, "info",
              f"{c_mat} yield at Tt3", unit="m/s"),
    ]
    return dict(
        rpm=rpm, omega_rad_s=omega, rpm_mcs=rpm * mcs, mcs_factor=mcs, mode=mode, binding_limit=binding,
        rpm_limit_inducer=rpm_inducer, rpm_limit_turbine_AN2=rpm_turbine, rpm_limit_turbine_disc=rpm_disc,
        rpm_limit_bearing_DN=rpm_dn, turbine_r_hub_est_m=r_hub_est,
        inducer_M_rel=mrel_final, journal_d_min_mm=d_j, dn_bearing_candidate=best_b["id"] if best_b else None,
        turbine_sigma_allow_Pa=sig_allow_t, turbine_T_metal_K=T_metal, turbine_A5_est_m2=A5,
        impeller_U2_allow_m_s=U2_allow, impeller_material=c_mat, turbine_material=t_mat,
        _rules=rules,
    )
