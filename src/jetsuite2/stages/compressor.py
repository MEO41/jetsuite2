"""Stage 4 - centrifugal compressor meanline sizing (impeller + diffuser).

Method (Dixon & Hall ch. 7, Aungier 2000, Japikse 1996):

* inlet: axial inflow, hub/tip ratio given; shroud radius chosen for minimum
  inducer relative Mach (Dixon 7.4) at the spool speed from the ``speed`` stage;
* work: Euler with Wiesner slip on the Aungier effective blade count,
  exit flow coefficient phi2 = Cm2/U2 given, power-input factor for disc
  friction / recirculation; U2 follows in closed form from the cycle work;
* exit width from continuity with blade-metal and aerodynamic blockage;
* exducer blade root sized so the centrifugal bending stress of the backswept
  blade (tapered cantilever plate, Kt 1.4) equals the material allowable at
  MCS -- this is where the impeller material enters the geometry;
* choke check on the inducer throat (relative total conditions);
* diffuser: vaneless gap + vaned radial diffuser (or vaneless), then deswirl;
* efficiency estimate: Casey-Robinson-type peak polytropic efficiency vs
  global flow coefficient with a Reynolds/size correction and tip-clearance
  penalty.  It is an estimate for consistency with the cycle assumption, not
  a performance prediction.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

from .. import gas
from ..library import materials
from ..rules import check
from .common import inp, out, is_auto, nearest_prime_not_sharing
from .speed import inducer_min_mrel

DEFAULTS = {
    "material": "Ti-6Al-4V",
    "hub_tip_ratio": 0.35,
    "backsweep_deg": 30.0,          # blade angle at exit from radial, positive = backswept
    "n_main": "auto",
    "n_splitter": "auto",
    "splitter_length_frac": 0.6,    # splitter meridional length / main blade length
    "phi2": 0.28,                   # exit flow coefficient Cm2/U2
    "power_input_factor": 1.03,     # disc friction + recirculation
    "impeller_eta_offset": 0.06,    # impeller tt efficiency = stage eta_c + offset
    "aero_blockage_exit": 0.06,     # boundary-layer blockage at impeller exit
    "tip_clearance_mm": "auto",     # auto: max(0.2, 0.002*D2)
    "blade_tip_thickness_mm": "auto",   # auto: max(0.5, 0.005*D2)
    "incidence_deg": 3.0,
    "axial_length_ratio": 0.32,     # impeller axial length / D2
    "diffuser_type": "vaned",       # 'vaned' or 'vaneless'
    "vaneless_gap_ratio": 1.08,     # r3/r2
    "diffuser_radius_ratio": 1.38,  # r4/r2 (vaned; 1.35-1.5 practice) ; vaneless uses 1.8
    "n_vanes": "auto",
    "diffuser_exit_angle_deg": 35.0,    # vane trailing-edge angle from radial
    "diffuser_throat_mach": 0.70,   # design Mach at the vaned-diffuser throat (sizes the throat; 0.65-0.85 practice)
    "diffuser_Cp": 0.62,            # static pressure recovery of the vaned channel
    "n_deswirl": "auto",
    "combustor_inlet_mach": 0.12,
    "safety_factor_blade": 1.0,
    "blade_load_relief": 0.8,       # 2-D plate root stress / 1-D strip theory (calibrated on boomsonic_v0 Morley FE)
    "_doc": {
        "material": "impeller material (library.materials)",
        "hub_tip_ratio": "inducer hub/shroud radius ratio (0.3-0.45)",
        "backsweep_deg": "exit blade backsweep from radial [deg]; 20-40 typical for stability",
        "n_main": "'auto' or number of full blades",
        "n_splitter": "'auto' (= n_main) or number of splitter blades (0 for none)",
        "phi2": "impeller exit flow coefficient Cm2/U2 (0.22-0.32)",
        "power_input_factor": "work input factor for disc friction and recirculation (1.02-1.05)",
        "impeller_eta_offset": "impeller-only efficiency minus stage efficiency",
        "aero_blockage_exit": "aerodynamic blockage fraction at impeller exit",
        "tip_clearance_mm": "'auto' or running shroud clearance [mm]",
        "blade_tip_thickness_mm": "'auto' or blade thickness at the tip/TE [mm]",
        "incidence_deg": "inducer incidence at design [deg]",
        "axial_length_ratio": "impeller axial length / D2 (0.28-0.36)",
        "diffuser_type": "'vaned' or 'vaneless'",
        "vaneless_gap_ratio": "vaneless space outer radius / r2 (1.05-1.15)",
        "diffuser_radius_ratio": "diffuser outer radius / r2",
        "n_vanes": "'auto' or diffuser vane count",
        "diffuser_exit_angle_deg": "vane trailing-edge angle from radial",
        "diffuser_Cp": "vaned channel static pressure recovery coefficient",
        "n_deswirl": "'auto' or number of axial deswirl vanes",
        "combustor_inlet_mach": "Mach at diffuser/deswirl exit into the combustor annulus",
        "safety_factor_blade": "allowable / stress at MCS for the exducer root (allowable is already minimum-basis yield)",
        "blade_load_relief": "ratio of 2-D plate root stress to 1-D strip theory; 0.8 reproduces the boomsonic_v0 verified plate FE (618 vs 780 MPa)",
    },
}

READS = ["inputs.compressor.*", "outputs.speed.rpm", "outputs.speed.omega_rad_s", "outputs.speed.mcs_factor",
         "outputs.cycle.W_kg_s", "outputs.cycle.Tt2_K", "outputs.cycle.Pt2_Pa", "outputs.cycle.Tt3_K",
         "outputs.cycle.Pt3_Pa", "outputs.cycle.dh_c_J_kg", "outputs.cycle.eta_c_assumed", "outputs.cycle.OPR"]

NU_AIR_500K = 3.8e-5  # kinematic viscosity of air at ~500 K, 4 bar is ~1e-5; used with rho, mu below
MU_AIR = lambda T: 1.458e-6 * T ** 1.5 / (T + 110.4)  # Sutherland  # noqa: E731


def wiesner_slip(beta2b_deg: float, z_eff: float) -> float:
    return 1.0 - math.sqrt(math.cos(math.radians(beta2b_deg))) / z_eff ** 0.7


def exducer_root_thickness(rho: float, omega: float, r2: float, beta2b_deg: float, b2: float,
                           t_tip: float, sigma_allow: float, kt: float = 1.4, relief: float = 0.8) -> tuple[float, float]:
    """Root thickness [m] of a backswept exducer blade (tapered cantilever plate) so that
    the root bending stress from the blade's own centrifugal load equals sigma_allow.

    Load per unit chord length at spanwise y: w(y) = rho t(y) omega^2 r sin(beta).
    Root moment M = int w(y) y dy ; sigma = Kt 6 M / t_root^2.
    Returns (t_root, sigma_at_t_root)."""
    s = math.sin(math.radians(abs(beta2b_deg)))
    q = rho * omega ** 2 * r2 * s

    def sigma(t_root):
        # t(y) = t_root + (t_tip - t_root) y/b ; M = q int (t_root y + (t_tip-t_root) y^2/b) dy
        M = q * (t_root * b2 ** 2 / 2 + (t_tip - t_root) * b2 ** 2 / 3)
        return relief * kt * 6 * M / t_root ** 2

    t_lo = max(t_tip, 0.4e-3)
    if sigma(t_lo) <= sigma_allow:
        return t_lo, sigma(t_lo)
    t_hi = 0.02
    if sigma(t_hi) > sigma_allow:
        return t_hi, sigma(t_hi)
    t = brentq(lambda t: sigma(t) - sigma_allow, t_lo, t_hi, xtol=1e-7)
    return t, sigma(t)


def efficiency_estimate(phi_global: float, Re: float, clearance_over_b2: float, backsweep_deg: float,
                        vaned: bool) -> dict:
    """Stage total-total polytropic efficiency estimate (conceptual).

    Peak-efficiency curve after Casey & Robinson (2013) trend: best around
    phi 0.07-0.10, falling either side; Reynolds correction after Casey (1985):
    (1-eta)/(1-eta_ref) = 0.3 + 0.7 (Re_ref/Re)^0.2; tip clearance after
    Pampreen: delta eta ~ 0.3 (eps/b2); vaneless diffuser -0.02."""
    if phi_global < 0.07:
        eta_peak = 0.87 - 1.0 * (0.07 - phi_global)
    elif phi_global <= 0.10:
        eta_peak = 0.87
    else:
        eta_peak = 0.87 - 0.6 * (phi_global - 0.10)
    re_corr = 0.3 + 0.7 * (1.0e6 / max(Re, 1e4)) ** 0.2
    eta = 1.0 - (1.0 - eta_peak) * re_corr
    d_clr = 0.3 * clearance_over_b2
    d_bs = -0.005 * max(0.0, (backsweep_deg - 30.0) / 10.0)  # slight penalty for very large backsweep (longer passage)
    d_diff = 0.0 if vaned else -0.02
    eta_p = eta - d_clr + d_bs + d_diff
    return dict(eta_p=eta_p, eta_peak=eta_peak, re_corr=re_corr, d_clearance=d_clr, d_diffuser=d_diff)


def run(doc: dict) -> dict:
    c = lambda k: inp(doc, "compressor", k, DEFAULTS[k])  # noqa: E731
    W, Tt2, Pt2 = out(doc, "cycle", "W_kg_s"), out(doc, "cycle", "Tt2_K"), out(doc, "cycle", "Pt2_Pa")
    Tt3, Pt3, dh_c = out(doc, "cycle", "Tt3_K"), out(doc, "cycle", "Pt3_Pa"), out(doc, "cycle", "dh_c_J_kg")
    eta_c_assumed, OPR = out(doc, "cycle", "eta_c_assumed"), out(doc, "cycle", "OPR")
    rpm, omega, mcs = out(doc, "speed", "rpm"), out(doc, "speed", "omega_rad_s"), out(doc, "speed", "mcs_factor")
    mat = c("material")
    nu = float(c("hub_tip_ratio"))
    beta2b = float(c("backsweep_deg"))
    phi2 = float(c("phi2"))
    pif = float(c("power_input_factor"))

    # ------------------------------------------------------------- inlet
    M1s_rel, r1s, C1, M1 = inducer_min_mrel(W, Tt2, Pt2, omega, nu)
    r1h = nu * r1s
    r1rms = math.sqrt(0.5 * (r1s ** 2 + r1h ** 2))
    T1, P1, g1 = gas.static_from_total(Tt2, Pt2, M1)
    rho1 = P1 / (gas.R_AIR * T1)
    a1 = math.sqrt(g1 * gas.R_AIR * T1)
    U1s, U1h, U1rms = omega * r1s, omega * r1h, omega * r1rms
    W1s = math.sqrt(C1 ** 2 + U1s ** 2)
    beta1s = math.degrees(math.atan2(U1s, C1))
    beta1h = math.degrees(math.atan2(U1h, C1))
    beta1rms = math.degrees(math.atan2(U1rms, C1))
    inc = float(c("incidence_deg"))

    # ---------------------------------------------------- blade count (auto)
    # Aungier-type estimate on the mean blade angle and radius ratio; needs r2 -> iterate once
    n_main_in, n_split_in = c("n_main"), c("n_splitter")
    split_frac = float(c("splitter_length_frac"))
    # provisional U2 with a typical slip to seed the blade-count estimate
    U2_seed = math.sqrt(dh_c / pif / (0.88 - phi2 * math.tan(math.radians(beta2b))))
    r2_seed = U2_seed / omega
    if is_auto(n_main_in):
        beta_m = 0.5 * (beta1rms + beta2b)
        z_est = 2 * math.pi * math.cos(math.radians(beta_m)) / (0.4 * math.log(max(r2_seed / r1rms, 1.2)))
        n_main = int(min(max(round(z_est / 2.0), 7), 16))
    else:
        n_main = int(n_main_in)
    n_split = n_main if is_auto(n_split_in) else int(n_split_in)
    z_eff = n_main + n_split * split_frac
    z_exit = n_main + n_split

    # ------------------------------------------------------------- work / U2
    sigma = wiesner_slip(beta2b, z_eff)
    psi = sigma - phi2 * math.tan(math.radians(beta2b))     # Euler work coefficient
    if psi <= 0.2:
        raise ValueError(f"work coefficient {psi:.3f} too low: reduce backsweep ({beta2b} deg) or phi2 ({phi2})")
    dh_euler = dh_c / pif
    U2 = math.sqrt(dh_euler / psi)
    r2 = U2 / omega
    D2 = 2 * r2
    Cm2 = phi2 * U2
    Ct2 = sigma * U2 - Cm2 * math.tan(math.radians(beta2b))
    C2 = math.hypot(Cm2, Ct2)
    alpha2 = math.degrees(math.atan2(Ct2, Cm2))
    W2 = math.hypot(Cm2, U2 - Ct2)
    beta2_flow = math.degrees(math.atan2(U2 - Ct2, Cm2))

    # impeller exit total state (all the work is in; impeller-only efficiency for pressure)
    eta_imp = min(eta_c_assumed + float(c("impeller_eta_offset")), 0.94)
    T02 = Tt3
    T02s = gas.T_from_h(gas.h(Tt2) + eta_imp * dh_c)
    P02 = Pt2 * math.exp((gas.phi(T02s) - gas.phi(Tt2)) / gas.R_AIR)
    cp2 = float(gas.cp(T02))
    T2 = T02 - C2 ** 2 / (2 * cp2)
    g2 = float(gas.gamma(T2))
    P2 = P02 * (T2 / T02) ** (g2 / (g2 - 1))
    rho2 = P2 / (gas.R_AIR * T2)
    M2 = C2 / math.sqrt(g2 * gas.R_AIR * T2)
    M2_rel = W2 / math.sqrt(g2 * gas.R_AIR * T2)
    diffuser_loss_implied = 1.0 - Pt3 / P02

    # ------------------------------------------------ exit width and blade root
    t_tip_in = c("blade_tip_thickness_mm")
    t_tip = (max(0.5, 0.005 * D2 * 1e3) if is_auto(t_tip_in) else float(t_tip_in)) * 1e-3
    clr_in = c("tip_clearance_mm")
    clearance = (max(0.2, 0.002 * D2 * 1e3) if is_auto(clr_in) else float(clr_in)) * 1e-3
    aero_blk = float(c("aero_blockage_exit"))
    sf = float(c("safety_factor_blade"))
    rho_m = materials.get(mat)["rho"]
    T_metal = T02  # exducer runs at about the exit total temperature
    sig_allow = materials.yield_at(mat, T_metal) / sf
    omega_mcs = omega * mcs
    # iterate b2 <-> root thickness (blockage depends on root thickness)
    t_root = 2.0 * t_tip
    b2 = 0.05 * r2
    for _ in range(30):
        t_mean = 0.5 * (t_root + t_tip)
        B_metal = z_exit * t_mean / (2 * math.pi * r2 * math.cos(math.radians(beta2b)))
        b2_new = W / (rho2 * Cm2 * 2 * math.pi * r2 * (1 - B_metal - aero_blk))
        t_root_new, sig_root = exducer_root_thickness(rho_m, omega_mcs, r2, beta2b, b2_new, t_tip, sig_allow,
                                                      relief=float(c("blade_load_relief")))
        if abs(b2_new - b2) < 1e-7 and abs(t_root_new - t_root) < 1e-7:
            b2, t_root = b2_new, t_root_new
            break
        b2, t_root = b2_new, t_root_new
    B_total = B_metal + aero_blk
    L_ax = float(c("axial_length_ratio")) * D2

    # ------------------------------------------------------------ choke check
    # relative total conditions at the inducer (rms) and throat area per passage
    W1rms = math.hypot(C1, U1rms)
    cp1 = float(gas.cp(T1))
    T01rel = T1 + W1rms ** 2 / (2 * cp1)
    g1r = float(gas.gamma(T01rel))
    P01rel = P1 * (T01rel / T1) ** (g1r / (g1r - 1))
    A1 = math.pi * (r1s ** 2 - r1h ** 2)
    t_le = 0.5 * t_tip   # leading edge thinned to half the tip thickness
    beta1b_rms = beta1rms - inc   # blade angle (incidence opens the throat relative to the flow angle)
    # spanwise-integrated throat choking capacity, same model as the off-design loss model (perf.closs)
    from ..perf import closs as _closs
    _g = _closs.CompressorGeometry(r1h=r1h, r1s=r1s, r2=r2, b2=b2, beta1b_rms=beta1b_rms, beta2b=beta2b, n_main=n_main,
                                   n_split=n_split, split_frac=split_frac, t_le=t_le, t_te=t_tip, clearance=clearance,
                                   L_ax=L_ax, r3=1.08 * r2, r4=1.4 * r2, b3=b2, n_vanes=0, vane_le_angle=0.0,
                                   vane_te_angle=0.0, vane_throat=0.0)   # diffuser fields unused by the inducer choke
    W_choke = _closs.inducer_choke_flow(_g, C1, T1, P1, omega)
    blk_throat = n_main * t_le / (2 * math.pi * r1rms * math.cos(math.radians(beta1b_rms)))
    A_throat = A1 * math.cos(math.radians(beta1b_rms)) * (1 - blk_throat) * _g.throat_factor
    choke_margin = W_choke / W - 1.0

    # ----------------------------------------------------------- efficiency
    rho01 = Pt2 / (gas.R_AIR * Tt2)
    phi_global = W / (rho01 * U2 * D2 ** 2)
    Re = rho2 * U2 * b2 / MU_AIR(T2)
    vaned = str(c("diffuser_type")).lower() == "vaned"
    est = efficiency_estimate(phi_global, Re, clearance / b2, beta2b, vaned)
    # polytropic -> isentropic (tt) over the stage
    n_exp = (g2 - 1) / g2 / est["eta_p"]
    eta_tt_est = (OPR ** ((g2 - 1) / g2) - 1) / (OPR ** n_exp - 1)
    Ns = omega * math.sqrt(W / rho01) / (dh_c * eta_c_assumed) ** 0.75   # specific speed (isentropic head basis)

    # ---------------------------------------------------------------- diffuser
    r3 = float(c("vaneless_gap_ratio")) * r2
    # vaneless space: free vortex + continuity with ~constant density (short gap)
    Ct3 = Ct2 * r2 / r3
    Cm3 = Cm2 * r2 / r3 * (1 - B_total)  # blockage mixes out
    C3 = math.hypot(Cm3, Ct3)
    alpha3 = math.degrees(math.atan2(Ct3, Cm3))
    T3s_ = T02 - C3 ** 2 / (2 * cp2)
    M3 = C3 / math.sqrt(g2 * gas.R_AIR * T3s_)
    n_vanes_in = c("n_vanes")
    if vaned:
        r4 = float(c("diffuser_radius_ratio")) * r2
        if is_auto(n_vanes_in):
            n_vanes = nearest_prime_not_sharing(int(round(1.4 * n_main)), [n_main, z_exit], lo=9, hi=31)
        else:
            n_vanes = int(n_vanes_in)
        Cp = float(c("diffuser_Cp"))
        alpha4 = float(c("diffuser_exit_angle_deg"))
        # static pressure at vane LE and exit
        P3s = P02 * (T3s_ / T02) ** (g2 / (g2 - 1))
        q3 = 0.5 * rho2 * C3 ** 2
        P4 = P3s + Cp * q3
        # exit velocity from energy (total pressure drop consistent with Cp and Pt3)
        T4s_ = gas.isentropic_T(T02, P4 / Pt3)
        C4 = math.sqrt(max(2 * cp2 * (T02 - T4s_), 1.0))
        M4 = C4 / math.sqrt(g2 * gas.R_AIR * T4s_)
        b4 = b2 * 1.0   # parallel-wall diffuser
        # vane leading-edge angle: 2 deg negative incidence at design against the L2 loss-model swirl
        # (the vaneless-space flow angle of perf.closs, so L1 geometry and L2 map are consistent)
        _g.n_vanes = 0
        _g.r3, _g.r4, _g.b3 = r3, r4, b4
        _dp = _closs.evaluate(_g, W, omega, Tt2, Pt2)
        alpha3_L2 = _dp.alpha3 if _dp.ok else alpha3
        vane_le_angle = alpha3_L2 - 2.0
        # throat sized for the design throat Mach (total state ~ impeller exit total minus the vaneless loss)
        M_th = float(c("diffuser_throat_mach"))
        A_th_vd = W / gas.mass_flow_function(T02, P02 * 0.985, M_th, 1.0)
        throat_w = A_th_vd / (n_vanes * b4)
        throat_geometric = 2 * math.pi * r3 / n_vanes * math.cos(math.radians(alpha3))
    else:
        r4 = 1.8 * r2
        n_vanes = 0
        Ct4 = Ct2 * r2 / r4
        Cm4 = Cm2 * r2 / r4 * (1 - B_total)
        C4 = math.hypot(Cm4, Ct4)
        T4s_ = T02 - C4 ** 2 / (2 * cp2)
        M4 = C4 / math.sqrt(g2 * gas.R_AIR * T4s_)
        alpha4 = math.degrees(math.atan2(Ct4, Cm4))
        P4 = P02 * (T4s_ / T02) ** (g2 / (g2 - 1))
        b4 = b2
        vane_le_angle = None
        throat_w = None
        throat_geometric = None
    # deswirl: turn to axial and diffuse to the combustor inlet Mach
    M_comb = float(c("combustor_inlet_mach"))
    n_deswirl_in = c("n_deswirl")
    n_deswirl = int(round(2 * math.pi * r4 / (0.02 + 0.06 * r4))) if is_auto(n_deswirl_in) else int(n_deswirl_in)
    n_deswirl = max(n_deswirl, 12)
    A_comb_in = W / gas.mass_flow_function(Tt3, Pt3, M_comb, 1.0)
    # annulus at the deswirl exit: outer radius r4 (casing), inner from area
    r_deswirl_in = math.sqrt(max(r4 ** 2 - A_comb_in / math.pi, 0.0))
    L_deswirl = 0.6 * (r4 - r_deswirl_in) + 0.02 * r4 * 4

    # exducer blade height and camber definition (for CAD and modal checks)
    U2_mcs = U2 * mcs
    sig_allow_full = materials.yield_at(mat, T_metal)
    T_max_mat = materials.get(mat)["T_max"]

    rules = [
        check("COMP-1", "inducer shroud relative Mach", M1s_rel, 1.30, "max", "fielded micro-turbojet band (boomsonic A3R.1)",
              warn_margin=0.03, note="reduce rpm or raise hub/tip ratio"),
        check("COMP-2", "impeller tip speed U2", U2, 620.0, "max", "Ti impellers ~550-600 m/s, Al ~450-500 (Dixon; Rodgers)",
              unit="m/s", note="lower OPR, less backsweep, more blades, or accept a stronger material"),
        check("COMP-3", "exducer root stress at MCS vs allowable (root sized to the limit)",
              (min(sig_root, sig_allow) if t_root < 0.0199 else sig_root) / 1e6, sig_allow / 1e6, "max",
              f"{mat} yield at {T_metal:.0f} K / SF {sf}", unit="MPa", warn_margin=0.0,
              note="root thickness capped at 20 mm: reduce U2 or backsweep, or change material"),
        check("COMP-4", "impeller material temperature (Tt3)", T_metal, T_max_mat, "max", f"{mat} T_max", unit="K",
              note="compressor exit too hot for this material: lower OPR or change material"),
        check("COMP-5", "exit width ratio b2/D2", b2 / D2, 0.03, "min", "narrow exits lose efficiency (Rodgers): b2/D2 >= 0.03",
              warn_margin=0.1, hard=False, note="raise phi2 or backsweep, or lower rpm"),
        check("COMP-6", "relative diffusion ratio W1s/W2", W1s / W2, 2.0, "max", "Dixon & Hall / Rodgers: W1s/W2 <= ~1.8-2.0 for attached flow",
              hard=False, note="raise phi2 (wider exit), more backsweep, or reduce inducer Mach"),
        check("COMP-7", "inducer throat choke margin at design", choke_margin, 0.10, "min",
              "Rodgers: design at <= 90 % of throat choke flow (boomsonic A3R.5)", hard=False,
              note="thinner LE, fewer main blades, larger hub/tip or lower inducer relative Mach"),
        check("COMP-7b", "inducer throat not choked at design", choke_margin, 0.0, "min", "throat mass-flow function",
              warn_margin=0.0, note="the inducer throat is choked: lower rpm / relative Mach or open the throat"),
        check("COMP-8", "radius ratio r2/r1s", r2 / r1s, 1.3, "min", "Aungier: 1.4-2.2 for a radial impeller", hard=False,
              note="rpm too high for the required work: reduce rpm"),
        check("COMP-9", "radius ratio r2/r1s upper", r2 / r1s, 2.3, "max", "Aungier: 1.4-2.2 for a radial impeller", hard=False,
              note="rpm too low: raise rpm or hub/tip ratio"),
        check("COMP-10", "impeller exit absolute Mach", M2, 1.10, "max", "vaned diffuser LE tolerates ~M 1.1 (Japikse)", hard=False),
        check("COMP-11", "diffuser inlet flow angle from radial", alpha3, 78.0, "max", "vaneless stability: alpha < ~78 deg (Senoo)",
              note="more backsweep or higher phi2 to reduce swirl"),
        check("COMP-12", "estimated vs assumed stage efficiency |diff|", abs(eta_tt_est - eta_c_assumed), 0.03, "max",
              "consistency: run `jet converge`", note=f"estimate {eta_tt_est:.3f} vs cycle assumption {eta_c_assumed:.3f}"),
        check("COMP-13", "backsweep angle", beta2b, 45.0, "max", "manufacturing/loading practice 15-45 deg"),
        check("COMP-14", "backsweep angle minimum for stability", beta2b, 15.0, "min", "range/stability practice", hard=False),
        check("COMP-15", "implied diffuser total-pressure loss", diffuser_loss_implied, 0.12, "max",
              "impeller/diffuser split: 3-10 % typical", hard=False,
              note="impeller_eta_offset too large or eta_c assumption too low"),
    ]
    return dict(
        material=mat, rpm=rpm, omega_rad_s=omega,
        # inlet
        r1s_m=r1s, r1h_m=r1h, r1rms_m=r1rms, hub_tip_ratio=nu, M1=M1, C1_m_s=C1, M1s_rel=M1s_rel, W1s_m_s=W1s,
        beta1s_deg=beta1s, beta1rms_deg=beta1rms, beta1h_deg=beta1h, incidence_deg=inc,
        blade_angle_le_s_deg=beta1s - inc, blade_angle_le_rms_deg=beta1rms - inc, blade_angle_le_h_deg=beta1h - inc,
        T1_K=T1, P1_Pa=P1, rho1=rho1,
        # impeller
        n_main=n_main, n_splitter=n_split, splitter_length_frac=split_frac, z_eff=z_eff,
        slip_factor=sigma, work_coefficient=psi, power_input_factor=pif,
        U2_m_s=U2, U2_mcs_m_s=U2_mcs, r2_m=r2, D2_m=D2, b2_m=b2, backsweep_deg=beta2b, phi2=phi2,
        Cm2_m_s=Cm2, Ct2_m_s=Ct2, C2_m_s=C2, W2_m_s=W2, alpha2_deg=alpha2, beta2_flow_deg=beta2_flow,
        M2=M2, M2_rel=M2_rel, T02_K=T02, P02_Pa=P02, T2_K=T2, P2_Pa=P2, rho2=rho2,
        blockage_metal=B_metal, blockage_total=B_total, t_root_m=t_root, t_tip_m=t_tip,
        sigma_root_mcs_Pa=sig_root, sigma_allow_Pa=sig_allow, sigma_allow_nosf_Pa=sig_allow_full,
        tip_clearance_m=clearance, axial_length_m=L_ax, diffusion_ratio=W1s / W2,
        eta_impeller_assumed=eta_imp, diffuser_loss_implied=diffuser_loss_implied,
        # choke
        A1_m2=A1, A_throat_m2=A_throat, W_choke_kg_s=W_choke, choke_margin=choke_margin,
        # efficiency
        phi_global=phi_global, Re_exit=Re, eta_p_est=est["eta_p"], eta_tt_est=eta_tt_est, eta_estimate_parts=est,
        eta_c_assumed=eta_c_assumed, specific_speed=Ns,
        # diffuser
        diffuser_type="vaned" if vaned else "vaneless", r3_m=r3, r4_m=r4, b4_m=b4, n_vanes=n_vanes,
        alpha3_deg=alpha3, M3=M3, C3_m_s=C3, vane_le_angle_deg=vane_le_angle, vane_te_angle_deg=alpha4,
        vane_throat_width_m=throat_w, vane_throat_geometric_m=throat_geometric,
        alpha3_L2_deg=(alpha3_L2 if vaned else None),
        diffuser_throat_mach=float(c("diffuser_throat_mach")), M4=M4, C4_m_s=C4, P4_Pa=P4, alpha4_deg=alpha4,
        n_deswirl=n_deswirl, r_deswirl_inner_m=r_deswirl_in, deswirl_length_m=L_deswirl, A_combustor_inlet_m2=A_comb_in,
        M_combustor_inlet=M_comb, casing_outer_radius_m=r4,
        _rules=rules,
    )
