"""Stage 7 - axial layout and envelope.

Places every component along the engine axis (x = 0 at the impeller nose,
positive aft) from the component axial lengths and a few clearance rules,
and reports the outer envelope against the requirement limits.  The rotor
stage takes the bearing positions from here; the geometry stage takes all
station positions.
"""
from __future__ import annotations

import math

from ..rules import check
from .common import inp, out

DEFAULTS = {
    "inlet_length_ratio": 0.45,     # bellmouth/inlet length / r1s
    "casing_wall_mm": 1.0,
    "front_bearing_offset_ratio": 0.10,   # front bearing centre behind the impeller back face / D2
    "rear_bearing_offset_ratio": 0.22,    # rear bearing centre ahead of the turbine disc mid-plane / D_turbine
    "ngv_rotor_gap_ratio": 0.30,    # axial gap / NGV axial chord
    "nozzle_half_angle_deg": 12.0,
    "tail_cone_half_angle_deg": 18.0,
    "_doc": {
        "inlet_length_ratio": "inlet duct/bellmouth length as a fraction of the inducer tip radius",
        "casing_wall_mm": "outer casing wall thickness (envelope)",
        "front_bearing_offset_ratio": "front bearing centre distance behind the impeller back face / D2",
        "rear_bearing_offset_ratio": "rear bearing centre distance ahead of the turbine disc / D_turbine",
        "ngv_rotor_gap_ratio": "NGV-rotor axial gap / NGV axial chord",
        "nozzle_half_angle_deg": "convergent nozzle wall half-angle",
        "tail_cone_half_angle_deg": "tail cone half-angle",
    },
}

READS = ["inputs.layout.*", "outputs.requirements.max_diameter_mm", "outputs.requirements.max_length_mm",
         "outputs.compressor.r1s_m", "outputs.compressor.r2_m", "outputs.compressor.D2_m", "outputs.compressor.b2_m",
         "outputs.compressor.axial_length_m", "outputs.compressor.r4_m", "outputs.compressor.deswirl_length_m",
         "outputs.compressor.casing_outer_radius_m",
         "outputs.combustor.L_liner_m", "outputs.combustor.L_transition_m", "outputs.combustor.casing_outer_radius_m",
         "outputs.turbine.cx_ngv_m", "outputs.turbine.cx_rotor_m", "outputs.turbine.r_tip_rotor_m",
         "outputs.turbine.r_hub_rotor_m", "outputs.cycle.A8_geo_m2"]


def run(doc: dict) -> dict:
    l = lambda k: inp(doc, "layout", k, DEFAULTS[k])  # noqa: E731
    r1s, r2, D2, b2 = (out(doc, "compressor", "r1s_m"), out(doc, "compressor", "r2_m"),
                       out(doc, "compressor", "D2_m"), out(doc, "compressor", "b2_m"))
    L_imp, r4, L_desw = (out(doc, "compressor", "axial_length_m"), out(doc, "compressor", "r4_m"),
                         out(doc, "compressor", "deswirl_length_m"))
    L_liner, L_trans = out(doc, "combustor", "L_liner_m"), out(doc, "combustor", "L_transition_m")
    r_cas_comb = out(doc, "combustor", "casing_outer_radius_m")
    cx_n, cx_r = out(doc, "turbine", "cx_ngv_m"), out(doc, "turbine", "cx_rotor_m")
    r_tip_t, r_hub_t = out(doc, "turbine", "r_tip_rotor_m"), out(doc, "turbine", "r_hub_rotor_m")
    A8 = out(doc, "cycle", "A8_geo_m2")
    wall = float(l("casing_wall_mm")) * 1e-3

    x_inlet0 = -float(l("inlet_length_ratio")) * r1s
    x_imp_exit = L_imp
    rim = 0.06 * r2
    x_imp_back = L_imp + rim + 0.12 * r2          # back-face boss end (see geomlib.impeller_hub_profile)
    x_diff0 = L_imp - b2                           # diffuser channel axial band
    x_desw_end = L_imp + L_desw
    x_comb0 = x_desw_end + 0.006                   # dome plane
    x_comb_end = x_comb0 + L_liner + L_trans
    x_ngv0 = x_comb_end
    x_ngv1 = x_ngv0 + cx_n
    gap = float(l("ngv_rotor_gap_ratio")) * cx_n
    x_rot0 = x_ngv1 + gap
    x_rot1 = x_rot0 + cx_r
    x_disc_mid = x_rot0 + 0.5 * cx_r
    D_t = 2 * r_tip_t
    x_fb = x_imp_back + float(l("front_bearing_offset_ratio")) * D2
    x_rb = x_disc_mid - float(l("rear_bearing_offset_ratio")) * D_t
    span = x_rb - x_fb
    # nozzle: from the rotor exit annulus to the throat radius r8 (with a tail cone inside)
    r8 = math.sqrt(A8 / math.pi)
    half = math.radians(float(l("nozzle_half_angle_deg")))
    L_noz = max((r_tip_t - r8) / math.tan(half), 0.5 * r_tip_t) + 0.3 * r_tip_t
    x_noz0 = x_rot1 + 0.3 * cx_r
    x_noz_exit = x_noz0 + L_noz
    L_cone = r_hub_t / math.tan(math.radians(float(l("tail_cone_half_angle_deg"))))
    x_cone_end = x_noz0 + L_cone
    r_env = max(r4, r_cas_comb) + wall
    OD = 2 * r_env
    L_total = x_noz_exit - x_inlet0
    max_d = out(doc, "requirements", "max_diameter_mm")
    max_l = out(doc, "requirements", "max_length_mm")
    rules = [
        check("LAY-1", "engine outer diameter vs limit", OD * 1e3, float(max_d) if max_d else None, "max",
              "requirements.max_diameter_mm", unit="mm"),
        check("LAY-2", "engine length vs limit", L_total * 1e3, float(max_l) if max_l else None, "max",
              "requirements.max_length_mm", unit="mm"),
        check("LAY-3", "bearing span / D2 (rotordynamic sanity)", span / D2, 2.2, "max",
              "long spans lower the bending critical; boomsonic_v0 1.43", hard=False,
              note="shorten the combustor (higher U_ref / residence) or move the rear bearing aft"),
        check("LAY-4", "tail cone shorter than nozzle", L_cone, L_noz, "max", "geometry", hard=False),
    ]
    return dict(
        x_inlet0_m=x_inlet0, x_impeller_nose_m=0.0, x_impeller_exit_m=x_imp_exit, x_impeller_back_m=x_imp_back,
        x_diffuser0_m=x_diff0, x_deswirl_end_m=x_desw_end, x_combustor0_m=x_comb0, x_combustor_end_m=x_comb_end,
        x_ngv0_m=x_ngv0, x_ngv1_m=x_ngv1, x_rotor0_m=x_rot0, x_rotor1_m=x_rot1, x_disc_mid_m=x_disc_mid,
        x_front_bearing_m=x_fb, x_rear_bearing_m=x_rb, bearing_span_m=span,
        x_nozzle0_m=x_noz0, x_nozzle_exit_m=x_noz_exit, x_tail_cone_end_m=x_cone_end,
        r8_m=r8, L_nozzle_m=L_noz, L_tail_cone_m=L_cone, envelope_radius_m=r_env, OD_m=OD, length_m=L_total,
        casing_wall_m=wall, ngv_rotor_gap_m=gap,
        _rules=rules,
    )
