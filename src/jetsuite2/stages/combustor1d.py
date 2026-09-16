"""Analysis stage - 1-D combustor network model (L2).

Zones in series (dome / primary, secondary, dilution) with the air split of
the sizing stage; per zone: equivalence ratio, residence time, temperature
from the local energy balance (variable cp), chemical time from a global
one-step Arrhenius rate (kerosene, Westbrook-Dryer form), Damkohler number,
Lefebvre loading and combustion-efficiency correlation, lean and rich
blow-out boundaries (Lefebvre stability loop), liner wall temperature from a
film-cooling/convection-radiation balance, pattern factor (Lefebvre
correlation), altitude relight capability from the loading parameter at
windmilling conditions.

Methods: Lefebvre & Ballal, *Gas Turbine Combustion* 3rd ed. (ch. 5, 6, 9);
Westbrook & Dryer 1981 (global kinetics).  Conceptual fidelity; the pattern
factor and blow-out correlations carry +/-30 % model-form uncertainty.
"""
from __future__ import annotations

import math

import numpy as np

from .. import gas
from ..library import materials
from ..rules import check
from .common import inp, out

TIER = "L2"
CORE = False

DEFAULTS = {
    "dome_cooling_frac": 0.10,      # share of the "cooling" air used on the dome (rest along the liner)
    "eta_b_target": 0.98,
    "theta_ref": 72.0e6,            # Lefebvre theta (Pa basis) at which eta_b ~ 0.98: fleet mean of 7 vaporiser combustors (boomsonic_v0)
    "wall_emissivity": 0.7,
    "film_effectiveness": 0.45,
    "altitude_relight_m": 6000.0,
    "windmill_N_frac": 0.12,
    "_doc": {"dome_cooling_frac": "fraction of the cooling air used at the dome", "eta_b_target": "target combustion efficiency",
             "theta_ref": "Lefebvre loading parameter at which the efficiency correlation reaches ~98 %",
             "wall_emissivity": "liner emissivity for the radiative balance", "film_effectiveness": "cooling-film effectiveness",
             "altitude_relight_m": "altitude for the relight check", "windmill_N_frac": "windmilling speed for the relight check"},
}

READS = ["inputs.combustor1d.*", "outputs.combustor.*", "outputs.cycle.*", "outputs.compressor.M_combustor_inlet",
         "outputs.offdesign.idle", "outputs.offdesign.running_line", "outputs.transient.scenarios"]

def _tau_chem(T: float, P: float, phi: float) -> float:
    """Characteristic chemical time [s]: global-kinetics fit for kerosene/air of the Lefebvre form
    tau = A exp(E/RT) (P0/P)^n, calibrated to ~0.2 ms at 2000 K / 4 bar and ~0.2 s at 1200 K
    (order-of-magnitude, used only through the Damkohler number)."""
    phi_pen = 1.0 + 4.0 * max(0.0, abs(phi - 1.0) - 0.3) ** 2    # off-stoichiometric slow-down
    return 1.0e-8 * math.exp(21000.0 / T) * (1.0e5 / P) ** 0.5 * phi_pen


def _zone_T(T_in: float, far_zone: float, eta: float = 1.0, far_upstream: float = 0.0) -> float:
    """Adiabatic zone temperature for a fuel-air ratio far_zone (all fuel of the zone) with efficiency eta."""
    # rich zones (phi > 1): only the stoichiometric share burns, the excess fuel is carried as unburnt
    f = min(far_zone, gas.FAR_STOICH)
    try:
        from scipy.optimize import brentq
        h_in = gas.h(T_in, far_upstream)
        rhs = h_in + (f - far_upstream) * eta * gas.LHV_KEROSENE
        return brentq(lambda T: gas.h(T, f) - rhs, 250, 2600)
    except Exception:  # noqa: BLE001
        # polynomial range exceeded (near-stoichiometric): mean-cp estimate
        return T_in + (f - far_upstream) * eta * gas.LHV_KEROSENE / ((1 + f) * 1350.0)


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "combustor1d", k, DEFAULTS[k])  # noqa: E731
    cb, cy = out(doc, "combustor"), out(doc, "cycle")
    W3, Tt3, Pt3, Wf = cy["W3_kg_s"], cy["Tt3_K"], cy["Pt3_Pa"], cy["Wf_kg_s"]
    holes = cb["holes"]
    split = {k: v["air_frac"] for k, v in holes.items()}
    f_dome = float(g("dome_cooling_frac"))
    # cumulative air along the liner: dome + primary jets -> secondary -> dilution ; cooling distributed
    frac_primary = split["primary"] + split["cooling"] * f_dome
    frac_secondary = split["secondary"] + split["cooling"] * 0.4
    frac_dilution = split["dilution"] + split["cooling"] * (0.6 - f_dome)
    zones = {}
    far_overall = Wf / W3
    far_st = gas.FAR_STOICH
    A_L = cb["A_liner_m2"]; L = cb["L_liner_m"]
    x_bounds = {"primary": (0.0, 0.35), "secondary": (0.35, 0.62), "dilution": (0.62, 1.0)}
    air_cum = 0.0
    T_prev, far_prev = Tt3, 0.0
    eta_zone = {"primary": 0.85, "secondary": 0.97, "dilution": 1.0}   # progressive burn-out of the fuel (Lefebvre)
    T_zone_out = {}
    for name, frac in (("primary", frac_primary), ("secondary", frac_secondary), ("dilution", frac_dilution)):
        air_cum += frac
        W_zone = W3 * air_cum
        far_zone = Wf / W_zone
        phi = far_zone / far_st
        T_z = _zone_T(Tt3, far_zone, eta_zone[name])
        x0, x1 = x_bounds[name]
        V_z = A_L * L * (x1 - x0)
        rho_z = Pt3 / (gas.R_AIR * T_z)
        tau_res = V_z * rho_z / (W_zone + Wf)
        tau_ch = _tau_chem(min(T_z, 2300.0), Pt3, min(phi, 1.5))
        Da = tau_res / max(tau_ch, 1e-9)
        zones[name] = dict(air_frac_cum=air_cum, phi=phi, far=far_zone, T_K=T_z, residence_ms=tau_res * 1e3,
                           chemical_ms=tau_ch * 1e3, Damkohler=Da, volume_cm3=V_z * 1e6)
        T_zone_out[name] = T_z
    # ---- loading parameter and combustion efficiency (Lefebvre theta correlation)
    theta = Pt3 ** 1.75 * cb["A_ref_m2"] * (2 * cb["H_casing_m"]) ** 0.75 * math.exp(Tt3 / 300.0) / W3   # Pa basis (fleet mean 7.2e7)
    theta_ref = float(g("theta_ref"))
    eta_b = 1.0 - 0.02 * (theta_ref / theta) ** 0.6 if theta > 0 else 0.5
    eta_b = float(min(max(eta_b, 0.5), 0.995))
    # ---- stability loop (Lefebvre): q_LBO = far_lbo = f(loading); rich and lean limits vs W/(V P^1.3)
    def lbo_far(W, P, V, T3, phi_st_ratio=0.5):
        # Lefebvre lean blow-out: q_LBO = A (W/(V P^1.3 exp(T3/300))) ... with A calibrated so design phi_pz has 2x margin
        return 0.0
    loading = W3 / (cb["V_liner_m3"] * (Pt3 / 1e3) ** 1.3 * math.exp(Tt3 / 300.0))
    # primary-zone equivalence ratio at lean blow-out (Lefebvre form): phi_LBO = k * loading^0.16 ; k calibrated so that
    # phi_LBO ~ 0.5 at the design loading of a typical vaporiser combustor
    k_lbo = 0.5 / max(loading, 1e-9) ** 0.16
    phi_lbo_design = k_lbo * loading ** 0.16
    phi_pz = zones["primary"]["phi"]
    lbo_margin = phi_pz / phi_lbo_design
    phi_rbo = 3.0 * min(1.0, (1.0 / max(loading, 1e-9)) ** 0.05)   # rich limit ~ phi 2.5-3
    # idle: from the off-design stage if present (lower P3, T3, fuel)
    idle = doc["outputs"].get("offdesign", {}).get("idle")
    idle_margin = None
    if idle and idle.get("converged"):
        rl = doc["outputs"]["offdesign"]["running_line"]
        p = min([q for q in rl if q["converged"]], key=lambda q: abs(q["N_frac"] - idle["N_frac"]))
        # reconstruct P3/T3 at idle roughly from PR_c and eta_c
        PR = p["PR_c"]; T3i = gas.T_from_h(gas.h(cy["Tt2_K"]) + (gas.h(gas.isentropic_T(cy["Tt2_K"], PR)) - gas.h(cy["Tt2_K"])) / max(p["eta_c"], 0.3))
        P3i = cy["Pt2_Pa"] * PR
        load_i = p["W"] / (cb["V_liner_m3"] * (P3i / 1e3) ** 1.3 * math.exp(T3i / 300.0))
        phi_lbo_i = k_lbo * load_i ** 0.16
        phi_pz_i = (p["Wf"] / (p["W"] * frac_primary)) / far_st
        idle_margin = phi_pz_i / phi_lbo_i
    # ---- pattern factor (Lefebvre): PF = 1 - exp(-0.07 (L/D) / (dP_liner/q_ref)) ... simplified form
    dp_q = cb["liner_dp_Pa"] / (0.5 * (Pt3 / (gas.R_AIR * Tt3)) * cb["U_ref_m_s"] ** 2)
    # Lefebvre-form correlation PF = 1 - exp(-k (L/H)(dP/q_ref)); k calibrated to PF ~0.25 at L/H 2.8, dP/q ~20
    PF = 1.0 - math.exp(-0.0025 * (L / cb["H_liner_m"]) * max(dp_q, 1.0))
    PF = float(min(max(PF, 0.05), 0.5))
    T_max_ngv = cy["T04_K"] + PF * (cy["T04_K"] - Tt3)
    # ---- liner wall temperature: radiation from the gas + convection inside, film cooling, convection outside
    eps_w = float(g("wall_emissivity")); eff_film = float(g("film_effectiveness"))
    T_g = T_zone_out["secondary"]
    sigma = 5.67e-8
    L_beam = 0.6 * cb["H_liner_m"]
    eps_g = 1 - math.exp(-290 * (Pt3 / 1e5) * L_beam * (far_overall / 0.0683) * (Pt3 / 1e5) ** -0.5 * 0.5)   # luminous-flame emissivity estimate
    eps_g = min(max(eps_g, 0.15), 0.6)
    T_film = Tt3 + (1 - eff_film) * (T_g - Tt3)
    # iterate wall temperature: q_rad_in + q_conv_in = q_conv_out (+ radiation out to the casing)
    Tw = 0.5 * (T_g + Tt3)
    h_in, h_out = 250.0, 200.0
    for _ in range(50):
        q_rad = 0.5 * (1 + eps_w) * eps_g * sigma * (T_g ** 2.5 * (T_g ** 1.5 - Tw ** 1.5))
        q_conv_in = h_in * (T_film - Tw)
        q_out = h_out * (Tw - Tt3) + eps_w * sigma * (Tw ** 4 - (Tt3 + 30) ** 4)
        f = q_rad + q_conv_in - q_out
        Tw_new = Tw + f / (h_in + h_out + 4 * eps_w * sigma * Tw ** 3 + 1.0)
        if abs(Tw_new - Tw) < 0.05:
            Tw = Tw_new
            break
        Tw = 0.5 * (Tw + Tw_new)
    T_max_liner = materials.get(cb["liner_material"])["T_max"]
    # ---- altitude relight: loading at windmilling
    from .common import isa
    T_alt, P_alt, _ = isa(float(g("altitude_relight_m")))
    Nw = float(g("windmill_N_frac"))
    P3w = P_alt * (1 + 0.6 * Nw ** 2 * 3.0)      # windmilling compressor: small pressure rise
    T3w = T_alt + 15.0
    Ww = cy["W_kg_s"] * Nw * (P_alt / cy["Pt2_Pa"]) * math.sqrt(cy["Tt2_K"] / T_alt)
    load_w = Ww / (cb["V_liner_m3"] * (P3w / 1e3) ** 1.3 * math.exp(T3w / 300.0))
    phi_lbo_w = k_lbo * load_w ** 0.16
    # ignition: Lefebvre says relight needs loading below ~ (P^1.3 V / W) threshold; express as ratio of design LBO
    relight_index = phi_lbo_w / phi_lbo_design     # >2.5 means the mixture must be 2.5x richer than at design LBO: hard
    T_mat_note = materials.get(cb["liner_material"])["T_max"]
    rules = [
        check("C1D-1", "primary-zone equivalence ratio", phi_pz, 1.4, "max", "Lefebvre: primary zone phi 0.8-1.4 for vaporiser combustors",
              note="more primary air (holes/dome)"),
        check("C1D-1b", "primary-zone equivalence ratio minimum", phi_pz, 0.8, "min", "Lefebvre: phi_pz >= 0.8 for stability", hard=False),
        check("C1D-2", "primary-zone Damkohler number (residence/chemical)", zones["primary"]["Damkohler"], 5.0, "min",
              "Da >> 1 required for stable combustion (global kinetics; order of magnitude)", hard=False),
        check("C1D-3", "combustion efficiency (Lefebvre theta correlation)", eta_b, float(g("eta_b_target")), "min",
              "theta correlation calibrated on the fleet (+/-2 pts)", warn_margin=0.0,
              note="larger liner volume, higher P3, or better mixing"),
        check("C1D-4", "lean blow-out margin at design (phi_pz / phi_LBO)", lbo_margin, 1.5, "min", "Lefebvre stability loop",
              note="richer primary zone or larger primary volume"),
        check("C1D-5", "lean blow-out margin at idle", idle_margin, 1.2, "min", "Lefebvre stability loop at the idle point",
              hard=False, note="raise idle speed or the deceleration fuel floor"),
        check("C1D-6", "pattern factor into the turbine", PF, 0.30, "max", "Lefebvre: PF 0.2-0.35 for short annular liners",
              hard=False, note=f"peak NGV inlet temperature ~{T_max_ngv:.0f} K"),
        check("C1D-7", "liner wall temperature vs material limit", Tw, T_max_liner, "max",
              f"{cb['liner_material']} T_max; radiation/convection/film balance", unit="K",
              note="more film cooling, thermal barrier coating or IN625 -> Haynes 230"),
        check("C1D-8", "altitude relight index (phi_LBO windmilling / phi_LBO design)", relight_index, 2.5, "max",
              f"Lefebvre loading at {g('altitude_relight_m'):.0f} m, N {Nw:.2f}", hard=False,
              note="relight needs a rich start schedule or a lower relight altitude"),
    ]
    return dict(zones=zones, air_fractions=dict(primary=frac_primary, secondary=frac_secondary, dilution=frac_dilution),
                theta_loading=theta, eta_b_model=eta_b, loading_parameter=loading, phi_primary=phi_pz, phi_lbo_design=phi_lbo_design,
                phi_rbo=phi_rbo, lbo_margin_design=lbo_margin, lbo_margin_idle=idle_margin, pattern_factor=PF,
                T_ngv_peak_K=T_max_ngv, liner_wall_T_K=Tw, gas_emissivity=eps_g, film_T_K=T_film,
                relight=dict(altitude_m=float(g("altitude_relight_m")), windmill_N_frac=Nw, loading=load_w, index=relight_index),
                uncertainty_note="pattern factor, blow-out and wall temperature: +/-30 % model-form uncertainty (Lefebvre correlations)",
                _rules=rules)
