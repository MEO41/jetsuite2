"""Stage 6 - annular combustor sizing (straight-through, vaporiser-fed).

Method (Lefebvre & Ballal, *Gas Turbine Combustion*, ch. 3-5; micro-turbojet
practice from the JetCat / AMT / KingTech class):

* casing annulus from a reference-velocity criterion (U_ref 15-25 m/s) with
  the outer radius inherited from the compressor diffuser and the inner
  radius from the shaft tunnel;
* liner height from the annulus split (outer/inner passages carry the liner
  cooling and dilution air);
* liner length from the larger of an L/H rule and a residence-time
  criterion; the Lefebvre theta loading parameter is reported;
* air distribution by zone (primary / secondary / dilution / cooling) to
  hole areas with a discharge coefficient and the liner pressure drop, then
  to hole counts and diameters on the inner and outer liners;
* vaporiser tubes, igniter and drain positions for the CAD.
"""
from __future__ import annotations

import math

from .. import gas
from ..library import materials, components
from ..rules import check
from .common import inp, out, is_auto

DEFAULTS = {
    "liner_material": "IN625",
    "casing_material": "AISI321",
    "U_ref_target_m_s": 25.0,
    "residence_time_ms": 2.5,       # micro-turbojet vaporiser combustors run 1.5-3 ms at mean density
    "length_to_height": 2.8,
    "liner_dp_frac": 0.035,         # liner pressure drop / P3 (of the total 5 % combustor loss)
    "hole_Cd": 0.62,
    "air_split": {"primary": 0.22, "secondary": 0.28, "dilution": 0.35, "cooling": 0.15},
    "hole_d_mm": {"primary": "auto", "secondary": "auto", "dilution": "auto", "cooling": 1.5},
    "n_vaporisers": "auto",
    "vaporiser_d_mm": "auto",
    "liner_wall_mm": 0.6,
    "casing_wall_mm": 1.0,
    "annulus_passage_frac": 0.16,   # (outer + inner passage height) / casing annulus height, each side
    "inner_radius_margin_mm": 6.0,  # liner inner radius above the shaft-tunnel outer radius
    "n_igniters": 1,
    "_doc": {
        "liner_material": "liner / dome sheet material", "casing_material": "outer casing material",
        "U_ref_target_m_s": "reference velocity on the casing annulus (15-25 m/s)",
        "residence_time_ms": "liner residence time criterion [ms] (4-7 for vaporiser combustors)",
        "length_to_height": "liner length / liner annulus height (2.5-3.5)",
        "liner_dp_frac": "liner pressure drop fraction of P3 driving the hole jets",
        "hole_Cd": "hole discharge coefficient",
        "air_split": "fractions of combustor airflow per zone (must sum to 1)",
        "hole_d_mm": "hole diameters per zone ('auto' scales with liner height)",
        "n_vaporisers": "'auto' or number of vaporiser tubes",
        "vaporiser_d_mm": "'auto' or vaporiser tube OD [mm]",
        "liner_wall_mm": "liner sheet thickness", "casing_wall_mm": "casing wall thickness",
        "annulus_passage_frac": "outer and inner passage height as a fraction of the casing annulus height",
        "inner_radius_margin_mm": "radial gap between shaft tunnel and inner casing",
        "n_igniters": "number of glow-plug igniters",
    },
}

READS = ["inputs.combustor.*", "outputs.cycle.W3_kg_s", "outputs.cycle.Tt3_K", "outputs.cycle.Pt3_Pa",
         "outputs.cycle.T04_K", "outputs.cycle.Wf_kg_s", "outputs.cycle.far",
         "outputs.compressor.casing_outer_radius_m", "outputs.compressor.r_deswirl_inner_m",
         "outputs.compressor.A_combustor_inlet_m2", "outputs.turbine.r_tip_ngv_m", "outputs.turbine.r_hub_ngv_m",
         "outputs.speed.journal_d_min_mm", "inputs.rotor.tunnel_od_mm", "inputs.rotor.tube_od_mm",
         "inputs.rotor.tunnel_clearance_mm", "inputs.rotor.tunnel_wall_mm"]


def run(doc: dict) -> dict:
    c = lambda k: inp(doc, "combustor", k, DEFAULTS[k])  # noqa: E731
    W3, Tt3, Pt3 = out(doc, "cycle", "W3_kg_s"), out(doc, "cycle", "Tt3_K"), out(doc, "cycle", "Pt3_Pa")
    T04, Wf, far = out(doc, "cycle", "T04_K"), out(doc, "cycle", "Wf_kg_s"), out(doc, "cycle", "far")
    r_cas_out = out(doc, "compressor", "casing_outer_radius_m")
    r_ngv_tip, r_ngv_hub = out(doc, "turbine", "r_tip_ngv_m"), out(doc, "turbine", "r_hub_ngv_m")
    tunnel_od = inp(doc, "rotor", "tunnel_od_mm", "auto")
    rho3 = Pt3 / (gas.R_AIR * Tt3)
    U_ref_t = float(c("U_ref_target_m_s"))
    wall_c = float(c("casing_wall_mm")) * 1e-3
    wall_l = float(c("liner_wall_mm")) * 1e-3

    # ---- casing annulus
    Ro = r_cas_out - wall_c
    if is_auto(tunnel_od):
        # estimate the shaft tunnel from the same rules the rotor stage applies (tube 2.4 x journal)
        d_j_est = float(out(doc, "speed", "journal_d_min_mm"))
        tube_in = inp(doc, "rotor", "tube_od_mm", "auto")
        tube_od_est = (2.4 * d_j_est if is_auto(tube_in) else float(tube_in)) * 1e-3
        r_tun = tube_od_est / 2 + (float(inp(doc, "rotor", "tunnel_clearance_mm", 2.0))
                                   + float(inp(doc, "rotor", "tunnel_wall_mm", 1.5))) * 1e-3
    else:
        r_tun = float(tunnel_od) * 1e-3 / 2
    Ri_min = max(r_tun + float(c("inner_radius_margin_mm")) * 1e-3, 0.25 * Ro)
    A_ref_needed = W3 / (rho3 * U_ref_t)
    Ri_from_uref = math.sqrt(max(Ro ** 2 - A_ref_needed / math.pi, 0.0))
    Ri_uref = min(max(Ri_from_uref, Ri_min), 0.6 * Ro)
    pf = float(c("annulus_passage_frac"))
    k_LH = float(c("length_to_height"))
    T_mean = 0.5 * (Tt3 + T04)
    rho_mean = Pt3 / (gas.R_AIR * T_mean)
    tau = float(c("residence_time_ms")) * 1e-3
    V_tau = W3 * tau / rho_mean

    def liner_for(Ri_):
        H_cas_ = Ro - Ri_
        r_lo_, r_li_ = Ro - pf * H_cas_, Ri_ + pf * H_cas_
        H_ = r_lo_ - r_li_
        A_ = math.pi * (r_lo_ ** 2 - r_li_ ** 2)
        return r_lo_, r_li_, H_, A_, k_LH * H_, V_tau / A_

    # Inner casing radius: start from the U_ref target; if the liner at L = k*H does not
    # give the residence time, grow the liner inward (use the space above the tunnel)
    # before lengthening it -- a longer combustor costs bearing span.
    Ri = Ri_uref
    r_lo, r_li, H_L, A_L, L_rule, L_tau = liner_for(Ri)
    if L_tau > L_rule and Ri_uref > Ri_min + 1e-6:
        f = lambda x: liner_for(x)[5] - liner_for(x)[4]  # noqa: E731
        if f(Ri_min) <= 0:
            from scipy.optimize import brentq
            Ri = brentq(f, Ri_min, Ri_uref, xtol=1e-6)
        else:
            Ri = Ri_min
        r_lo, r_li, H_L, A_L, L_rule, L_tau = liner_for(Ri)
    A_ref = math.pi * (Ro ** 2 - Ri ** 2)
    U_ref = W3 / (rho3 * A_ref)
    H_cas = Ro - Ri
    L_liner = max(L_rule, L_tau)
    V_liner = A_L * L_liner
    tau_actual = V_liner * rho_mean / W3
    theta = (Pt3 / 1e3) ** 1.75 * A_ref * (2 * H_cas) ** 0.75 * math.exp(Tt3 / 300.0) / W3  # Lefebvre loading (kPa basis)
    heat_release = Wf * gas.LHV_KEROSENE / (V_liner * Pt3 / 1e5)   # W / (m3 bar)

    # ---- hole sizing
    split = dict(c("air_split"))
    ssum = sum(split.values())
    split = {k: v / ssum for k, v in split.items()}
    dp = float(c("liner_dp_frac")) * Pt3
    Cd = float(c("hole_Cd"))
    v_jet = math.sqrt(2 * dp / rho3)
    hd_in = dict(c("hole_d_mm"))
    auto_d = {"primary": 0.16 * H_L, "secondary": 0.20 * H_L, "dilution": 0.28 * H_L, "cooling": 1.5e-3}
    holes = {}
    x_frac = {"primary": 0.22, "secondary": 0.48, "dilution": 0.75, "cooling": 0.10}
    for zone, frac in split.items():
        W_z = frac * W3
        A_eff = W_z / (Cd * rho3 * v_jet)
        d_in = hd_in.get(zone, "auto")
        d = auto_d[zone] if is_auto(d_in) else float(d_in) * 1e-3
        d = max(d, 1.0e-3)
        n_total = max(int(round(A_eff / (math.pi * d ** 2 / 4))), 4)
        # split outer/inner by circumference; round to even for symmetry
        n_out = max(int(round(n_total * r_lo / (r_lo + r_li))), 2)
        n_in = max(n_total - n_out, 2)
        if zone == "cooling":
            n_out, n_in = int(round(n_total * 0.5)), int(round(n_total * 0.5))
        holes[zone] = dict(air_frac=frac, W_kg_s=W_z, d_m=d, n_outer=n_out, n_inner=n_in,
                           x_frac=x_frac[zone], A_eff_m2=A_eff, jet_velocity_m_s=v_jet)

    # ---- vaporisers and igniters
    r_mid = 0.5 * (r_lo + r_li)
    nv_in = c("n_vaporisers")
    n_vap = int(min(max(round(2 * math.pi * r_mid / 0.030), 6), 16)) if is_auto(nv_in) else int(nv_in)
    dv_in = c("vaporiser_d_mm")
    d_vap = (min(max(0.5 * H_L, 4e-3), 10e-3)) if is_auto(dv_in) else float(dv_in) * 1e-3
    L_vap = 0.45 * L_liner
    fuel_per_vap = Wf / n_vap
    ign = components.igniter()
    n_ign = int(c("n_igniters"))

    # ---- transition to the NGV: the liner exit must meet the NGV annulus
    liner_exit_r_out, liner_exit_r_in = r_ngv_tip, r_ngv_hub
    L_transition = max(0.6 * abs(r_lo - r_ngv_tip), 0.6 * abs(r_li - r_ngv_hub), 0.015)
    T_liner_mat = materials.get(c("liner_material"))["T_max"]

    rules = [
        check("COMB-1", "reference velocity", U_ref, 25.0, "max", "Lefebvre: annular 15-25 m/s; micro practice ~20",
              unit="m/s", note="casing annulus too small: raise diffuser radius ratio or shrink the tunnel"),
        check("COMB-2", "reference velocity minimum", U_ref, 12.0, "min", "low U_ref wastes volume", hard=False, unit="m/s"),
        check("COMB-3", "liner residence time", tau_actual * 1e3, float(c("residence_time_ms")), "min",
              "vaporiser combustors 4-7 ms (JetCat/AMT class)", unit="ms", warn_margin=0.0),
        check("COMB-4", "liner length / height", L_liner / H_L, 3.6, "max", "practice 2.5-3.5 (Lefebvre)", hard=False,
              note="long liner: raise U_ref or liner height"),
        check("COMB-5", "liner metal temperature margin (T04 vs liner T_max; film-cooled liners run cooler)", T04,
              T_liner_mat + 150.0, "max", f"{c('liner_material')} T_max + 150 K film credit", unit="K", hard=False),
        check("COMB-6", "heat release rate", heat_release / 1e6, 300.0, "max",
              "large annular 20-60, micro-turbojet vaporiser combustors up to ~300 MW/(m3 bar)", unit="MW/m3bar", hard=False,
              note="raise residence time or liner volume"),
        check("COMB-7", "air split sums to 1", ssum, 1.0, "max", "input check", warn_margin=0.0, hard=False),
        check("COMB-8", "vaporiser fuel loading", fuel_per_vap * 3600, 12.0, "max", "practice 3-12 kg/h per tube", unit="kg/h",
              hard=False, note="more vaporisers"),
    ]
    return dict(
        liner_material=c("liner_material"), casing_material=c("casing_material"),
        Ro_m=Ro, Ri_m=Ri, casing_outer_radius_m=r_cas_out, casing_wall_m=wall_c, liner_wall_m=wall_l,
        A_ref_m2=A_ref, U_ref_m_s=U_ref, H_casing_m=H_cas,
        r_liner_outer_m=r_lo, r_liner_inner_m=r_li, H_liner_m=H_L, A_liner_m2=A_L,
        L_liner_m=L_liner, L_rule_m=L_rule, L_residence_m=L_tau, L_transition_m=L_transition,
        L_total_m=L_liner + L_transition, V_liner_m3=V_liner, residence_time_ms=tau_actual * 1e3,
        theta_loading=theta, heat_release_MW_m3bar=heat_release / 1e6,
        liner_dp_Pa=dp, jet_velocity_m_s=v_jet, holes=holes,
        n_vaporisers=n_vap, vaporiser_d_m=d_vap, vaporiser_length_m=L_vap, vaporiser_r_m=r_mid,
        fuel_per_vaporiser_kg_h=fuel_per_vap * 3600, igniter=ign["id"], n_igniters=n_ign,
        igniter_thread=ign["thread"], igniter_x_frac=0.18,
        liner_exit_r_out_m=liner_exit_r_out, liner_exit_r_in_m=liner_exit_r_in,
        _rules=rules,
    )
