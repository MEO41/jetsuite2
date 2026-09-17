"""Analysis stage - life and durability (L1/L2).

* Creep-rupture life of the turbine blade root and disc rim with the
  Larson-Miller parameter over a mission duty cycle (time fractions at
  speed/temperature), Robinson's linear damage rule.
* Low-cycle fatigue of the impeller bore and turbine disc bore from the
  start/stop cycle (Manson universal-slopes with the material's UTS, modulus
  and ductility), plus the thermal-transient bore/rim stress of the turbine
  disc during start (lumped rim/bore thermal lag).
* Bearing L10 life (ISO 281) at the real thrust and radial loads with the
  temperature/lubrication factor, lubrication method as an input.
* Containment: tri-hub burst fragment energy vs the casing's energy
  absorption (Hagg-Sankey style energy balance, conceptual).

Creep and LCF constants are derived from the material library (LMP curve
from the creep table with C = 20; Manson universal slopes) and carry a
stated factor-of-3 life uncertainty.
"""
from __future__ import annotations

import math

import numpy as np

from ..library import materials
from ..rules import check
from .common import inp, out

TIER = "L1"
CORE = False

DEFAULTS = {
    "mission": [  # duty cycle segments: fraction of time, speed fraction, T04 fraction of design
        {"name": "idle", "time_frac": 0.15, "N_frac": 0.45, "T04_frac": 0.72},
        {"name": "cruise", "time_frac": 0.65, "N_frac": 0.90, "T04_frac": 0.92},
        {"name": "max", "time_frac": 0.20, "N_frac": 1.00, "T04_frac": 1.00}],
    "starts_per_hour": 2.0,
    "life_target_h": 50.0,
    "cycles_target": 500,
    "LMP_C": 20.0,
    "life_scatter_factor": 3.0,
    "lubrication": "oil-mist",          # oil-mist | oil-air | grease
    "bearing_preload_N": 60.0,
    "casing_containment_material": "AISI321",
    "rim_thermal_tau_s": 30.0,
    "bore_thermal_tau_s": 90.0,
    "_doc": {"mission": "duty cycle segments (time_frac, N_frac, T04_frac)", "starts_per_hour": "start/stop cycles per flight hour",
             "life_target_h": "hot-section life target [h]", "cycles_target": "LCF cycle target",
             "LMP_C": "Larson-Miller constant", "life_scatter_factor": "life divided by this factor for the minimum-life verdicts",
             "lubrication": "bearing lubrication method (affects the ISO 281 a_ISO factor and the DN rating)",
             "rim_thermal_tau_s": "turbine disc rim heating time constant during a start [s]",
             "bore_thermal_tau_s": "turbine disc bore heating time constant during a start [s]",
             "bearing_preload_N": "axial preload on the angular-contact pair", "casing_containment_material": "casing material for the containment check"},
}

READS = ["inputs.life.*", "outputs.turbine.*", "outputs.compressor.*", "outputs.mechanical.*", "outputs.rotor.*",
         "outputs.speed.*", "outputs.cycle.T04_K", "outputs.cycle.Tt3_K", "outputs.layout.OD_m", "outputs.layout.casing_wall_m",
         "outputs.geometry.sheet.casing", "outputs.control.start", "outputs.thermal.temperatures"]


def lmp_curve(mat: str, C: float):
    """(LMP, log10 stress[MPa]) points from the creep table (stress for 1 % creep / 1000 h -> rupture ~ x1.4)."""
    m = materials.get(mat)
    if "creep_table" not in m:
        return None
    pts = []
    for T, s in m["creep_table"]:
        pts.append((T * (C + math.log10(1000.0)) / 1000.0, math.log10(1.4 * s)))
    pts.sort()
    return np.array(pts)


def creep_life_h(mat: str, sigma_Pa: float, T: float, C: float) -> float:
    """Rupture life [h] at stress and temperature from the LMP curve (linear in log stress)."""
    cur = lmp_curve(mat, C)
    if cur is None or sigma_Pa <= 0:
        return float("inf")
    ls = math.log10(sigma_Pa / 1e6)
    # LMP as a function of log stress (decreasing): interpolate with extrapolation
    x, y = cur[:, 1][::-1], cur[:, 0][::-1]   # ascending log-stress
    if ls <= x[0]:
        lmp = y[0] + (y[1] - y[0]) / (x[1] - x[0]) * (ls - x[0])
    elif ls >= x[-1]:
        lmp = y[-1] + (y[-1] - y[-2]) / (x[-1] - x[-2]) * (ls - x[-1])
    else:
        lmp = float(np.interp(ls, x, y))
    log_t = lmp * 1000.0 / T - C
    return 10.0 ** min(max(log_t, -3), 9)


def lcf_cycles(mat: str, d_eps: float, T: float) -> float:
    """Manson universal slopes: d_eps = 3.5 (UTS/E) N^-0.12 + D^0.6 N^-0.6, D = ductility ~ ln(1/(1-RA))."""
    m = materials.get(mat)
    uts = materials.uts_at(mat, T, minimum_basis=False)
    E = m["E"]
    D = {"aluminium": 0.15, "titanium": 0.25, "steel": 0.5, "nickel": 0.12}.get(m["family"], 0.2)
    if d_eps <= 0:
        return float("inf")
    from scipy.optimize import brentq
    f = lambda lnN: 3.5 * uts / E * math.exp(-0.12 * lnN) + D ** 0.6 * math.exp(-0.6 * lnN) - d_eps  # noqa: E731
    try:
        return math.exp(brentq(f, math.log(1.0), math.log(1e9)))
    except ValueError:
        return 1e9 if f(math.log(1e9)) > 0 else 1.0


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "life", k, DEFAULTS[k])  # noqa: E731
    t, c, me, ro, sp = out(doc, "turbine"), out(doc, "compressor"), out(doc, "mechanical"), out(doc, "rotor"), out(doc, "speed")
    T04, Tt3 = out(doc, "cycle", "T04_K"), out(doc, "cycle", "Tt3_K")
    C = float(g("LMP_C")); scatter = float(g("life_scatter_factor"))
    mat_t = t["material"]
    # predicted metal temperatures from the thermal stage (section 6) replace the mechanical-stage assumptions when present
    thm = (doc["outputs"].get("thermal") or {}).get("temperatures") or {}
    me = dict(me)
    me["turbine"] = dict(me["turbine"])
    T_src = "assumed (mechanical inputs)"
    if thm.get("T_rim_K"):
        me["turbine"]["T_rim_K"], me["turbine"]["T_bore_K"] = float(thm["T_rim_K"]), float(thm["T_bore_K"])
        T_src = f"thermal network L1 +/-{thm.get('band_K', 40):.0f} K"
    # ---- creep: blade root and disc rim over the mission (stress ~ N^2, temperature ~ T04 fraction)
    dmg_blade = dmg_rim = 0.0
    seg_out = []
    for s in g("mission"):
        Nf, Tf, tf = float(s["N_frac"]), float(s["T04_frac"]), float(s["time_frac"])
        sig_b = t["sigma_root_mcs_Pa"] / 1.05 ** 2 * Nf ** 2
        T_b = T04 * Tf - float(doc["inputs"]["turbine"].get("T_metal_offset_K", 120.0))
        sig_r = me["turbine"]["sigma_avg_Pa"] / 1.05 ** 2 * Nf ** 2
        T_r = me["turbine"]["T_rim_K"] - (1 - Tf) * 300.0
        Lb, Lr = creep_life_h(mat_t, sig_b, T_b, C), creep_life_h(mat_t, sig_r, T_r, C)
        dmg_blade += tf / Lb; dmg_rim += tf / Lr
        seg_out.append(dict(name=s["name"], time_frac=tf, sigma_blade_MPa=sig_b / 1e6, T_blade_K=T_b, life_blade_h=Lb,
                            sigma_rim_MPa=sig_r / 1e6, T_rim_K=T_r, life_rim_h=Lr))
    life_blade = 1.0 / dmg_blade if dmg_blade > 0 else float("inf")
    life_rim = 1.0 / dmg_rim if dmg_rim > 0 else float("inf")
    # ---- LCF: bore strain range per start-stop cycle (0 -> MCS): elastic strain = sigma_peak/E, plus plastic if above yield
    def bore_cycles(mat, sig_peak, T):
        m = materials.get(mat)
        sy = materials.yield_at(mat, T)
        eps_e = sig_peak / m["E"]
        eps_p = 0.0 if sig_peak <= sy else (sig_peak - sy) / (0.1 * m["E"])   # crude strain hardening slope E/10
        d_eps = 1.0 * (eps_e + eps_p)  # zero-to-max cycle: strain range = peak strain
        return lcf_cycles(mat, d_eps, T), d_eps
    N_imp, de_imp = bore_cycles(c["material"], me["impeller"]["sigma_peak_Pa"], me["impeller"]["T_disc_K"])
    N_tur, de_tur = bore_cycles(mat_t, me["turbine"]["sigma_peak_Pa"], me["turbine"]["T_bore_K"])
    # ---- thermal transient of the turbine disc during start: rim heats with tau ~ 15 s, bore with ~120 s
    m_t = materials.get(mat_t)
    dT_max = 0.0
    T_rim_ss, T_bore_ss = me["turbine"]["T_rim_K"], me["turbine"]["T_bore_K"]
    T_r, T_b = 300.0, 300.0
    tau_r, tau_b = float(g("rim_thermal_tau_s")), float(g("bore_thermal_tau_s"))
    # the start fuel ramp (control stage) sets how fast the gas temperature rises: the rim and bore see a
    # gas-side ramp of duration t_ramp = 1 / ramp_rate (time for the Wf/P3 command to reach the accel line)
    ramp = doc["outputs"].get("control", {}).get("start", {}).get("ramp_rate")
    t_ramp = (1.0 / float(ramp)) if ramp else 0.0
    dt = 0.1
    for i in range(3000):
        f = min(i * dt / t_ramp, 1.0) if t_ramp > 0 else 1.0
        T_gr = 300.0 + (T_rim_ss - 300.0) * f
        T_gb = 300.0 + (T_bore_ss - 300.0) * f
        T_r += (T_gr - T_r) * dt / tau_r
        T_b += (T_gb - T_b) * dt / tau_b + (T_r - T_b) * dt / 200.0
        dT_max = max(dT_max, T_r - T_b)
    sig_th = m_t["E"] * m_t["alpha"] * dT_max / (1 - m_t["nu"]) * 0.35  # bore thermal stress ~ 0.35 E a dT/(1-nu) (parabolic radial gradient)
    sig_bore_total = me["turbine"]["sigma_peak_Pa"] + sig_th
    stress_src = f"L1 disc factor + 0.35 E alpha dT/(1-nu) thermal term"
    # an ingested FE result (overrides.life.sigma_bore_total_Pa, L3) replaces the L1 superposition; the LCF curve stays L1
    ov = (doc.get("overrides", {}).get("life", {}) or {}).get("sigma_bore_total_Pa")
    if ov and ov.get("value"):
        sig_bore_total = float(ov["value"])
        stress_src = f"{ov.get('tier', 'L3')} FE stress ({ov.get('source', '')[:60]})"
    N_tur_th, _ = bore_cycles(mat_t, sig_bore_total, me["turbine"]["T_bore_K"])
    # ---- bearing L10 with axial load and lubrication
    brg = ro["bearing"]
    Fa = max(0.3 * abs(me["impeller"]["axial_gas_load_N"]), 50.0) + float(g("bearing_preload_N"))   # net after the turbine counter-thrust (crude, 30 %)
    Fr = max(abs(ro["F_front_bearing_N"]), abs(ro["F_rear_bearing_N"])) + 0.02 * (ro["m_impeller_kg"] + ro["m_turbine_kg"]) * 9.81 * 10
    X, Y = (1.0, 0.0) if Fa / max(Fr, 1e-3) < 0.5 else (0.44, 1.23)    # 15 deg contact angle approx
    P_eq = X * Fr + Y * Fa
    a_iso = {"oil-mist": 1.0, "oil-air": 1.2, "grease": 0.4}.get(str(g("lubrication")), 0.8)
    T_brg = float(thm.get("T_bearing_rear_K") or doc["inputs"]["rotor"].get("bearing_T_K", 420.0))
    a_temp = 1.0 if T_brg <= 400 else max(0.3, 1.0 - (T_brg - 400) / 250)
    L10 = a_iso * a_temp * (brg["C"] * 1e3 / max(P_eq, 1.0)) ** 3 * 1e6 / (60 * sp["rpm"])
    dn_ok = brg["bore"] * sp["rpm_mcs"] <= brg["dn_limit"] * {"oil-mist": 1.0, "oil-air": 1.1, "grease": 0.5}.get(str(g("lubrication")), 0.8)
    # ---- containment: 1/3 disc fragment at burst speed vs casing absorption
    omega_b = sp["omega_rad_s"] * sp["mcs_factor"] * me["turbine"]["burst_ratio"]
    m_frag = ro["m_turbine_kg"] / 3.0
    r_cg = 0.55 * t["r_tip_rotor_m"]
    E_frag = 0.5 * m_frag * (omega_b * r_cg) ** 2
    cas_mat = str(g("casing_containment_material"))
    sig_u = materials.uts_at(cas_mat, 700.0, minimum_basis=False)
    t_cas = out(doc, "layout", "casing_wall_m")
    w_frag = t["h_rotor_m"] + t["t_rim"] * 1e-3 if "t_rim" in t else t["h_rotor_m"] + 0.02
    # Hagg-Sankey type: energy absorbed by shear + membrane ~ sigma_u * t * perimeter * t * k (k ~ 3 for ductile stainless)
    E_abs = 3.0 * sig_u * t_cas ** 2 * (2 * w_frag + 2 * 0.05)
    t_req = math.sqrt(E_frag / (3.0 * sig_u * (2 * w_frag + 2 * 0.05)))
    life_target = float(g("life_target_h")); cyc_target = float(g("cycles_target"))
    rules = [
        check("LIFE-1", "turbine blade creep life over the mission / scatter", life_blade / scatter, life_target, "min",
              f"Larson-Miller from the {mat_t} creep table (C {C}), Robinson damage", unit="h",
              note="lower T04 or rpm, or MAR-M247"),
        check("LIFE-2", "turbine disc rim creep life / scatter", life_rim / scatter, life_target, "min", "as LIFE-1", unit="h"),
        check("LIFE-3", "impeller bore LCF cycles / scatter", N_imp / scatter, cyc_target, "min",
              f"Manson universal slopes, {c['material']}", note="lower bore stress: boreless hub or lower U2"),
        check("LIFE-4", "turbine bore LCF cycles incl. start thermal stress / scatter", N_tur_th / scatter, cyc_target, "min",
              f"Manson universal slopes (L1), {mat_t}; bore stress {sig_bore_total/1e6:.0f} MPa from {stress_src}; thermal dT_max {dT_max:.0f} K; T {T_src}",
              note="slower start, thicker hub, or boreless wheel"),
        check("LIFE-5", "bearing L10 life (ISO 281, lubrication/temperature factors)", L10, life_target * 4, "min",
              f"{brg['id']} C {brg['C']} kN, P_eq {P_eq:.0f} N, {g('lubrication')}", unit="h"),
        check("LIFE-6", "bearing DN with the lubrication method", 1.0 if dn_ok else 0.0, 1.0, "min", "catalogue DN x lubrication factor", warn_margin=0.0,
              note="grease halves the DN rating: use oil-mist / oil-air"),
        check("LIFE-7", "casing wall vs containment thickness (1/3 disc fragment at burst)", t_cas * 1e3, t_req * 1e3, "min",
              f"energy balance, {cas_mat} UTS at 700 K, k 3 (conceptual)", unit="mm", hard=False,
              note="a containment ring around the turbine plane is the usual answer"),
    ]
    return dict(mission=seg_out, creep=dict(blade_life_h=life_blade, rim_life_h=life_rim, damage_blade=dmg_blade, damage_rim=dmg_rim),
                lcf=dict(impeller_cycles=N_imp, impeller_strain=de_imp, turbine_cycles=N_tur, turbine_strain=de_tur,
                         turbine_cycles_with_thermal=N_tur_th, thermal_dT_max_K=dT_max, thermal_stress_Pa=sig_th, thermal_ramp_s=t_ramp,
                         sigma_bore_total_Pa=sig_bore_total, stress_source=stress_src),
                bearing=dict(L10_h=L10, P_eq_N=P_eq, Fa_N=Fa, Fr_N=Fr, a_iso=a_iso, a_temp=a_temp, lubrication=str(g("lubrication"))),
                containment=dict(E_fragment_J=E_frag, E_absorbed_J=E_abs, t_required_mm=t_req * 1e3, t_casing_mm=t_cas * 1e3,
                                 burst_omega=omega_b),
                uncertainty_note=f"life numbers carry a factor-of-{scatter:.0f} scatter (applied in the verdicts)", _rules=rules)
