"""Analysis stage - secondary air, thermal network and oil system (L1).

Replaces the assumed metal temperatures with predictions:

* Secondary-air network (lumped): compressor-exit leakage through the impeller back-face labyrinth into
  the shaft tunnel, through the tunnel to the turbine disc front cavity, out through the rim seal into
  the gas path.  Martin's labyrinth formula, cavity windage heating (free-disc moment), rim-seal purge
  check against the minimum ingestion-free purge fraction.
* Thermal network (steady, nodal): turbine blade root -> disc rim -> web -> bore -> shaft -> rear bearing
  -> housing; impeller hub -> front bearing; cavity air and hot gas as boundary temperatures with rotating-
  disc and flat-plate convection; bearing friction heat (Palmgren) removed by the oil / mist flow and the
  housing.  Gauss-Seidel on ~12 nodes.
* Oil / mist system: heat per bearing, oil flow for a 40 K rise, mist-air flow, pump duty.
* Bearing-temperature abort criterion: predicted bearing temperature + margin, consumed by the test bench.

The life stage reads the predicted rim / bore / bearing temperatures when this stage has run; the mechanical
stage keeps its temperature inputs (core cannot depend on an opt-in analysis) and THM-8 flags a mismatch.
Correlations are L1 (Owen & Rogers rotating-disc heat transfer, Martin labyrinth, Palmgren bearing friction)
and carry a declared +/-40 K band on metal temperatures until a thermocouple datum exists.
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
    "seal_radial_clearance_mm": 0.15,     # impeller back-face labyrinth radial clearance
    "seal_teeth": 3,
    "seal_radius_ratio": 0.55,            # seal radius / r2
    "rim_seal_clearance_mm": 0.30,        # turbine rim seal axial gap
    "purge_min_fraction": 0.005,          # minimum rim purge / gas-path flow for no ingestion (Owen, declared)
    "cooling_budget_max": 0.03,           # max secondary air / core flow
    "oil_dT_K": 40.0,                     # oil temperature rise across a bearing
    "oil_supply_T_K": 330.0,
    "oil_cp_J_kgK": 2000.0,
    "mist_air_l_min": 60.0,               # oil-mist carrier air per bearing
    "housing_to_casing_conductance_W_K": 2.0,   # bearing housing -> casing (bolted flange, conservative)
    "bearing_abort_margin_K": 30.0,
    "metal_T_band_K": 40.0,               # declared band on predicted metal temperatures
    "_doc": {"seal_radial_clearance_mm": "impeller back-face labyrinth radial clearance", "seal_teeth": "labyrinth teeth",
             "seal_radius_ratio": "labyrinth radius / impeller exit radius", "rim_seal_clearance_mm": "turbine rim seal axial gap",
             "purge_min_fraction": "minimum rim purge fraction of gas-path flow (ingestion limit, declared)",
             "cooling_budget_max": "maximum secondary-air fraction of core flow", "oil_dT_K": "design oil temperature rise",
             "oil_supply_T_K": "oil supply temperature", "oil_cp_J_kgK": "oil specific heat", "mist_air_l_min": "mist carrier air per bearing",
             "housing_to_casing_conductance_W_K": "bearing housing to casing conductance", "bearing_abort_margin_K": "abort = predicted bearing T + margin",
             "metal_T_band_K": "declared band on the predicted metal temperatures"},
}

READS = ["inputs.thermal.*", "inputs.life.lubrication", "inputs.mechanical.turbine_disc_rim_T_K", "inputs.mechanical.turbine_disc_bore_T_K",
         "outputs.cycle.*", "outputs.speed.rpm", "outputs.speed.rpm_mcs", "outputs.turbine.*", "outputs.compressor.r2_m",
         "outputs.compressor.b2_m", "outputs.compressor.material", "outputs.compressor.T02_K", "outputs.rotor.*", "outputs.layout.*",
         "outputs.mechanical.turbine.T_rim_K", "outputs.mechanical.turbine.T_bore_K", "outputs.mechanical.impeller.T_disc_K",
         "outputs.mechanical.impeller.axial_gas_load_N"]

R_AIR = 287.05


def _mu_air(T):
    return 1.716e-5 * (T / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 110.4)


def _k_air(T):
    return 0.0241 * (T / 273.15) ** 0.85


def _h_rot_disc(omega, r, T, P):
    """Rotating disc in air: turbulent Nu = 0.0197 Re_r^0.8 (Owen & Rogers), laminar 0.4 Re^0.5."""
    rho = P / (R_AIR * T)
    Re = rho * omega * r * r / _mu_air(T)
    Nu = 0.0197 * Re ** 0.8 if Re > 2.5e5 else 0.4 * math.sqrt(max(Re, 1.0))
    return Nu * _k_air(T) / max(r, 1e-4)


def _h_plate(V, L, T, P):
    rho = P / (R_AIR * T)
    Re = rho * V * L / _mu_air(T)
    Nu = 0.037 * Re ** 0.8 * 0.7 ** 0.33 if Re > 5e5 else 0.664 * math.sqrt(max(Re, 1.0)) * 0.7 ** 0.33
    return Nu * _k_air(T) / max(L, 1e-4)


def _labyrinth(P_in, P_out, T_in, r, c, n, Cd=0.7):
    """Martin: W = Cd A sqrt((P_in^2 - P_out^2) / (R T n))."""
    A = 2 * math.pi * r * c
    if P_out >= P_in:
        return 0.0
    return Cd * A * math.sqrt(max(P_in * P_in - P_out * P_out, 0.0) / (R_AIR * T_in * n))


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "thermal", k, DEFAULTS[k])  # noqa: E731
    cy, t, ro, lay, sp = out(doc, "cycle"), out(doc, "turbine"), out(doc, "rotor"), out(doc, "layout"), out(doc, "speed")
    c = out(doc, "compressor")
    W = cy["W_kg_s"]; Tt3, Pt3, T04, Pt4, Tt5 = cy["Tt3_K"], cy["Pt3_Pa"], cy["T04_K"], cy["Pt4_Pa"], cy["Tt5_K"]
    omega = sp["rpm"] * 2 * math.pi / 60
    r2, r_hub_t, r_tip_t = c["r2_m"], t["r_hub_rotor_m"], t["r_tip_rotor_m"]
    mat_t, mat_c = t["material"], c["material"]
    k_t, k_c = materials.get(mat_t)["k"], materials.get(mat_c)["k"]
    k_s = materials.get(ro.get("shaft_material", "AISI4340"))["k"]
    # ------------------------------------------------------------- secondary air
    r_seal = float(g("seal_radius_ratio")) * r2
    c_seal = float(g("seal_radial_clearance_mm")) * 1e-3
    P_back = Pt3 * (0.90 - 0.15 * (1 - (r_seal / r2) ** 2))         # back-face static falls toward the seal (disc pumping)
    P_turb_hub = Pt4 * 0.55                                           # rotor-inlet hub static ~ 0.55 Pt4 for a 4:1 stage
    W_leak = _labyrinth(P_back, P_turb_hub, Tt3, r_seal, c_seal, int(g("seal_teeth")))
    # windage in the impeller back cavity and the turbine front cavity (free-disc moment, turbulent)
    def windage(r, T, P):
        rho = P / (R_AIR * T)
        Re = rho * omega * r * r / _mu_air(T)
        Cm = 0.0622 * Re ** -0.2
        return 0.5 * Cm * rho * omega ** 2 * r ** 5 * omega           # W
    Q_wind_back = windage(r2, Tt3, P_back)
    Q_wind_turb = windage(r_hub_t, Tt3, P_turb_hub)
    cp_air = 1050.0
    T_cav_back = Tt3 + (Q_wind_back / max(W_leak * cp_air, 1e-3) if W_leak > 0 else 60.0)
    T_cav_turb = T_cav_back + (Q_wind_turb / max(W_leak * cp_air, 1e-3) if W_leak > 0 else 80.0)
    T_cav_back = min(T_cav_back, Tt3 + 150.0); T_cav_turb = min(T_cav_turb, Tt3 + 300.0)
    purge_frac = W_leak / W
    cooling_frac = purge_frac                                        # single circuit: all leakage purges the rim seal
    # rim seal: minimum purge for no ingestion; if the leakage falls short, the front cavity sees hot gas
    purge_min = float(g("purge_min_fraction"))
    ingestion = purge_frac < purge_min
    T_front_gas = T_cav_turb if not ingestion else 0.5 * (T_cav_turb + T04)
    # ------------------------------------------------------------- thermal network
    # geometry from the disc profile: rim, web, hub radii and thicknesses
    prof = np.array(ro["turbine_disc_profile"], float)
    x_prof, r_prof = prof[:, 0], prof[:, 1]
    r_rim, r_min = float(r_prof.max()), float(r_prof.min())
    def thickness_at(r_lo, r_hi):
        xs = x_prof[(r_prof >= r_lo - 1e-9) & (r_prof <= r_hi + 1e-9)]
        return float(xs.max() - xs.min()) if len(xs) >= 2 else 0.005
    t_rim = ro.get("t_rim_turbine_m", thickness_at(0.9 * r_rim, r_rim))
    r_web = 0.5 * (r_rim + r_min); t_web = thickness_at(0.4 * r_rim + 0.6 * r_min, 0.6 * r_rim + 0.4 * r_min)
    t_hub = thickness_at(r_min, r_min + 0.25 * (r_rim - r_min))
    # nodes: 0 rim, 1 web, 2 bore/hub, 3 shaft mid, 4 rear bearing, 5 rear housing, 6 impeller hub, 7 front bearing, 8 front housing
    n = 9
    G = np.zeros((n, n)); Gb = np.zeros(n); Tb = np.zeros(n); Q = np.zeros(n)
    def link(i, j, val):
        G[i, j] += val; G[j, i] += val
    def bound(i, val, T):
        Gb[i] += val; Tb[i] += val * T
    # blade root -> rim: blade metal temperature from the turbine stage through the root section
    A_root = t["n_rotor"] * (t.get("chord_rotor_m", 0.02) * 0.16 * t.get("chord_rotor_m", 0.02)) if t.get("n_rotor") else 25 * 6e-5
    bound(0, k_t * A_root / 0.004, t["T_metal_K"])
    # rim platform convection from the relative gas (T_rel ~ T04 - U^2/(2 cp) + 0.5 W^2/(2cp) ~ 0.9 T04 at the hub)
    U_h = omega * r_hub_t
    T_rel = T04 - 0.5 * U_h ** 2 / 1150.0
    A_platform = 2 * math.pi * r_rim * t_rim
    bound(0, _h_plate(0.6 * U_h, t_rim, T_rel, Pt4 * 0.6) * A_platform, T_rel)
    # rim -> web -> hub conduction
    link(0, 1, k_t * 2 * math.pi * (0.75 * r_rim + 0.25 * r_min) * t_web / max(0.5 * (r_rim - r_min), 1e-3))
    link(1, 2, k_t * 2 * math.pi * (0.25 * r_rim + 0.75 * r_min) * (0.5 * (t_web + t_hub)) / max(0.5 * (r_rim - r_min), 1e-3))
    # disc faces: front face to the (purged) cavity air, back face to the exhaust cavity (~Tt5 gas, low velocity)
    h_front = _h_rot_disc(omega, r_web, T_front_gas, P_turb_hub)
    h_back = _h_rot_disc(omega, r_web, Tt5, Pt4 * 0.4)
    A_face = math.pi * (r_rim ** 2 - r_min ** 2)
    bound(1, h_front * 0.7 * A_face, T_front_gas); bound(1, h_back * 0.7 * A_face, Tt5)
    bound(2, h_front * 0.3 * A_face, T_front_gas); bound(2, h_back * 0.3 * A_face, Tt5)
    # hub -> shaft -> rear bearing conduction (shaft between disc mid-plane and the rear bearing)
    L_sh = max(lay["x_disc_mid_m"] - lay["x_rear_bearing_m"], 0.01)
    d_j = ro["journal_d_m"]
    A_sh = math.pi / 4 * d_j ** 2
    link(2, 3, k_s * A_sh / (0.5 * L_sh)); link(3, 4, k_s * A_sh / (0.5 * L_sh))
    # shaft surface to the tunnel air (cavity air at T_cav_turb)
    bound(3, _h_rot_disc(omega, 0.5 * d_j, T_cav_turb, P_turb_hub) * math.pi * d_j * L_sh, T_cav_turb)
    # bearings: Palmgren friction heat, oil cooling, housing conduction
    brg = ro["bearing"]
    lub = str(doc["inputs"].get("life", {}).get("lubrication", "oil-mist"))
    nu_oil = 12.0                                                    # cSt at the bearing (thin turbine oil hot)
    dm = 0.5 * (brg["bore"] + brg["od"])                              # mm
    f0 = {"oil-mist": 1.0, "oil-air": 1.0, "grease": 2.0}.get(lub, 1.5)
    M0 = 1e-7 * f0 * (nu_oil * sp["rpm"]) ** (2.0 / 3.0) * dm ** 3    # N mm
    F_ax = abs(float(out(doc, "mechanical")["impeller"].get("axial_gas_load_N", 300.0)))   # net axial gas load on the thrust bearing
    M1 = 0.001 * (F_ax + 30.0) * dm                                   # N mm, load term (f1 ~ 0.001 for AC bearings)
    Q_brg = (M0 + M1) * 1e-3 * omega                                  # W per bearing
    m_oil = Q_brg / (float(g("oil_cp_J_kgK")) * float(g("oil_dT_K")))
    G_oil = m_oil * float(g("oil_cp_J_kgK"))                          # W/K effective (oil leaves at T_brg - dT/2 ~ conservative)
    G_house = float(g("housing_to_casing_conductance_W_K"))
    T_oil = float(g("oil_supply_T_K"))
    for i_b, i_h, T_wall in ((4, 5, Tt3), (7, 8, Tt3)):
        Q[i_b] += Q_brg
        bound(i_b, 2.0 * G_oil, T_oil)                                # oil/mist carries the heat (2x: both rings wetted)
        link(i_b, i_h, 25.0)                                          # outer ring -> housing (fit conductance, W/K)
        bound(i_h, G_house, T_wall)                                   # housing -> casing / cavity wall near Tt3
        bound(i_h, 2.0 * G_oil, T_oil)
    # impeller hub: back face to the back cavity, front (gas path) to ~Tt2..T02, hub -> front bearing through the shaft
    T_gas_imp = 0.5 * (cy["Tt2_K"] + c.get("T02_K", Tt3))
    A_imp = math.pi * r2 ** 2
    bound(6, _h_rot_disc(omega, 0.7 * r2, T_cav_back, P_back) * A_imp, T_cav_back)
    bound(6, _h_rot_disc(omega, 0.7 * r2, T_gas_imp, 0.5 * (cy["Pt2_Pa"] + Pt3)) * 1.5 * A_imp, T_gas_imp)
    L_fs = max(lay["x_front_bearing_m"] - lay["x_impeller_back_m"], 0.005)
    link(6, 7, k_s * A_sh / L_fs)
    # solve (Gauss-Seidel)
    T = np.full(n, 600.0)
    for _ in range(400):
        for i in range(n):
            s = G[i].sum() + Gb[i]
            if s > 0:
                T[i] = (G[i] @ T + Tb[i] + Q[i]) / s
    T_rim, T_web, T_bore, T_shaft, T_brg_r, T_hous_r, T_imp, T_brg_f, T_hous_f = [float(v) for v in T]
    # oil / mist system
    mist_air = float(g("mist_air_l_min"))
    oil_l_h = 2 * m_oil / 900.0 * 3600.0                              # both bearings, rho_oil 900 kg/m3
    pump = dict(oil_flow_l_h=oil_l_h, pressure_bar=3.0 if lub != "grease" else 0.0, mist_air_l_min=2 * mist_air if lub == "oil-mist" else 0.0,
                heat_W=2 * Q_brg, note="oil-mist: oil metered into the carrier air; oil-air: pulsed lubricator")
    # abort criterion for the bench
    T_brg = max(T_brg_r, T_brg_f)
    abort_T = T_brg + float(g("bearing_abort_margin_K"))
    band = float(g("metal_T_band_K"))
    # mechanical stage assumptions vs prediction
    T_rim_assumed = float(doc["inputs"].get("mechanical", {}).get("turbine_disc_rim_T_K", out(doc, "mechanical")["turbine"]["T_rim_K"]))
    T_bore_assumed = float(doc["inputs"].get("mechanical", {}).get("turbine_disc_bore_T_K", out(doc, "mechanical")["turbine"]["T_bore_K"]))
    T_max_t = materials.get(mat_t)["T_max"]
    rules = [
        check("THM-1", "turbine disc rim temperature vs material limit", T_rim, T_max_t, "max",
              f"{mat_t} T_max; network L1 +/-{band:.0f} K", unit="K", warn_margin=band / T_max_t, note="more rim purge, cooler cavity air, or a rim heat shield"),
        check("THM-2", "turbine disc bore temperature vs shaft / bearing tolerance", T_bore, 850.0, "max",
              f"bore heat sinks into the shaft; L1 +/-{band:.0f} K", unit="K", warn_margin=band / 850.0, hard=False),
        check("THM-3", "rear bearing temperature vs bearing rating", T_brg_r, float(brg["T_max"]), "max",
              f"{brg['id']} T_max; Palmgren heat {Q_brg:.0f} W, oil {m_oil*1e3*60:.1f} g/min at dT {float(g('oil_dT_K')):.0f} K", unit="K",
              warn_margin=band / float(brg["T_max"]), note="more oil flow, a cooled housing, or move the rear bearing forward"),
        check("THM-4", "secondary air (leakage + purge) fraction of core flow", cooling_frac, float(g("cooling_budget_max")), "max",
              f"labyrinth {int(g('seal_teeth'))} teeth, c {c_seal*1e3:.2f} mm at r {r_seal*1e3:.1f} mm (Martin)", note="tighter seal or more teeth"),
        check("THM-5", "rim-seal purge fraction vs ingestion minimum", purge_frac, purge_min, "min",
              "declared minimum (Owen); below it hot gas enters the front cavity", warn_margin=0.5,
              note="open the labyrinth clearance or add a dedicated purge bleed"),
        check("THM-6", "front bearing temperature vs bearing rating", T_brg_f, float(brg["T_max"]), "max", f"{brg['id']} T_max", unit="K",
              warn_margin=band / float(brg["T_max"]), hard=False),
        check("THM-7", "bearing abort setting (predicted + margin) below the bearing rating", abort_T, float(brg["T_max"]), "max",
              f"abort = predicted {T_brg:.0f} K + {float(g('bearing_abort_margin_K')):.0f} K margin", unit="K", warn_margin=0.0, hard=False),
        check("THM-8", "mechanical-stage rim temperature assumption vs prediction |dT|", abs(T_rim - T_rim_assumed), band, "max",
              f"assumed {T_rim_assumed:.0f} K, predicted {T_rim:.0f} K; bore assumed {T_bore_assumed:.0f} K, predicted {T_bore:.0f} K", unit="K", hard=False,
              note=f"set mechanical.turbine_disc_rim_T_K={T_rim:.0f} mechanical.turbine_disc_bore_T_K={T_bore:.0f} to carry the prediction into the stress rules"),
    ]
    return dict(secondary_air=dict(W_leak_kg_s=W_leak, leak_fraction=purge_frac, cooling_fraction=cooling_frac, P_back_face_Pa=P_back,
                                   P_turbine_hub_Pa=P_turb_hub, T_cavity_back_K=T_cav_back, T_cavity_turbine_K=T_cav_turb,
                                   windage_back_W=Q_wind_back, windage_turbine_W=Q_wind_turb, rim_ingestion=ingestion, purge_min_fraction=purge_min),
                temperatures=dict(T_rim_K=T_rim, T_web_K=T_web, T_bore_K=T_bore, T_shaft_K=T_shaft, T_bearing_rear_K=T_brg_r, T_housing_rear_K=T_hous_r,
                                  T_impeller_hub_K=T_imp, T_bearing_front_K=T_brg_f, T_housing_front_K=T_hous_f, band_K=band,
                                  T_rel_gas_K=T_rel, T_front_cavity_gas_K=T_front_gas),
                bearing_heat=dict(Q_per_bearing_W=Q_brg, M0_Nmm=M0, M1_Nmm=M1, oil_flow_per_bearing_kg_s=m_oil, lubrication=lub),
                oil_system=pump, abort=dict(bearing_T_abort_K=abort_T, basis="predicted bearing T + margin"),
                assumed_vs_predicted=dict(rim_assumed_K=T_rim_assumed, rim_predicted_K=T_rim, bore_assumed_K=T_bore_assumed, bore_predicted_K=T_bore),
                _rules=rules)
