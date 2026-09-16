"""Analysis stage - manufacturability and build realism (L1).

* Tolerance stack-up through the rotating assembly (worst-case and RSS):
  impeller tip clearance and turbine tip clearance chains, bearing fits,
  axial float, and the resulting clearance range with its efficiency effect
  (0.3 x d(clearance)/b2 for the impeller, 2 x d(clearance)/h for the turbine).
* Balance grade requirement (ISO 1940/21940): permissible residual unbalance
  per plane for the chosen grade at the design speed, and what a two-plane
  balancing machine of a given resolution can achieve.
* Machinability of the impeller (5-axis flank/point milling): minimum passage
  width between blades along the meridional path vs the smallest usable
  cutter, blade wrap and overlap in the axial view (flank-milling reach), hub
  fillet radius vs blade root thickness, minimum thickness vs cutter deflection;
  turbine: cast-only features (fillets, trailing-edge thickness, blade count
  vs core spacing).
* Material / process selection with the associated allowable knock-downs and
  surface finish (billet-machined, investment cast, additively manufactured).
* Bill of materials with representative catalogue part numbers, unit cost
  and lead time from the library's cost tables.
"""
from __future__ import annotations

import math

import numpy as np

from ..library import components, materials
from ..rules import check
from .common import inp, out

TIER = "L1"
CORE = False

PROCESSES = {
    "billet-5axis": dict(allowable_factor=1.00, Ra_um=0.8, min_fillet_mm=0.5, min_thickness_mm=0.5, cost_factor=1.0,
                         note="5-axis milled from forged/rolled billet: full handbook allowables"),
    "investment-cast": dict(allowable_factor=0.85, Ra_um=3.2, min_fillet_mm=0.8, min_thickness_mm=0.8, cost_factor=0.6,
                            note="cast: porosity/grain knock-down 15 %, HIP recommended"),
    "AM-LPBF": dict(allowable_factor=0.80, Ra_um=8.0, min_fillet_mm=0.4, min_thickness_mm=0.4, cost_factor=0.8,
                    note="laser powder bed: as-built surface, HIP + machining of fits required, fatigue knock-down 20 %"),
}

COST_TABLE = {  # representative unit costs [EUR] and lead times [weeks]; catalogue-class hardware
    "impeller": (900, 6), "turbine_wheel": (1400, 10), "ngv_ring": (700, 8), "outer_casing": (250, 3), "inlet_shroud": (300, 3),
    "diffuser": (450, 4), "combustor_liners": (350, 4), "shaft": (200, 3), "housings_tunnel": (350, 4), "nozzle_tailcone": (180, 3),
    "inner_casing": (120, 3), "turbine_shroud": (90, 2), "bearings": (180, 2), "igniter": (12, 1), "egt_probe": (45, 1),
    "screws": (15, 1), "retaining_rings": (4, 1), "locknuts": (25, 1), "o_ring": (2, 1), "vaporisers": (120, 3),
}

PART_NUMBERS = {  # representative real part-number patterns for the catalogue items
    "bearing": {"71900C-HC": "SKF 71900 CD/HCP4A", "71901C-HC": "SKF 71901 CD/HCP4A", "71902C-HC": "SKF 71902 CD/HCP4A",
                "71903C-HC": "SKF 71903 CD/HCP4A", "71904C-HC": "SKF 71904 CD/HCP4A", "7000C-HC": "SKF 7000 CD/HCP4A",
                "7001C-HC": "SKF 7001 CD/HCP4A", "7002C-HC": "SKF 7002 CD/HCP4A", "7003C-HC": "SKF 7003 CD/HCP4A",
                "708C-HC": "GMN S 608 C TA HC", "719/8-HC": "GMN S 619/8 C TA HC", "707C-HC": "GMN S 607 C TA HC"},
    "glow-1/4-32": "OS Engines No. 8 (1/4-32)", "EGT-K-M8": "RS PRO K-type M8 probe 3 mm x 25 mm",
}

DEFAULTS = {
    "impeller_process": "billet-5axis",
    "turbine_process": "investment-cast",
    "balance_grade_G": 2.5,
    "balancer_resolution_gmm": 0.05,
    "min_cutter_d_mm": 3.0,
    "hub_fillet_mm": 1.0,
    "tolerances_mm": {"impeller_axial_position": 0.03, "shroud_contour": 0.03, "front_housing_seat": 0.02,
                      "bearing_axial_float": 0.05, "shaft_shoulder": 0.02, "turbine_axial_position": 0.03,
                      "turbine_shroud_bore": 0.03, "casing_stack": 0.05, "thermal_growth_turbine_shroud": 0.06,
                      "thermal_growth_impeller": 0.02},
    "_doc": {"impeller_process": "billet-5axis | investment-cast | AM-LPBF", "turbine_process": "as above",
             "balance_grade_G": "ISO 21940 grade", "balancer_resolution_gmm": "achievable residual per plane [g mm]",
             "min_cutter_d_mm": "smallest usable ball/taper cutter diameter for the impeller passages",
             "hub_fillet_mm": "blade-root fillet radius", "tolerances_mm": "+/- tolerances of the stack-up contributors"},
}

READS = ["inputs.manufacturing.*", "outputs.compressor.*", "outputs.turbine.*", "outputs.rotor.*", "outputs.geometry.*",
         "outputs.speed.*", "outputs.layout.*"]


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "manufacturing", k, DEFAULTS[k])  # noqa: E731
    c, t, ro, ge, sp = out(doc, "compressor"), out(doc, "turbine"), out(doc, "rotor"), out(doc, "geometry"), out(doc, "speed")
    tol = dict(DEFAULTS["tolerances_mm"]); tol.update(g("tolerances_mm") or {})
    # ---------------------------------------------------------------- tolerance stack-up (axial tip clearance chains)
    chain_imp = ["impeller_axial_position", "shroud_contour", "front_housing_seat", "bearing_axial_float", "shaft_shoulder", "thermal_growth_impeller"]
    chain_tur = ["turbine_axial_position", "turbine_shroud_bore", "bearing_axial_float", "shaft_shoulder", "casing_stack", "thermal_growth_turbine_shroud"]
    def stack(chain):
        wc = sum(tol[k] for k in chain)
        rss = math.sqrt(sum(tol[k] ** 2 for k in chain))
        return wc, rss
    wc_i, rss_i = stack(chain_imp)
    wc_t, rss_t = stack(chain_tur)
    clr_i, clr_t = c["tip_clearance_m"] * 1e3, t["tip_clearance_m"] * 1e3
    b2_mm, h_mm = c["b2_m"] * 1e3, t["h_rotor_m"] * 1e3
    d_eta_i = 0.3 * rss_i / b2_mm          # Pampreen-type clearance sensitivity (from the L1 estimate)
    d_eta_t = 2.0 * rss_t / h_mm * 0.5
    rub_i = clr_i - wc_i                   # remaining clearance in the worst case
    rub_t = clr_t - wc_t
    # ---------------------------------------------------------------- balance
    G = float(g("balance_grade_G"))
    omega = sp["omega_rad_s"]
    m_rot = ro["m_impeller_kg"] + ro["m_turbine_kg"] + 0.3
    e_per = G * 1e-3 / omega                                  # m
    U_per_total = m_rot * e_per * 1e6                         # g mm
    U_per_plane = U_per_total / 2
    resol = float(g("balancer_resolution_gmm"))
    # ---------------------------------------------------------------- impeller machinability
    proc_i = PROCESSES[str(g("impeller_process"))]; proc_t = PROCESSES[str(g("turbine_process"))]
    n_pass = int(c["n_main"] + c["n_splitter"])
    # passage width at the exit (between adjacent blades including splitters) and at the inducer (main blades only)
    w_exit = 2 * math.pi * c["r2_m"] / n_pass * math.cos(math.radians(c["backsweep_deg"])) - c["t_tip_m"]
    r1rms = c["r1rms_m"]
    w_inducer = 2 * math.pi * r1rms / c["n_main"] * math.cos(math.radians(c["blade_angle_le_rms_deg"])) - 0.5 * c["t_tip_m"]
    # hub passage near the splitter LE (splitter starts at s ~ 0.4): radius ~ r1rms + 0.4 (r2 - r1rms), all blades
    r_sp = r1rms + (1 - c["splitter_length_frac"]) * (c["r2_m"] - r1rms)
    beta_sp = 0.5 * (c["blade_angle_le_rms_deg"] + c["backsweep_deg"])
    w_split = 2 * math.pi * r_sp / n_pass * math.cos(math.radians(beta_sp)) - 0.5 * (c["t_root_m"] + c["t_tip_m"])
    w_min = min(w_exit, w_inducer, w_split) * 1e3
    d_cut = float(g("min_cutter_d_mm"))
    # blade wrap and overlap: axial-view overlap of adjacent blades prevents point milling from the front
    wrap_deg = 0.0
    try:
        from ..cad.impeller import camber_grids
        sheet = ge["sheet"]["impeller"]
        sh = dict(sheet); sh["splitter_start"] = 1.0 - sheet["splitter_length_frac"]
        _, _, th = camber_grids(sh, n_span=3, n_chord=21)
        wrap_deg = math.degrees(th)
    except Exception:  # noqa: BLE001
        wrap_deg = float("nan")
    pitch_deg = 360.0 / c["n_main"]
    overlap = wrap_deg / pitch_deg if wrap_deg == wrap_deg else None      # > 1: blades overlap in the axial view (5-axis only)
    fillet = float(g("hub_fillet_mm"))
    fillet_ok = fillet >= proc_i["min_fillet_mm"] and fillet <= 0.6 * c["t_root_m"] * 1e3
    t_min = c["t_tip_m"] * 1e3
    flags = []
    if w_min < d_cut:
        flags.append(f"passage width {w_min:.2f} mm < cutter {d_cut:.1f} mm: reduce blade count or use a smaller cutter")
    if overlap and overlap > 1.6:
        flags.append(f"blade overlap {overlap:.2f} pitches: deep wrap, cutter reach and chatter risk (5-axis flank milling)")
    if t_min < proc_i["min_thickness_mm"]:
        flags.append(f"tip thickness {t_min:.2f} mm below the process minimum {proc_i['min_thickness_mm']} mm")
    if not fillet_ok:
        flags.append("hub fillet outside 0.5 mm .. 0.6 x root thickness")
    # turbine casting features
    te_t = t["te_thickness_m"] * 1e3
    pitch_hub = 2 * math.pi * t["r_hub_rotor_m"] / t["n_rotor"] * 1e3
    t_flags = []
    if te_t < proc_t["min_thickness_mm"] * 0.7:
        t_flags.append(f"trailing edge {te_t:.2f} mm too thin to cast reliably")
    if pitch_hub < 4.0:
        t_flags.append(f"hub pitch {pitch_hub:.1f} mm: ceramic-core spacing marginal")
    # ---------------------------------------------------------------- material / process allowables
    allow_i = materials.yield_at(c["material"], c["T02_K"]) * proc_i["allowable_factor"]
    allow_t = materials.allowable_at(t["material"], t["T_metal_K"]) * proc_t["allowable_factor"]
    # ---------------------------------------------------------------- BOM
    brg = ro["bearing"]
    sheet = ge["sheet"]
    bom = []
    def add(item, qty, material="", pn="", key=None):
        cost, lead = COST_TABLE.get(key or item, (0, 0))
        bom.append(dict(item=item, qty=qty, material=material, part_number=pn, unit_cost_EUR=cost, lead_weeks=lead, line_cost_EUR=cost * qty))
    add("impeller", 1, c["material"], f"{g('impeller_process')}", "impeller")
    add("turbine_wheel", 1, t["material"], f"{g('turbine_process')}", "turbine_wheel")
    add("ngv_ring", 1, t["ngv_material"], "investment cast", "ngv_ring")
    for p in ("inlet_shroud", "diffuser", "outer_casing", "combustor_liners", "inner_casing", "shaft", "housings_tunnel", "nozzle_tailcone", "turbine_shroud", "vaporisers"):
        add(p, 1, ge["mass"].get(p, {}).get("material", ""), "machined / sheet", p)
    add("bearings", 2, "hybrid ceramic", PART_NUMBERS["bearing"].get(brg["id"], brg["id"]), "bearings")
    add("retaining_rings", 2, "spring steel", f"{sheet['shaft']['retaining_ring']} / {sheet['bearings']['internal_ring']}", "retaining_rings")
    add("locknuts", 2, "steel", f"{sheet['shaft']['nut_front']} / {sheet['shaft']['nut_rear']}", "locknuts")
    add("screws", 2 * sheet["casing"]["n_bolts"], "12.9", f"ISO 4762 {sheet['casing']['screw']} x {2 * int(sheet['casing']['flange_thickness']) + 4}", "screws")
    add("o_ring", 1, "FKM", sheet["housings"]["oring"], "o_ring")
    add("igniter", sheet["combustor"]["n_igniters"], "-", PART_NUMBERS["glow-1/4-32"], "igniter")
    add("egt_probe", 1, "-", PART_NUMBERS["EGT-K-M8"], "egt_probe")
    total_cost = sum(b["line_cost_EUR"] for b in bom)
    lead = max(b["lead_weeks"] for b in bom)
    rules = [
        check("MFG-1", "impeller tip clearance remaining at worst-case stack-up", rub_i, 0.05, "min", "tolerance chain (worst case)", unit="mm",
              note="tighten the axial chain or open the nominal clearance"),
        check("MFG-2", "turbine tip clearance remaining at worst-case stack-up", rub_t, 0.05, "min", "tolerance chain incl. thermal growth", unit="mm"),
        check("MFG-3", "impeller efficiency scatter from clearance tolerance (RSS)", d_eta_i, 0.01, "max", "0.3 x d(clr)/b2", hard=False),
        check("MFG-4", "balancing: required residual per plane vs achievable", U_per_plane, resol, "min",
              f"ISO 21940 G{G} at {sp['rpm']:.0f} rpm: {U_per_plane:.3f} g mm per plane", unit="g mm",
              note="a finer balancer or a lower grade is needed"),
        check("MFG-5", "minimum impeller passage width vs cutter", w_min, d_cut, "min", "5-axis cutter access", unit="mm",
              note="fewer blades / splitters or a smaller cutter (deflection!)"),
        check("MFG-6", "impeller blade wrap / pitch (axial-view overlap)", overlap, 1.6, "max", "flank-milling reach", hard=False),
        check("MFG-7", "impeller features flagged", float(len(flags)), 0.0, "max", "machinability screen", hard=False, warn_margin=0.0, note="; ".join(flags)),
        check("MFG-8", "turbine casting features flagged", float(len(t_flags)), 0.0, "max", "investment-casting screen", hard=False, warn_margin=0.0, note="; ".join(t_flags)),
        check("MFG-9", "exducer root stress vs process-adjusted allowable", min(c["sigma_root_mcs_Pa"], allow_i) / 1e6 if c["t_root_m"] < 0.0199 else c["sigma_root_mcs_Pa"] / 1e6,
              allow_i / 1e6, "max", f"{g('impeller_process')}: allowable x {proc_i['allowable_factor']} (root sized to the limit)", unit="MPa", warn_margin=0.0),
        check("MFG-10", "turbine root stress vs process-adjusted allowable", t["sigma_root_mcs_Pa"] / 1e6, allow_t / 1e6, "max",
              f"{g('turbine_process')}: allowable x {proc_t['allowable_factor']}", unit="MPa"),
    ]
    return dict(stackup=dict(impeller=dict(chain=chain_imp, worst_case_mm=wc_i, rss_mm=rss_i, nominal_clearance_mm=clr_i, remaining_worst_mm=rub_i,
                                           d_eta_rss=d_eta_i),
                             turbine=dict(chain=chain_tur, worst_case_mm=wc_t, rss_mm=rss_t, nominal_clearance_mm=clr_t, remaining_worst_mm=rub_t,
                                          d_eta_rss=d_eta_t), tolerances_mm=tol),
                balance=dict(grade=G, e_per_um=e_per * 1e6, U_total_gmm=U_per_total, U_per_plane_gmm=U_per_plane, resolution_gmm=resol,
                             rotor_mass_kg=m_rot),
                impeller_machining=dict(process=str(g("impeller_process")), passage_width_min_mm=w_min, w_exit_mm=w_exit * 1e3,
                                        w_inducer_mm=w_inducer * 1e3, w_splitter_mm=w_split * 1e3, wrap_deg=wrap_deg, overlap_pitches=overlap,
                                        fillet_mm=fillet, tip_thickness_mm=t_min, flags=flags, surface_Ra_um=proc_i["Ra_um"], note=proc_i["note"]),
                turbine_casting=dict(process=str(g("turbine_process")), te_mm=te_t, hub_pitch_mm=pitch_hub, flags=t_flags, note=proc_t["note"]),
                allowables=dict(impeller_process_MPa=allow_i / 1e6, turbine_process_MPa=allow_t / 1e6),
                bom=bom, cost_EUR=total_cost, lead_weeks=lead, _rules=rules)
