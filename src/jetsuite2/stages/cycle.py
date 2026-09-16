"""Stage 2 - thermodynamic cycle (design point).

Station numbering (SAE ARP 755): 0 ambient, 2 compressor face, 3 compressor
exit, 4 turbine inlet, 5 turbine exit, 8 nozzle throat.

Variable-cp gas model (``jetsuite2.gas``).  Solved explicitly per unit
airflow, then scaled to the thrust target -- no iteration except the
FAR-for-T4 and enthalpy-to-temperature inversions.  Runs in milliseconds.

The component efficiencies here are *assumptions*; the compressor and turbine
stages produce their own estimates and the CONV rules flag inconsistency.
``jet converge`` iterates the two until they agree.
"""
from __future__ import annotations

import math

from .. import gas
from ..rules import check
from .common import inp, out

DEFAULTS = {
    "OPR": 4.0,
    "T04_K": 1150.0,
    "eta_c": 0.80,          # compressor isentropic total-total (stage incl. diffuser)
    "eta_t": 0.87,          # turbine isentropic total-total
    "eta_b": 0.97,          # combustion efficiency
    "dp_burner": 0.05,      # combustor total-pressure loss fraction
    "intake_recovery": 0.98,  # Pt2/Pt0 (subsonic pitot + duct)
    "dp_jetpipe": 0.02,     # turbine exit -> nozzle throat loss fraction
    "eta_mech": 0.99,       # shaft mechanical efficiency (bearings, windage)
    "bleed_frac": 0.01,     # compressor-exit bleed lost from the cycle (bearing pressurisation, cooling)
    "power_offtake_W": 100.0,   # generator / pump drive
    "nozzle_Cv": 0.98,      # velocity coefficient
    "nozzle_Cd": 0.97,      # discharge coefficient (effective/geometric area)
    "fuel_LHV_J_per_kg": gas.LHV_KEROSENE,
    "_doc": {
        "OPR": "compressor total pressure ratio Pt3/Pt2 (single centrifugal stage: 2.5-5)",
        "T04_K": "turbine inlet total temperature [K]; uncooled cast wheel practice 1100-1200 K",
        "eta_c": "assumed compressor stage isentropic efficiency (tt); compared with the compressor stage estimate",
        "eta_t": "assumed turbine isentropic efficiency (tt); compared with the turbine stage estimate",
        "eta_b": "combustion efficiency",
        "dp_burner": "combustor pressure loss dP/Pt3",
        "intake_recovery": "intake total pressure recovery Pt2/Pt0",
        "dp_jetpipe": "jet pipe / nozzle duct pressure loss dP/Pt5",
        "eta_mech": "mechanical efficiency of the spool",
        "bleed_frac": "fraction of compressor airflow bled off (not returned)",
        "power_offtake_W": "shaft power extracted for accessories [W]",
        "nozzle_Cv": "nozzle velocity coefficient",
        "nozzle_Cd": "nozzle discharge coefficient",
        "fuel_LHV_J_per_kg": "fuel lower heating value [J/kg]",
    },
}

READS = ["inputs.cycle.*", "outputs.requirements.thrust_N", "outputs.requirements.T0_K",
         "outputs.requirements.P0_Pa", "outputs.requirements.V0", "outputs.requirements.Tt0_K",
         "outputs.requirements.Pt0_Pa", "outputs.requirements.mach"]


def run(doc: dict) -> dict:
    c = lambda k, d=None: inp(doc, "cycle", k, DEFAULTS.get(k) if d is None else d)  # noqa: E731
    F_target = out(doc, "requirements", "thrust_N")
    T0, P0, V0 = out(doc, "requirements", "T0_K"), out(doc, "requirements", "P0_Pa"), out(doc, "requirements", "V0")
    Tt0, Pt0 = out(doc, "requirements", "Tt0_K"), out(doc, "requirements", "Pt0_Pa")
    M0 = out(doc, "requirements", "mach")

    OPR, T04 = float(c("OPR")), float(c("T04_K"))
    eta_c, eta_t, eta_b = float(c("eta_c")), float(c("eta_t")), float(c("eta_b"))
    dp_b, rec, dp_jp = float(c("dp_burner")), float(c("intake_recovery")), float(c("dp_jetpipe"))
    eta_m, bleed = float(c("eta_mech")), float(c("bleed_frac"))
    P_off = float(c("power_offtake_W"))
    Cv, Cd = float(c("nozzle_Cv")), float(c("nozzle_Cd"))
    LHV = float(c("fuel_LHV_J_per_kg"))

    # --- station 2: compressor face
    if M0 > 1.0:  # normal-shock recovery times duct recovery
        g = 1.4
        pi_ns = ((((g + 1) * M0 ** 2) / ((g - 1) * M0 ** 2 + 2)) ** (g / (g - 1))
                 * ((g + 1) / (2 * g * M0 ** 2 - (g - 1))) ** (1 / (g - 1)))
        rec_eff = rec * pi_ns
    else:
        rec_eff = rec
    Tt2, Pt2 = Tt0, Pt0 * rec_eff

    # --- compressor (per kg/s of inlet air)
    Pt3 = Pt2 * OPR
    T3s = gas.isentropic_T(Tt2, OPR)
    dh_ideal = gas.h(T3s) - gas.h(Tt2)
    dh_c = dh_ideal / eta_c
    Tt3 = gas.T_from_h(gas.h(Tt2) + dh_c)

    # --- combustor
    Pt4 = Pt3 * (1.0 - dp_b)
    far = gas.far_for_T04(Tt3, T04, eta_b, LHV)
    w3 = 1.0 - bleed                      # airflow entering the combustor per unit inlet flow
    w4 = w3 * (1.0 + far)                 # gas flow into the turbine

    # --- turbine: power balance (per unit inlet airflow); offtake applied after W is known -> 2-pass
    def turbine(W_guess: float):
        P_turb = (1.0 * dh_c) / eta_m + P_off / max(W_guess, 1e-6)   # per unit inlet airflow
        dh_t = P_turb / w4
        h5 = gas.h(T04, far) - dh_t
        Tt5 = gas.T_from_h(h5, far)
        h5s = gas.h(T04, far) - dh_t / eta_t
        T5s = gas.T_from_h(h5s, far)
        Pt5 = Pt4 * math.exp((gas.phi(T5s, far) - gas.phi(T04, far)) / gas.R_AIR)
        return dh_t, Tt5, Pt5, P_turb

    def nozzle(Tt8, Pt8):
        """Return V8, P8 static, T8 static, M8, choked flag, rho8 for the (convergent) nozzle."""
        g8 = float(gas.gamma(Tt8, far))
        pr_crit = (2.0 / (g8 + 1.0)) ** (g8 / (g8 - 1.0))   # P*/Pt
        npr = Pt8 / P0
        if npr * pr_crit >= 1.0:   # choked
            T8, P8, g8 = gas.static_from_total(Tt8, Pt8, 1.0, far)
            V8 = math.sqrt(g8 * gas.R_AIR * T8)
            M8 = 1.0
            choked = True
        else:
            P8 = P0
            T8s = gas.isentropic_T(Tt8, P8 / Pt8, far)
            V8 = math.sqrt(max(2.0 * (gas.h(Tt8, far) - gas.h(T8s, far)), 0.0))
            T8 = T8s
            M8 = V8 / gas.a_sound(T8, far)
            choked = False
        rho8 = P8 / (gas.R_AIR * T8)
        return V8, P8, T8, M8, choked, rho8, npr

    W = 1.0
    for _ in range(4):   # offtake makes the per-unit power depend weakly on W
        dh_t, Tt5, Pt5, P_turb = turbine(W)
        Pt8 = Pt5 * (1.0 - dp_jp)
        V8, P8, T8, M8, choked, rho8, npr = nozzle(Tt5, Pt8)
        V8e = Cv * V8
        # per unit inlet airflow: gross thrust = w4 V8 + (P8-P0) A8 ; A8 = w4/(rho8 V8)
        A8_unit = w4 / (rho8 * V8)
        Fg_unit = w4 * V8e + (P8 - P0) * A8_unit
        Fn_unit = Fg_unit - 1.0 * V0
        W_new = F_target / Fn_unit
        if abs(W_new - W) < 1e-9:
            W = W_new
            break
        W = W_new

    Wf = W * w3 * far
    A8_eff = A8_unit * W
    A8_geo = A8_eff / Cd
    tsfc = Wf / F_target  # kg/(N s)
    P_comp = W * dh_c
    P_turb_total = P_turb * W
    q_fuel = Wf * LHV
    eta_th = (0.5 * W * w4 * V8e ** 2 - 0.5 * W * V0 ** 2) / q_fuel if q_fuel > 0 else 0.0
    eta_prop = (F_target * V0) / max(0.5 * W * w4 * V8e ** 2 - 0.5 * W * V0 ** 2, 1e-9) if V0 > 0 else 0.0

    stations = {
        "0": dict(Tt=Tt0, Pt=Pt0, T=T0, P=P0, W=W),
        "2": dict(Tt=Tt2, Pt=Pt2, W=W),
        "3": dict(Tt=Tt3, Pt=Pt3, W=W * w3),
        "4": dict(Tt=T04, Pt=Pt4, W=W * w4, far=far),
        "5": dict(Tt=Tt5, Pt=Pt5, W=W * w4, far=far),
        "8": dict(Tt=Tt5, Pt=Pt8, T=T8, P=P8, M=M8, V=V8e, W=W * w4, far=far),
    }
    rules = [
        check("CYC-1", "OPR within single-stage centrifugal practice", OPR, 5.0, "max",
              "Dixon & Hall ch.7; micro-turbojet fleet 2.5-4.5", note="above ~5 a single backswept impeller needs U2 > 600 m/s"),
        check("CYC-2", "OPR above useful minimum", OPR, 2.2, "min", "cycle: specific thrust collapses below ~2.2"),
        check("CYC-3", "T04 within uncooled cast-wheel practice", T04, 1250.0, "max",
              "IN-713LC/MAR-M247 uncooled rotor practice (JetCat/AMT class 1050-1200 K)",
              note="above 1250 K an uncooled wheel is creep-life limited; check MECH turbine rules"),
        check("CYC-4", "T04 above combustor stability floor", T04, 950.0, "min", "lean stability at idle/design"),
        check("CYC-5", "compressor exit temperature vs aluminium impeller limit (info)", Tt3, None, "info", "materials.T_max", unit="K"),
        check("CYC-6", "nozzle pressure ratio", npr, None, "info", "-", unit="-"),
        check("CYC-7", "fuel-air ratio below 60 % stoichiometric", far, 0.6 * gas.FAR_STOICH, "max", "combustor: overall phi < 0.6"),
    ]
    return dict(
        W_kg_s=W, Wf_kg_s=Wf, far=far, TSFC_kg_per_N_s=tsfc, TSFC_kg_per_N_h=tsfc * 3600.0,
        specific_thrust_N_s_per_kg=F_target / W, OPR=OPR, T04_K=T04,
        Tt2_K=Tt2, Pt2_Pa=Pt2, Tt3_K=Tt3, Pt3_Pa=Pt3, Pt4_Pa=Pt4, Tt5_K=Tt5, Pt5_Pa=Pt5, Pt8_Pa=Pt8,
        dh_c_J_kg=dh_c, dh_t_J_kg=dh_t, P_comp_W=P_comp, P_turb_W=P_turb_total, P_offtake_W=P_off,
        W3_kg_s=W * w3, W4_kg_s=W * w4, bleed_frac=bleed,
        turbine_PR_tt=Pt4 / Pt5, NPR=npr, nozzle_choked=choked, A8_eff_m2=A8_eff, A8_geo_m2=A8_geo,
        V8_m_s=V8e, M8=M8, T8_K=T8, P8_Pa=P8, eta_thermal=eta_th, eta_propulsive=eta_prop,
        eta_c_assumed=eta_c, eta_t_assumed=eta_t, intake_recovery_effective=rec_eff,
        stations=stations, _rules=rules,
    )
