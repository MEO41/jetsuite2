"""Analysis stage - component quality assessment (L1/L2): "is this impeller
actually any good?"

Scores each design choice against aerodynamic practice (target ranges from
Balje, Japikse, Aungier, Dixon & Hall, Rodgers, Smith, Zweifel) rather than
against failure limits.  Every item carries the value, the target band, a
0-1 score and the named consequence of being outside it.

Compressor: Balje (Cordier) placement with the achievable-efficiency band,
slip by four methods with the disagreement surfaced, de Haller and diffusion
ratio, blade loading, inducer incidence across the running line, diffuser
vaneless-space and vane-throat analysis with a two-zone (Japikse) exit-mixing
estimate, and a backsweep trade study run through the sizing chain.
Turbine: Smith-chart placement, Zweifel, hub reaction, exit swirl, trailing
edge blockage, nozzle-throat coupling.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from .. import gas
from ..library import materials
from ..perf import closs
from ..rules import check
from .common import inp, out
from . import compressor as comp_stage

TIER = "L2"
CORE = False

DEFAULTS = {
    "backsweep_sweep_deg": [10, 15, 20, 25, 30, 35, 40, 45],
    "two_zone_wake_fraction": 0.20,
    "two_zone_secondary_mass_fraction": 0.12,
    "_doc": {"backsweep_sweep_deg": "backsweep values for the trade study", "two_zone_wake_fraction": "Japikse two-zone: area fraction of the wake at the impeller exit",
             "two_zone_secondary_mass_fraction": "Japikse two-zone: mass fraction in the secondary (wake) zone"},
}

READS = ["inputs.assess.*", "inputs.compressor.*", "outputs.compressor.*", "outputs.turbine.*", "outputs.cycle.*",
         "outputs.speed.*", "outputs.maps.design_point", "outputs.maps.compressor_map", "outputs.offdesign.running_line"]


def _score(value, lo, hi, soft=None):
    """1 inside [lo, hi]; linear decay to 0 over one band-width (or `soft`) outside."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    width = soft if soft else max(hi - lo, 1e-9)
    if lo <= value <= hi:
        return 1.0
    d = (lo - value) if value < lo else (value - hi)
    return float(max(0.0, 1.0 - d / width))


def item(id_, name, value, lo, hi, consequence, unit="", soft=None, tier="L1", source=""):
    return dict(id=id_, name=name, value=value, target=[lo, hi], score=_score(value, lo, hi, soft), consequence=consequence,
                unit=unit, tier=tier, source=source)


def balje_eta(Ns: float) -> float:
    """Achievable total-total efficiency of a radial compressor stage vs dimensionless specific
    speed (Balje 1981 chart, fitted: peak ~0.86 at Ns ~0.7)."""
    return float(max(0.60, 0.86 - 0.35 * (math.log10(max(Ns, 1e-3) / 0.7)) ** 2))


def run(doc: dict) -> dict:
    a = lambda k: inp(doc, "assess", k, DEFAULTS[k])  # noqa: E731
    c, t, cy, sp = out(doc, "compressor"), out(doc, "turbine"), out(doc, "cycle"), out(doc, "speed")
    mp = doc["outputs"].get("maps", {})
    dp = mp.get("design_point", {})
    rl = doc["outputs"].get("offdesign", {}).get("running_line")
    items = []
    # ------------------------------------------------------------- Balje / Cordier
    rho01 = cy["Pt2_Pa"] / (gas.R_AIR * cy["Tt2_K"])
    Q1 = cy["W_kg_s"] / rho01
    dh0s = gas.h(gas.isentropic_T(cy["Tt2_K"], cy["OPR"])) - gas.h(cy["Tt2_K"])
    omega = sp["omega_rad_s"]
    Ns = omega * math.sqrt(Q1) / dh0s ** 0.75
    Ds = c["D2_m"] * dh0s ** 0.25 / math.sqrt(Q1)
    eta_balje = balje_eta(Ns)
    items.append(item("AQ-C1", "specific speed Ns (Balje, dimensionless)", Ns, 0.5, 0.9,
                      "outside the radial-stage sweet spot the achievable efficiency falls; low Ns = narrow exit, high Ns = mixed-flow territory",
                      source="Balje 1981 Ns-Ds diagram"))
    items.append(item("AQ-C2", "specific diameter Ds", Ds, 3.5, 5.5, "Cordier line: Ns*Ds ~ 2-2.5 for radial compressors", source="Balje"))
    items.append(item("AQ-C3", "Ns*Ds (Cordier)", Ns * Ds, 1.8, 2.8, "off the Cordier line the impeller is over- or under-sized for its duty", source="Cordier"))
    items.append(item("AQ-C4", "L1 efficiency estimate vs Balje achievable band", c["eta_tt_est"] - eta_balje, -0.04, 0.02,
                      f"achievable ~{eta_balje:.3f} at this Ns; a higher claim needs justification, a lower one leaves performance on the table",
                      source="Balje chart fit"))
    # ------------------------------------------------------------- slip factor by method
    g = closs.CompressorGeometry.from_outputs(c)
    slips = {m: closs.slip_factor(g, m, c["phi2"]) for m in ("wiesner", "stanitz", "stodola", "busemann")}
    spread = max(slips.values()) - min(slips.values())
    items.append(item("AQ-C5", "slip factor disagreement between methods (max-min)", spread, 0.0, 0.03,
                      "each 0.01 of slip is ~1 % of work: a 3 % spread is a 3 % pressure-ratio uncertainty until CFD/test settles it",
                      source="Wiesner 1967, Stanitz 1952, Stodola, Busemann/Wiesner limit"))
    # ------------------------------------------------------------- loading
    de_haller = dp.get("de_haller") if dp else None
    items.append(item("AQ-C6", "de Haller number W2/W1rms", de_haller, 0.65, 0.85,
                      "below ~0.65 the inducer-to-exit deceleration separates the suction surface", source="de Haller; Rodgers", tier="L2"))
    items.append(item("AQ-C7", "diffusion ratio W1s/W2", c["diffusion_ratio"], 1.4, 1.9,
                      "above ~1.9 the shroud-side flow stalls (Dixon); below 1.4 the impeller is lightly loaded (heavy)", source="Dixon & Hall 7.x"))
    items.append(item("AQ-C8", "Coppage diffusion factor D_f", dp.get("D_f") if dp else None, 0.35, 0.62,
                      "blade-to-blade loading: above 0.6 the blade-loading loss and wake grow rapidly", source="Coppage / Oh 1997", tier="L2"))
    items.append(item("AQ-C9", "work coefficient psi = dh/U2^2 (Euler)", c["work_coefficient"], 0.55, 0.72,
                      "high psi = radial blades and wide operating-range penalty; low psi = tip speed used inefficiently", source="Aungier"))
    items.append(item("AQ-C10", "inducer shroud relative Mach", c["M1s_rel"], 0.9, 1.25,
                      "above ~1.25 shock losses and choke margin erode; below 0.9 the inducer is larger than it needs to be", source="Rodgers; fleet band"))
    items.append(item("AQ-C11", "exit width ratio b2/D2", c["b2_m"] / c["D2_m"], 0.04, 0.09,
                      "narrow exits lose efficiency to clearance and friction; wide exits promote exit-flow separation", source="Rodgers"))
    # ------------------------------------------------------------- inducer incidence across the running line
    inc_range = None
    if rl:
        incs = []
        for p in rl:
            if not p.get("converged"):
                continue
            T01 = cy["Tt2_K"]; P01 = cy["Pt2_Pa"]
            r = closs.evaluate(g, p["W"], p["N_rpm"] * 2 * math.pi / 60, T01, P01)
            if r.ok:
                incs.append((p["N_frac"], r.incidence, r.incidence_vd))
        if incs:
            inc_range = dict(N=[x[0] for x in incs], inducer=[x[1] for x in incs], diffuser=[x[2] for x in incs])
            items.append(item("AQ-C12", "inducer incidence range along the running line (max - min)", max(x[1] for x in incs) - min(x[1] for x in incs),
                              0.0, 10.0, "a wide incidence swing means the inlet metal angle cannot suit both idle and max power", unit="deg",
                              source="perf.closs along outputs.offdesign", tier="L2"))
            items.append(item("AQ-C13", "vaned-diffuser incidence at the lowest converged speed", incs[0][2], -6.0, 5.0,
                              "large positive incidence at low speed = diffuser stall = low-speed surge", unit="deg", source="Japikse", tier="L2"))
    # ------------------------------------------------------------- diffuser
    items.append(item("AQ-D1", "vaneless gap r3/r2", c["r3_m"] / c["r2_m"], 1.05, 1.15,
                      "too small: impeller/vane interaction, noise, forced response; too large: friction loss", source="Japikse"))
    if c["diffuser_type"] == "vaned":
        thr_ratio = c["vane_throat_width_m"] / c["vane_throat_geometric_m"] if c.get("vane_throat_geometric_m") else None
        items.append(item("AQ-D2", "vane throat / (pitch cos alpha3) at design", thr_ratio, 0.95, 1.15,
                          "a throat smaller than the free-stream opening chokes; much larger means the vane LE is not aligned with the flow",
                          source="Japikse; throat sized for M 0.70"))
        items.append(item("AQ-D3", "vane leading-edge incidence at design (L2 swirl)", dp.get("incidence_vd") if dp else None, -4.0, 2.0,
                          "positive incidence eats the stall margin, negative the choke margin", unit="deg", source="Japikse", tier="L2"))
        items.append(item("AQ-D4", "diffuser inlet Mach (vaneless exit)", dp.get("M3") if dp else None, 0.5, 0.95,
                          "transonic vane inlets are loss- and range-sensitive", source="Japikse", tier="L2"))
    items.append(item("AQ-D5", "vaneless-space swirl angle alpha3", dp.get("alpha3") if dp else c["alpha3_deg"], 60.0, 74.0,
                      "above ~75-78 deg the vaneless space itself stalls (Senoo); below 60 the impeller exit is heavily blocked", unit="deg",
                      source="Senoo 1977", tier="L2"))
    # two-zone (Japikse) exit mixing: momentum balance between primary and secondary zones
    eps = float(a("two_zone_wake_fraction")); chi = float(a("two_zone_secondary_mass_fraction"))
    Cm2 = c["Cm2_m_s"]; Ct2 = c["Ct2_m_s"]
    # primary zone carries (1-chi) of the mass in (1-eps) of the area, secondary chi in eps
    Cm_p = Cm2 * (1 - chi) / (1 - eps); Cm_s = Cm2 * chi / eps
    Cm_mix = Cm2
    dp_mix = c["rho2"] * ((1 - eps) * Cm_p ** 2 + eps * Cm_s ** 2 - Cm_mix ** 2)   # momentum recovered as static pressure
    q2 = 0.5 * c["rho2"] * c["C2_m_s"] ** 2
    loss_mix = 0.5 * c["rho2"] * ((1 - chi) * Cm_p ** 2 + chi * Cm_s ** 2 - Cm_mix ** 2) - dp_mix  # kinetic energy not recovered
    items.append(item("AQ-D6", "two-zone exit mixing loss / impeller exit dynamic head", loss_mix / q2, 0.0, 0.03,
                      "wake/jet mixing before the vanes; grows with wake fraction (loading, clearance, low Re)", source="Japikse 1996 two-zone (eps, chi inputs)"))
    # ------------------------------------------------------------- backsweep trade study
    bs = []
    T01, P01 = cy["Tt2_K"], cy["Pt2_Pa"]
    for b in a("backsweep_sweep_deg"):
        d2 = copy.deepcopy(doc)
        d2["inputs"]["compressor"]["backsweep_deg"] = float(b)
        try:
            o2 = comp_stage.run(d2)
        except Exception as ex:  # noqa: BLE001
            bs.append(dict(backsweep=b, ok=False, reason=str(ex)))
            continue
        g2 = closs.CompressorGeometry.from_outputs(o2)
        sl = closs.speedline(g2, omega, T01, P01, n_pts=14)
        r2 = closs.evaluate(g2, cy["W_kg_s"], omega, T01, P01)
        SM = None
        if sl.get("ok") and r2.ok:
            from ..perf.maps import corr_flow
            SM = (float(np.interp(sl["surge_W"], sl["W"][::-1], sl["PR"][::-1])) * cy["W_kg_s"]) / (r2.PR_tt * sl["surge_W"]) - 1.0 \
                if sl["surge_W"] < cy["W_kg_s"] else -(cy["W_kg_s"] / sl["surge_W"] - 1.0)
        sig_allow = o2["sigma_allow_Pa"]
        bs.append(dict(backsweep=b, ok=True, U2=o2["U2_m_s"], r2_mm=o2["r2_m"] * 1e3, t_root_mm=o2["t_root_m"] * 1e3,
                       eta_L1=o2["eta_tt_est"], eta_L2=(r2.eta_tt if r2.ok else None), PR_L2=(r2.PR_tt if r2.ok else None),
                       SM=SM, choke_margin=o2["choke_margin"], diffusion_ratio=o2["diffusion_ratio"],
                       root_stress_frac=o2["sigma_root_mcs_Pa"] / sig_allow, work_coefficient=o2["work_coefficient"]))
    # ------------------------------------------------------------- turbine
    from .turbine import smith_eta
    items.append(item("AQ-T1", "Smith-chart placement: efficiency contour at (psi, phi)", smith_eta(t["psi"], t["phi"]), 0.90, 0.96,
                      "loading/flow coefficient combination away from the 0.9+ island costs stage efficiency directly", source="Smith 1965"))
    items.append(item("AQ-T2", "stage loading psi", t["psi"], 1.3, 2.0, "above 2 the rotor turning and losses grow; below 1.3 the annulus is short", source="Dixon"))
    items.append(item("AQ-T3", "flow coefficient phi", t["phi"], 0.5, 0.8, "outside 0.5-0.8 the velocity triangles skew and secondary losses rise", source="Smith"))
    # actual Zweifel from the chosen pitch and angles
    def zweifel(a_in, a_out, s, cx):
        ai, ao = math.radians(a_in), math.radians(a_out)
        return 2 * s / cx * math.cos(ao) ** 2 * (math.tan(ai) + math.tan(ao))
    zw_r = zweifel(abs(t["beta2_deg"]), abs(t["beta3_deg"]), t["pitch_rotor_m"], t["cx_rotor_m"])
    zw_n = zweifel(0.0, t["alpha2_deg"], t["pitch_ngv_m"], t["cx_ngv_m"])
    items.append(item("AQ-T4", "rotor Zweifel coefficient (actual)", zw_r, 0.75, 1.05, "too many blades = friction/blockage; too few = separation on the suction side", source="Zweifel 1945"))
    items.append(item("AQ-T5", "NGV Zweifel coefficient (actual)", zw_n, 0.75, 1.05, "as above for the nozzle row", source="Zweifel"))
    R_hub = 1 - (1 - t["reaction"]) * (t["r_mean_m"] / t["r_hub_rotor_m"]) ** 2
    items.append(item("AQ-T6", "hub reaction (free vortex)", R_hub, 0.05, 0.5, "negative hub reaction = hub-section diffusion in the rotor = separation", source="Dixon 4.x"))
    items.append(item("AQ-T7", "exit swirl |alpha3|", abs(t["alpha3_deg"]), 0.0, 20.0, "exit swirl is lost kinetic energy in the jet pipe and loads the tail cone", unit="deg", source="practice"))
    items.append(item("AQ-T8", "rotor trailing-edge blockage t_te/o", t["te_thickness_m"] / t["throat_rotor_m"], 0.0, 0.10,
                      "thick trailing edges on small blades: mixing loss ~ 0.5 (t/o) of the exit head", source="Ainley-Mathieson"))
    items.append(item("AQ-T9", "rotor-exit Mach", t["M3"], 0.25, 0.55, "high exit Mach wastes turbine work in the jet pipe; the nozzle then dominates the running line", source="practice"))
    items.append(item("AQ-T10", "nozzle throat / turbine exit annulus area", cy["A8_geo_m2"] / t["A_exit_m2"], 0.45, 0.85,
                      "small ratio = high turbine exit Mach and a running line pushed toward surge; large = unchoked nozzle, thrust-lapse sensitive", source="matching practice"))
    items.append(item("AQ-T11", "rotor hub/tip ratio", t["hub_tip_ratio_exit"], 0.58, 0.85, "long blades: stress and tip-clearance sensitivity; short: clearance losses", source="practice"))
    # ------------------------------------------------------------- summary scores
    def avg(prefix):
        s = [i["score"] for i in items if i["id"].startswith(prefix) and i["score"] is not None]
        return float(np.mean(s)) if s else None
    scores = dict(compressor=avg("AQ-C"), diffuser=avg("AQ-D"), turbine=avg("AQ-T"))
    worst_items = sorted([i for i in items if i["score"] is not None], key=lambda i: i["score"])[:5]
    rules = [
        check("ASS-1", "compressor quality score (mean of items)", scores["compressor"], 0.75, "min", "assessment items AQ-C*", hard=False,
              note="; ".join(f"{i['id']} {i['name']} = {i['value']:.3g}" for i in worst_items if i["id"].startswith("AQ-C"))),
        check("ASS-2", "diffuser quality score", scores["diffuser"], 0.75, "min", "AQ-D*", hard=False),
        check("ASS-3", "turbine quality score", scores["turbine"], 0.75, "min", "AQ-T*", hard=False,
              note="; ".join(f"{i['id']} {i['name']} = {i['value']:.3g}" for i in worst_items if i["id"].startswith("AQ-T"))),
    ]
    return dict(items=items, scores=scores, balje=dict(Ns=Ns, Ds=Ds, eta_achievable=eta_balje), slip=slips,
                two_zone=dict(wake_fraction=eps, secondary_mass_fraction=chi, mixing_loss_over_q2=loss_mix / q2),
                incidence_along_running_line=inc_range, backsweep_trade=bs, _rules=rules)
