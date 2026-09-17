"""Stage 9 - mechanical integrity of the rotating parts.

* Impeller disc: average tangential stress (Robinson) from the hub profile
  and the blade rim load, peak stress with a bore/boreless concentration
  factor, burst speed ratio (14 CFR 33.27 style, k = 0.85 Ftu basis).
* Inducer root: radial tension of the inducer blade.
* Turbine disc: same average-tangential / burst treatment with the creep
  allowable at the rim temperature.
* Impeller retention: nut preload vs the axial gas load and the thermal
  loosening allowance.

Everything is closed-form and runs in milliseconds; a 3-D FE is the next
fidelity level (the stress-relief factors are documented for that hand-off).
"""
from __future__ import annotations

import math

import numpy as np

from ..library import materials
from ..rules import check
from .common import inp, out

DEFAULTS = {
    "impeller_mount": "bore",       # 'bore' (shaft through) or 'stub' (boreless hub, rear stub)
    "turbine_mount": "stub",        # 'stub' (boreless wheel with integral stub, bolted/friction-welded) or 'bore' (shaft through)
    "k_peak_boreless": 1.3,         # peak / average tangential stress, boreless thick-hub disc
    "k_peak_bored": 1.6,            # peak / average for a bored, thick-hub disc (Lame bore concentration; 2.0 for a thin uniform disc)
    "burst_k": 0.85,                # Robinson: average tangential stress at burst = k * Ftu
    "burst_ratio_required": 1.20,
    "disc_T_impeller_offset_K": -20.0,   # impeller disc metal T relative to Tt3
    "turbine_disc_rim_T_K": 950.0,
    "turbine_disc_bore_T_K": 750.0,
    "nut_preload_fraction": 0.6,    # of the shaft thread proof load
    "_doc": {
        "impeller_mount": "'bore' (tie-shaft through the impeller) or 'stub' (boreless)",
        "k_peak_boreless": "peak/average tangential stress factor for a boreless disc",
        "k_peak_bored": "peak/average tangential stress factor for a bored disc",
        "burst_k": "Robinson burst factor (average tangential stress at burst / UTS)",
        "burst_ratio_required": "required burst speed / MCS",
        "disc_T_impeller_offset_K": "impeller disc metal temperature minus Tt3",
        "turbine_disc_rim_T_K": "turbine disc rim metal temperature", "turbine_disc_bore_T_K": "turbine disc bore temperature",
        "nut_preload_fraction": "impeller nut preload as a fraction of thread proof load",
    },
}

READS = ["inputs.mechanical.*", "outputs.speed.omega_rad_s", "outputs.speed.mcs_factor", "outputs.cycle.Tt3_K",
         "outputs.compressor.material", "outputs.compressor.r1s_m", "outputs.compressor.r1h_m",
         "outputs.compressor.r2_m", "outputs.compressor.U2_m_s", "outputs.compressor.sigma_root_mcs_Pa",
         "outputs.compressor.t_root_m",
         "outputs.compressor.sigma_allow_Pa", "outputs.compressor.P2_Pa", "outputs.compressor.P1_Pa",
         "outputs.turbine.material", "outputs.turbine.r_hub_rotor_m", "outputs.turbine.r_tip_rotor_m",
         "outputs.turbine.sigma_root_mcs_Pa", "outputs.turbine.sigma_allow_Pa",
         "outputs.rotor.impeller_hub_profile", "outputs.rotor.turbine_disc_profile", "outputs.rotor.m_blades_impeller_kg",
         "outputs.rotor.m_turbine_blades_kg", "outputs.rotor.impeller_bore_m", "outputs.rotor.journal_d_m",
         "outputs.rotor.shaft_material"]


def section_props(profile):
    """Area and integral r^2 dA of a closed (x, r) polygon (meridional section)."""
    p = np.asarray(profile, dtype=float)
    x, r = p[:, 0], p[:, 1]
    x2, r2 = np.roll(x, -1), np.roll(r, -1)
    A = 0.5 * np.sum(x * r2 - x2 * r)
    # integral r^2 dA over polygon = (1/12) sum (x_i y_{i+1} - x_{i+1} y_i)(y_i^2 + y_i y_{i+1} + y_{i+1}^2)
    Ir2 = (1 / 12.0) * np.sum((x * r2 - x2 * r) * (r ** 2 + r * r2 + r2 ** 2))
    return abs(float(A)), abs(float(Ir2))


def disc_stresses(profile, rho, omega, m_blades, r_blade_cg, bored: bool, k_boreless, k_bored):
    A, Ir2 = section_props(profile)
    sig_avg = (rho * omega ** 2 * Ir2 + m_blades * omega ** 2 * r_blade_cg / (2 * math.pi)) / A
    k = k_bored if bored else k_boreless
    return sig_avg, k * sig_avg, A


def run(doc: dict) -> dict:
    m = lambda k: inp(doc, "mechanical", k, DEFAULTS[k])  # noqa: E731
    omega, mcs = out(doc, "speed", "omega_rad_s"), out(doc, "speed", "mcs_factor")
    om = omega * mcs
    Tt3 = out(doc, "cycle", "Tt3_K")
    c, t, rr = out(doc, "compressor"), out(doc, "turbine"), out(doc, "rotor")
    bored = str(m("impeller_mount")).lower() == "bore"
    kb, kbb = float(m("k_peak_boreless")), float(m("k_peak_bored"))
    burst_k, burst_req = float(m("burst_k")), float(m("burst_ratio_required"))

    # ---- impeller
    mat_c = c["material"]
    rho_c = materials.get(mat_c)["rho"]
    T_disc = Tt3 + float(m("disc_T_impeller_offset_K"))
    fty_c, ftu_c = materials.yield_at(mat_c, T_disc), materials.uts_at(mat_c, T_disc)
    sig_avg_c, sig_peak_c, A_c = disc_stresses(rr["impeller_hub_profile"], rho_c, om, rr["m_blades_impeller_kg"],
                                               0.7 * c["r2_m"], bored, kb, kbb)
    burst_c = math.sqrt(burst_k * ftu_c / sig_avg_c)
    # inducer root radial tension (untapered blade of height r1s-r1h)
    sig_ind = 0.6 * rho_c * om ** 2 * (c["r1s_m"] ** 2 - c["r1h_m"] ** 2) / 2
    # axial gas load on the impeller (front face at inlet static, back face at exit static, crude)
    F_axial = (c["P2_Pa"] - c["P1_Pa"]) * math.pi * (c["r2_m"] ** 2 - c["r1h_m"] ** 2) * 0.35

    # ---- turbine disc
    mat_t = t["material"]
    rho_t = materials.get(mat_t)["rho"]
    T_rim, T_bore = float(m("turbine_disc_rim_T_K")), float(m("turbine_disc_bore_T_K"))
    allow_t_rim = materials.allowable_at(mat_t, T_rim)
    ftu_t = materials.uts_at(mat_t, 0.5 * (T_rim + T_bore))
    t_bored = str(m("turbine_mount")).lower() == "bore"
    sig_avg_t, sig_peak_t, A_t = disc_stresses(rr["turbine_disc_profile"], rho_t, om, rr["m_turbine_blades_kg"],
                                               0.5 * (t["r_hub_rotor_m"] + t["r_tip_rotor_m"]), t_bored, kb, kbb)
    # ingested L3 disc stresses (FE) replace the L1 disc-factor values *before* the rules are evaluated, so the
    # verdicts are on the higher-tier number (the graph re-applies the same overrides to the outputs afterwards)
    ov = doc.get("overrides", {}).get("mechanical", {}) or {}
    stress_src_c = f"L1 disc factor k_peak {kbb if bored else kb}"
    if ov.get("impeller.sigma_peak_Pa", {}).get("value"):
        sig_peak_c = float(ov["impeller.sigma_peak_Pa"]["value"])
        stress_src_c = f"{ov['impeller.sigma_peak_Pa'].get('tier', 'L3')} FE ({ov['impeller.sigma_peak_Pa'].get('source', '')[:40]})"
    stress_src_t = f"L1 disc factor k_peak {kbb if t_bored else kb}"
    if ov.get("turbine.sigma_peak_Pa", {}).get("value"):
        sig_peak_t = float(ov["turbine.sigma_peak_Pa"]["value"])
        stress_src_t = f"{ov['turbine.sigma_peak_Pa'].get('tier', 'L3')} FE ({ov['turbine.sigma_peak_Pa'].get('source', '')[:40]})"
    if ov.get("turbine.sigma_avg_Pa", {}).get("value"):
        sig_avg_t = float(ov["turbine.sigma_avg_Pa"]["value"])
    burst_t = math.sqrt(burst_k * ftu_t / sig_avg_t)
    allow_t_bore = materials.allowable_at(mat_t, T_bore)

    # ---- impeller nut / tie shaft
    d_thread = rr["impeller_bore_m"]
    sh_mat = rr["shaft_material"]
    A_s = math.pi / 4 * (0.85 * d_thread) ** 2
    F_proof = materials.yield_at(sh_mat, 400.0) * A_s
    F_preload = float(m("nut_preload_fraction")) * F_proof
    # thermal loosening: aluminium/titanium impeller grows more than the steel shaft
    alpha_c, alpha_s = materials.get(mat_c)["alpha"], materials.get(sh_mat)["alpha"]
    dL_rel = (alpha_c - alpha_s) * (T_disc - 293.0)
    hub_len = 0.6 * c["r2_m"] * 2 * 0.32
    E_s = materials.get(sh_mat)["E"]
    F_thermal = E_s * A_s * dL_rel * hub_len / hub_len  # strain-based load change on the tie shaft
    F_min_clamp = F_preload + min(F_thermal, 0.0) - F_axial

    rules = [
        check("MECH-1", "impeller disc peak stress at MCS vs yield", sig_peak_c / 1e6, fty_c / 1e6, "max",
              f"{mat_c} min-basis yield at {T_disc:.0f} K; stress from {stress_src_c}", unit="MPa",
              note="lower U2 (OPR/backsweep), boreless mount, or a stronger material"),
        check("MECH-2", "impeller burst speed ratio", burst_c, burst_req, "min", "14 CFR 33.27 style; Robinson k 0.85",
              note="reduce average tangential stress: thicker hub, lower U2"),
        check("MECH-3", "inducer root radial stress vs yield", sig_ind / 1e6, fty_c / 1e6, "max", f"{mat_c} yield", unit="MPa"),
        check("MECH-4", "exducer root stress (from compressor stage, sized to limit) vs allowable",
              min(c["sigma_root_mcs_Pa"], c["sigma_allow_Pa"]) / 1e6 if c["t_root_m"] < 0.0199 else c["sigma_root_mcs_Pa"] / 1e6,
              c["sigma_allow_Pa"] / 1e6, "max", "compressor.COMP-3", unit="MPa", warn_margin=0.0),
        check("MECH-5", "turbine disc peak stress vs bore allowable", sig_peak_t / 1e6, allow_t_bore / 1e6, "max",
              f"{mat_t} allowable at bore {T_bore:.0f} K; stress from {stress_src_t}", unit="MPa", note="thicker web/hub, lower rpm"),
        check("MECH-6", "turbine disc average stress vs rim creep allowable", sig_avg_t / 1e6, allow_t_rim / 1e6, "max",
              f"{mat_t} allowable at rim {T_rim:.0f} K", unit="MPa"),
        check("MECH-7", "turbine burst speed ratio", burst_t, burst_req, "min", "14 CFR 33.27 style; Robinson k 0.85"),
        check("MECH-8", "turbine blade root (from turbine stage)", t["sigma_root_mcs_Pa"] / 1e6, t["sigma_allow_Pa"] / 1e6,
              "max", "turbine.TURB-5 (no margin factor here)", unit="MPa"),
        check("MECH-9", "impeller clamp load retained hot", F_min_clamp, 0.2 * F_preload, "min",
              "tie-shaft preload minus thermal relaxation and gas load >= 20 % of preload", unit="N",
              note="higher preload, longer tie shaft, or a matched-expansion sleeve"),
    ]
    return dict(
        impeller=dict(material=mat_c, T_disc_K=T_disc, sigma_avg_Pa=sig_avg_c, sigma_peak_Pa=sig_peak_c, yield_Pa=fty_c,
                      uts_Pa=ftu_c, burst_ratio=burst_c, section_area_m2=A_c, inducer_root_Pa=sig_ind, bored=bored,
                      axial_gas_load_N=F_axial, U2_mcs_m_s=c["U2_m_s"] * mcs),
        turbine=dict(material=mat_t, bored=t_bored, T_rim_K=T_rim, T_bore_K=T_bore, sigma_avg_Pa=sig_avg_t, sigma_peak_Pa=sig_peak_t,
                     allow_rim_Pa=allow_t_rim, allow_bore_Pa=allow_t_bore, uts_Pa=ftu_t, burst_ratio=burst_t,
                     section_area_m2=A_t),
        retention=dict(thread_d_m=d_thread, preload_N=F_preload, proof_load_N=F_proof, thermal_load_N=F_thermal,
                       min_clamp_N=F_min_clamp),
        _rules=rules,
    )
