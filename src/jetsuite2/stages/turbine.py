"""Stage 5 - single-stage axial turbine meanline sizing.

Method (Dixon & Hall ch. 4, Saravanamuttoo ch. 7):

* stage loading psi = dh0/Um^2, flow coefficient phi = Cx/Um and reaction R
  fix the velocity triangles at the mean radius:
      tan a2 = (psi/2 + 1 - R)/phi ,  tan a3 = (psi/2 - 1 + R)/phi ,
      tan b2 = tan a2 - 1/phi ,        tan b3 = tan a3 + 1/phi ;
* Um from the cycle work and psi, r_mean = Um/omega (constant mean radius);
* annulus heights from continuity at NGV exit and rotor exit;
* ``psi: auto`` picks the loading that gives the target rotor-exit hub/tip
  ratio (keeps blades long enough on small engines, short enough on large);
* blade counts from a Zweifel coefficient and the aspect ratios;
* efficiency estimate from a Smith-chart fit with tip-clearance, Reynolds and
  trailing-edge penalties (conceptual);
* blade root stress by the AN^2 relation with a taper factor against the
  material's creep/yield allowable at the rotor metal temperature.
"""
from __future__ import annotations

import math

from scipy.optimize import brentq

from .. import gas
from ..library import materials
from ..rules import check
from .common import inp, out, is_auto, nearest_prime_not_sharing

DEFAULTS = {
    "material": "IN713LC",
    "ngv_material": "IN713LC",
    "psi": "auto",                  # stage loading dh0/Um^2
    "phi": 0.65,                    # flow coefficient Cx/Um
    "reaction": 0.40,
    "hub_tip_ratio_target": 0.62,   # rotor exit, used by psi auto (lower = smaller hub radius = lower disc stress)
    "hub_tip_ratio_min": 0.55,
    "zweifel": 0.85,
    "aspect_ratio_ngv": 1.0,        # h / axial chord
    "aspect_ratio_rotor": 1.4,
    "n_ngv": "auto",
    "n_rotor": "auto",
    "tip_clearance_mm": "auto",     # auto: max(0.25, 0.006*h)
    "te_thickness_mm": 0.6,
    "tmax_over_c_ngv": 0.20,
    "tmax_over_c_rotor": 0.16,
    "taper_factor": 0.6,            # root stress of tapered blade / untapered
    "T_metal_offset_K": 120.0,      # rotor metal temperature below T04 (relative frame + radiation)
    "stress_margin": 1.25,          # allowable / root stress at MCS
    "ngv_loss_coefficient": 0.06,   # Pt loss / exit dynamic head
    "_doc": {
        "material": "rotor (integral wheel) material", "ngv_material": "NGV ring material",
        "psi": "'auto' or stage loading coefficient (1.3-2.4)",
        "phi": "flow coefficient Cx/Um (0.5-0.8)", "reaction": "degree of reaction at mean radius (0.3-0.5)",
        "hub_tip_ratio_target": "rotor-exit hub/tip ratio aimed for by psi auto",
        "hub_tip_ratio_min": "minimum acceptable hub/tip ratio",
        "zweifel": "Zweifel loading coefficient for pitch selection (0.8-1.0)",
        "aspect_ratio_ngv": "NGV height / axial chord", "aspect_ratio_rotor": "rotor height / axial chord",
        "n_ngv": "'auto' or NGV count", "n_rotor": "'auto' or rotor blade count",
        "tip_clearance_mm": "'auto' or rotor tip running clearance [mm]",
        "te_thickness_mm": "trailing-edge thickness (cast) [mm]",
        "tmax_over_c_ngv": "NGV max thickness / chord", "tmax_over_c_rotor": "rotor max thickness / chord",
        "taper_factor": "root stress factor for a tapered blade (0.55-0.7)",
        "T_metal_offset_K": "rotor metal temperature = T04 - offset",
        "stress_margin": "required allowable / stress at MCS",
        "ngv_loss_coefficient": "NGV total-pressure loss coefficient",
    },
}

READS = ["inputs.turbine.*", "outputs.speed.rpm", "outputs.speed.omega_rad_s", "outputs.speed.mcs_factor",
         "outputs.cycle.W4_kg_s", "outputs.cycle.T04_K", "outputs.cycle.Pt4_Pa", "outputs.cycle.Tt5_K",
         "outputs.cycle.Pt5_Pa", "outputs.cycle.far", "outputs.cycle.dh_t_J_kg", "outputs.cycle.eta_t_assumed",
         "outputs.cycle.turbine_PR_tt"]


def smith_eta(psi: float, phi: float) -> float:
    """Approximate Smith (1965) chart total-total efficiency for zero clearance."""
    e = 0.96 - 0.035 * (psi - 1.0) - 0.10 * (phi - 0.6) ** 2 - 0.02 * max(psi - 1.0, 0.0) ** 2
    return min(max(e, 0.80), 0.96)


def triangles(psi, phi, R):
    ta2 = (psi / 2 + 1 - R) / phi
    ta3 = (psi / 2 - 1 + R) / phi
    tb2 = ta2 - 1 / phi
    tb3 = ta3 + 1 / phi
    return (math.degrees(math.atan(ta2)), math.degrees(math.atan(ta3)),
            math.degrees(math.atan(tb2)), math.degrees(math.atan(tb3)))


def run(doc: dict) -> dict:
    t = lambda k: inp(doc, "turbine", k, DEFAULTS[k])  # noqa: E731
    W4, T04, Pt4 = out(doc, "cycle", "W4_kg_s"), out(doc, "cycle", "T04_K"), out(doc, "cycle", "Pt4_Pa")
    Tt5, Pt5, far = out(doc, "cycle", "Tt5_K"), out(doc, "cycle", "Pt5_Pa"), out(doc, "cycle", "far")
    dh_t, eta_t_assumed, PR = out(doc, "cycle", "dh_t_J_kg"), out(doc, "cycle", "eta_t_assumed"), out(doc, "cycle", "turbine_PR_tt")
    rpm, omega, mcs = out(doc, "speed", "rpm"), out(doc, "speed", "omega_rad_s"), out(doc, "speed", "mcs_factor")
    phi, R = float(t("phi")), float(t("reaction"))
    mat = t("material")
    Y_n = float(t("ngv_loss_coefficient"))

    def size(psi):
        Um = math.sqrt(dh_t / psi)
        rm = Um / omega
        a2, a3, b2, b3 = triangles(psi, phi, R)
        Cx = phi * Um
        # NGV exit (station 2 of the stage): total = inlet total minus loss
        C2 = Cx / math.cos(math.radians(a2))
        cp4 = float(gas.cp(T04, far))
        T2 = T04 - C2 ** 2 / (2 * cp4)
        g2 = float(gas.gamma(T2, far))
        # Pt2 = Pt4 - Y (Pt2 - P2) -> iterate
        Pt2 = Pt4
        for _ in range(10):
            P2 = Pt2 * (T2 / T04) ** (g2 / (g2 - 1))
            Pt2n = Pt4 - Y_n * (Pt2 - P2)
            if abs(Pt2n - Pt2) < 1.0:
                Pt2 = Pt2n
                break
            Pt2 = Pt2n
        P2 = Pt2 * (T2 / T04) ** (g2 / (g2 - 1))
        rho2 = P2 / (gas.R_AIR * T2)
        A2 = W4 / (rho2 * Cx)
        h2 = A2 / (2 * math.pi * rm)
        # rotor exit (station 3 = engine station 5)
        C3 = Cx / math.cos(math.radians(a3))
        cp5 = float(gas.cp(Tt5, far))
        T3 = Tt5 - C3 ** 2 / (2 * cp5)
        g3 = float(gas.gamma(T3, far))
        P3 = Pt5 * (T3 / Tt5) ** (g3 / (g3 - 1))
        rho3 = P3 / (gas.R_AIR * T3)
        A3 = W4 / (rho3 * Cx)
        h3 = A3 / (2 * math.pi * rm)
        ht3 = (rm - h3 / 2) / (rm + h3 / 2)
        return dict(Um=Um, rm=rm, a2=a2, a3=a3, b2=b2, b3=b3, Cx=Cx, C2=C2, T2=T2, P2=P2, Pt2=Pt2, rho2=rho2,
                    A2=A2, h2=h2, C3=C3, T3=T3, P3=P3, rho3=rho3, A3=A3, h3=h3, ht3=ht3, g2=g2, g3=g3)

    psi_in = t("psi")
    if is_auto(psi_in):
        target = float(t("hub_tip_ratio_target"))
        f = lambda p: size(p)["ht3"] - target  # noqa: E731
        lo, hi = 1.2, 2.6
        if f(lo) * f(hi) > 0:
            psi = lo if abs(f(lo)) < abs(f(hi)) else hi
        else:
            psi = brentq(f, lo, hi, xtol=1e-4)
        psi_mode = "auto (hub/tip target)"
    else:
        psi, psi_mode = float(psi_in), "user"
    s = size(psi)
    Um, rm = s["Um"], s["rm"]
    h_ngv, h_rot = s["h2"], s["h3"]
    r_tip_ngv, r_hub_ngv = rm + h_ngv / 2, rm - h_ngv / 2
    r_tip_rot, r_hub_rot = rm + h_rot / 2, rm - h_rot / 2
    M2 = s["C2"] / math.sqrt(s["g2"] * gas.R_AIR * s["T2"])
    W2 = s["Cx"] / math.cos(math.radians(s["b2"]))
    M2_rel = W2 / math.sqrt(s["g2"] * gas.R_AIR * s["T2"])
    W3 = s["Cx"] / math.cos(math.radians(s["b3"]))
    M3 = s["C3"] / math.sqrt(s["g3"] * gas.R_AIR * s["T3"])
    M3_rel = W3 / math.sqrt(s["g3"] * gas.R_AIR * s["T3"])

    # ------------------------------------------------------------ blading
    zw = float(t("zweifel"))
    ar_n, ar_r = float(t("aspect_ratio_ngv")), float(t("aspect_ratio_rotor"))
    cx_n, cx_r = h_ngv / ar_n, h_rot / ar_r

    def pitch_over_cx(a_in, a_out):
        ai, ao = math.radians(a_in), math.radians(a_out)
        return zw / (2 * math.cos(ao) ** 2 * (math.tan(ai) + math.tan(ao)))

    # NGV: inlet axial (0), exit a2 ; rotor: inlet b2, exit b3 (angles measured from axial, magnitudes)
    s_n = pitch_over_cx(0.0, s["a2"]) * cx_n
    s_r = pitch_over_cx(abs(s["b2"]), abs(s["b3"])) * cx_r
    n_ngv_in, n_rot_in = t("n_ngv"), t("n_rotor")
    n_ngv = int(round(2 * math.pi * rm / s_n)) if is_auto(n_ngv_in) else int(n_ngv_in)
    n_rot_est = int(round(2 * math.pi * rm / s_r))
    n_rot = nearest_prime_not_sharing(n_rot_est, [n_ngv], lo=max(n_rot_est - 6, 9), hi=n_rot_est + 6) if is_auto(n_rot_in) else int(n_rot_in)
    s_n, s_r = 2 * math.pi * rm / n_ngv, 2 * math.pi * rm / n_rot
    stagger_n = 0.5 * (0.0 + s["a2"])
    stagger_r = 0.5 * (s["b2"] + s["b3"])
    c_n, c_r = cx_n / math.cos(math.radians(stagger_n)), cx_r / math.cos(math.radians(stagger_r))
    o_n = s_n * math.cos(math.radians(s["a2"]))
    o_r = s_r * math.cos(math.radians(s["b3"]))
    te = float(t("te_thickness_mm")) * 1e-3
    clr_in = t("tip_clearance_mm")
    clearance = (max(0.25, 0.006 * h_rot * 1e3) if is_auto(clr_in) else float(clr_in)) * 1e-3

    # ------------------------------------------------------------ efficiency
    eta0 = smith_eta(psi, phi)
    d_clr = 2.0 * clearance / h_rot * 0.5      # unshrouded: ~1 point per 1 % clearance/height (Dixon), halved for reaction 0.4
    mu = 1.458e-6 * s["T2"] ** 1.5 / (s["T2"] + 110.4)
    Re = s["rho2"] * s["C2"] * c_n / mu
    re_corr = (2e5 / max(Re, 2e4)) ** 0.2
    d_re = 0.02 * (re_corr - 1.0) if Re < 2e5 else 0.0
    d_te = 0.5 * (te / o_r)                    # TE blockage penalty on the rotor throat
    eta_tt_est = min(max(eta0 - d_clr - d_re - d_te, 0.6), 0.95)

    # ------------------------------------------------------------- stress
    rho_b = materials.get(mat)["rho"]
    k_taper = float(t("taper_factor"))
    omega_mcs = omega * mcs
    A_ann = math.pi * (r_tip_rot ** 2 - r_hub_rot ** 2)
    sigma_root = k_taper * rho_b * omega_mcs ** 2 * (r_tip_rot ** 2 - r_hub_rot ** 2) / 2
    AN2 = A_ann * (rpm * mcs) ** 2
    T_metal = T04 - float(t("T_metal_offset_K"))
    # relative total temperature at rotor inlet is the true driver; report it too
    cp2 = float(gas.cp(s["T2"], far))
    T_rel_in = s["T2"] + W2 ** 2 / (2 * cp2)
    sig_allow = materials.allowable_at(mat, T_metal)
    sm = float(t("stress_margin"))
    T_max_mat = materials.get(mat)["T_max"]
    ngv_mat = t("ngv_material")
    T_max_ngv = materials.get(ngv_mat)["T_max"]

    ht_min = float(t("hub_tip_ratio_min"))
    rules = [
        check("TURB-1", "stage loading psi", psi, 2.4, "max", "Smith chart: efficiency falls fast above ~2.2", hard=False,
              note="raise rpm (larger Um) or accept lower efficiency"),
        check("TURB-2", "stage loading psi minimum", psi, 1.2, "min", "below ~1.2 the annulus becomes very short", hard=False),
        check("TURB-3", "rotor-exit hub/tip ratio", s["ht3"], ht_min, "min", "practice 0.6-0.85 for a single stage",
              note="too long blades: raise psi target or rpm"),
        check("TURB-4", "rotor-exit hub/tip ratio upper", s["ht3"], 0.88, "max", "very short blades: clearance losses", hard=False),
        check("TURB-5", "blade root stress at MCS x margin vs allowable", sigma_root * sm / 1e6, sig_allow / 1e6, "max",
              f"{mat} min(yield, creep) at {T_metal:.0f} K; margin {sm}", unit="MPa",
              note="lower rpm, shorter blades (higher psi/hub-tip), stronger material or lower T04"),
        check("TURB-6", "rotor metal temperature vs material limit", T_metal, T_max_mat, "max", f"{mat} T_max", unit="K"),
        check("TURB-7", "NGV metal temperature vs material limit", T04, T_max_ngv, "max", f"{ngv_mat} T_max", unit="K",
              note="NGV sees T04 directly; use a higher-temperature alloy or lower T04"),
        check("TURB-8", "NGV exit Mach", M2, 1.05, "max", "subsonic/transonic NGV practice", hard=False),
        check("TURB-9", "rotor exit absolute Mach", M3, 0.60, "max", "jet-pipe entry Mach; boomsonic R7.1 annulus cap", hard=False),
        check("TURB-10", "estimated vs assumed turbine efficiency |diff|", abs(eta_tt_est - eta_t_assumed), 0.03, "max",
              "consistency: run `jet converge`", note=f"estimate {eta_tt_est:.3f} vs cycle assumption {eta_t_assumed:.3f}"),
        check("TURB-11", "AN2 (rotor annulus x rpm^2) at MCS", AN2, 4.5e7, "max",
              "uncooled cast wheels: JetCat/AMT class 2-3.5e7, ceiling ~4.5e7 m2 rpm2", unit="m2rpm2", hard=False),
        check("TURB-12", "turbine tip diameter (info)", 2 * r_tip_rot * 1e3, None, "info", "-", unit="mm"),
    ]
    return dict(
        material=mat, ngv_material=ngv_mat, rpm=rpm, psi=psi, psi_mode=psi_mode, phi=phi, reaction=R,
        Um_m_s=Um, r_mean_m=rm, Cx_m_s=s["Cx"],
        alpha2_deg=s["a2"], alpha3_deg=s["a3"], beta2_deg=s["b2"], beta3_deg=s["b3"],
        C2_m_s=s["C2"], W2_m_s=W2, C3_m_s=s["C3"], W3_m_s=W3, M2=M2, M2_rel=M2_rel, M3=M3, M3_rel=M3_rel,
        T2_K=s["T2"], P2_Pa=s["P2"], Pt2_Pa=s["Pt2"], T3_K=s["T3"], P3_Pa=s["P3"], T_rel_in_K=T_rel_in,
        h_ngv_m=h_ngv, h_rotor_m=h_rot, r_tip_ngv_m=r_tip_ngv, r_hub_ngv_m=r_hub_ngv,
        r_tip_rotor_m=r_tip_rot, r_hub_rotor_m=r_hub_rot, hub_tip_ratio_exit=s["ht3"], A_exit_m2=s["A3"], A_ngv_exit_m2=s["A2"],
        n_ngv=n_ngv, n_rotor=n_rot, pitch_ngv_m=s_n, pitch_rotor_m=s_r, cx_ngv_m=cx_n, cx_rotor_m=cx_r,
        chord_ngv_m=c_n, chord_rotor_m=c_r, stagger_ngv_deg=stagger_n, stagger_rotor_deg=stagger_r,
        throat_ngv_m=o_n, throat_rotor_m=o_r, te_thickness_m=te, tip_clearance_m=clearance,
        tmax_over_c_ngv=float(t("tmax_over_c_ngv")), tmax_over_c_rotor=float(t("tmax_over_c_rotor")),
        zweifel=zw, eta_tt_est=eta_tt_est, eta_smith=eta0, eta_penalties=dict(clearance=d_clr, reynolds=d_re, te=d_te),
        eta_t_assumed=eta_t_assumed, Re_chord=Re, PR_tt=PR,
        sigma_root_mcs_Pa=sigma_root, sigma_allow_Pa=sig_allow, AN2_m2rpm2=AN2, T_metal_K=T_metal,
        _rules=rules,
    )
