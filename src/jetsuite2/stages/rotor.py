"""Stage 8 - rotor: shaft, bearings from the component library, DN, torque,
lateral critical speeds.

* Bearings are selected from ``library.components`` (bore >= the journal the
  torque needs, DN limit with margin at MCS, temperature rating).
* The shaft is a stepped tube: front stub through the impeller bore, front
  journal, tube between the bearings, rear journal, turbine stub.
* Critical speeds from an Euler-Bernoulli beam finite-element model of the
  stepped shaft with the impeller and turbine as lumped masses (mass and
  diametral inertia from the shared meridional profiles) on two bearing
  springs.  Gyroscopic stiffening is neglected (conservative for the forward
  bending mode; rigid-body modes are reported for information).
  Verified against the closed-form simply-supported beam in tests.
"""
from __future__ import annotations

import math

import numpy as np

from ..library import materials, components
from ..rules import check
from .. import geomlib
from ..rotordyn import RotorModel
from .common import inp, out, is_auto, journal_rule

DEFAULTS = {
    "shaft_material": "AISI4340",
    "journal_d_mm": "auto",
    "tube_od_mm": "auto",           # auto: 2.4 x journal, capped by the tunnel
    "tube_wall_mm": "auto",         # auto: 0.14 x tube OD, min 2 mm
    "bearing_id": "auto",           # auto: library selection
    "bearing_hybrid": True,
    "bearing_type": "angular_contact",
    "bearing_T_K": 420.0,           # expected bearing operating temperature
    "support_stiffness_N_m": 1.0e7, # bearing + housing radial stiffness (soft mount ~2e6, hard ~5e7)
    "tunnel_clearance_mm": 2.0,     # radial gap tube -> tunnel bore
    "tunnel_wall_mm": 1.5,
    "critical_speed_margin": 1.25,  # first bending critical / MCS
    "impeller_bore_mm": "auto",     # auto: journal diameter (shaft passes through the impeller)
    "_doc": {
        "shaft_material": "shaft material", "journal_d_mm": "'auto' or bearing journal diameter [mm]",
        "tube_od_mm": "'auto' or shaft tube OD between bearings [mm]", "tube_wall_mm": "'auto' or tube wall [mm]",
        "bearing_id": "'auto' or a bearing id from the library", "bearing_hybrid": "prefer hybrid ceramic bearings",
        "bearing_type": "angular_contact or deep_groove", "bearing_T_K": "bearing operating temperature [K]",
        "support_stiffness_N_m": "radial stiffness of each bearing support [N/m]",
        "tunnel_clearance_mm": "radial clearance between shaft tube and tunnel bore",
        "tunnel_wall_mm": "shaft tunnel wall thickness",
        "critical_speed_margin": "required first bending critical / MCS",
        "impeller_bore_mm": "'auto' or impeller bore diameter [mm]",
    },
}

READS = ["inputs.rotor.*", "outputs.speed.rpm", "outputs.speed.omega_rad_s", "outputs.speed.mcs_factor",
         "outputs.speed.journal_d_min_mm", "outputs.cycle.P_turb_W",
         "outputs.compressor.r1h_m", "outputs.compressor.r2_m", "outputs.compressor.axial_length_m",
         "outputs.compressor.material", "outputs.compressor.n_main", "outputs.compressor.n_splitter",
         "outputs.compressor.b2_m", "outputs.compressor.t_root_m", "outputs.compressor.t_tip_m",
         "outputs.compressor.r1s_m",
         "outputs.turbine.material", "outputs.turbine.r_hub_rotor_m", "outputs.turbine.r_tip_rotor_m",
         "outputs.turbine.cx_rotor_m", "outputs.turbine.n_rotor", "outputs.turbine.chord_rotor_m",
         "outputs.turbine.tmax_over_c_rotor", "outputs.turbine.h_rotor_m",
         "outputs.layout.x_impeller_back_m", "outputs.layout.x_front_bearing_m", "outputs.layout.x_rear_bearing_m",
         "outputs.layout.x_disc_mid_m", "outputs.layout.x_rotor1_m", "outputs.combustor.Ri_m"]


def run(doc: dict) -> dict:
    rt = lambda k: inp(doc, "rotor", k, DEFAULTS[k])  # noqa: E731
    rpm, omega, mcs = out(doc, "speed", "rpm"), out(doc, "speed", "omega_rad_s"), out(doc, "speed", "mcs_factor")
    d_j_min = out(doc, "speed", "journal_d_min_mm")
    P_turb = out(doc, "cycle", "P_turb_W")
    c = out(doc, "compressor")
    t = out(doc, "turbine")
    lay = out(doc, "layout")
    Ri_comb = out(doc, "combustor", "Ri_m")
    sh_mat = rt("shaft_material")
    E = materials.get(sh_mat)["E"]
    rho_s = materials.get(sh_mat)["rho"]

    # ---- bearing and journal
    j_in = rt("journal_d_mm")
    d_j = float(j_in) if not is_auto(j_in) else journal_rule(float(d_j_min), 2 * t["r_tip_rotor_m"], c["D2_m"])
    b_in = rt("bearing_id")
    bearing_note = ""
    if is_auto(b_in):
        try:
            brg = components.select_bearing(rpm * mcs, d_j, float(rt("bearing_T_K")), bool(rt("bearing_hybrid")),
                                            dn_margin=1.0, btype=rt("bearing_type"))
        except ValueError as e:
            # nothing in the catalogue admits this DN: take the smallest bore that fits the journal and let ROT-1 report it
            cands = components.bearings(min_bore=d_j, hybrid=bool(rt("bearing_hybrid")), btype=rt("bearing_type")) \
                or components.bearings(min_bore=d_j)
            if not cands:
                raise
            brg = max(cands, key=lambda b: b["dn_limit"] / b["bore"])
            bearing_note = f"no catalogue bearing meets DN: {e}"
    else:
        brg = components.by_id("bearings", b_in)
    d_j = float(brg["bore"])
    DN = d_j * rpm * mcs
    # ---- shaft tube
    od_in, wall_in = rt("tube_od_mm"), rt("tube_wall_mm")
    tube_od = (2.4 * d_j if is_auto(od_in) else float(od_in)) * 1e-3
    clr, wall_t = float(rt("tunnel_clearance_mm")) * 1e-3, float(rt("tunnel_wall_mm")) * 1e-3
    tunnel_od_max = 2 * (Ri_comb - 0.004)   # must clear the combustor inner casing
    tube_od = min(tube_od, tunnel_od_max - 2 * (clr + wall_t))
    tube_od = max(tube_od, d_j * 1e-3 * 1.2)
    tube_wall = (max(0.14 * tube_od, 2e-3) if is_auto(wall_in) else float(wall_in) * 1e-3)
    tube_id = max(tube_od - 2 * tube_wall, 0.0)
    tunnel_od = tube_od + 2 * (clr + wall_t)
    tunnel_id = tube_od + 2 * clr
    bore_in = rt("impeller_bore_mm")
    d_bore_imp = (d_j if is_auto(bore_in) else float(bore_in)) * 1e-3

    # ---- torque
    T_shaft = P_turb / omega
    tau_j = 16 * T_shaft / (math.pi * (d_j * 1e-3) ** 3)
    tau_tube = 16 * T_shaft * tube_od / (math.pi * (tube_od ** 4 - tube_id ** 4))
    tau_allow = 0.577 * materials.yield_at(sh_mat, 450.0)

    # ---- rotor masses (from the shared meridional profiles)
    r2, r1h, L_imp = c["r2_m"], c["r1h_m"], c["axial_length_m"]
    rho_c = materials.get(c["material"])["rho"]
    hub = geomlib.impeller_hub_profile(r1h, r2, L_imp, r_bore=d_bore_imp / 2)
    m_hub, ip_hub, id_hub, x_hub = geomlib.revolved_inertia(hub, rho_c)
    # blades: mean thickness x mean height x mean length, n blades
    t_mean = 0.5 * (c["t_root_m"] + c["t_tip_m"])
    blade_len = 1.15 * math.hypot(L_imp, r2 - c["r1s_m"])
    h_mean = 0.5 * (c["b2_m"] + (c["r1s_m"] - r1h))
    m_blades = rho_c * (c["n_main"] * blade_len + c["n_splitter"] * blade_len * 0.6) * h_mean * t_mean
    r_bl = 0.7 * r2
    m_imp = m_hub + m_blades
    ip_imp = ip_hub + m_blades * r_bl ** 2
    id_imp = id_hub + 0.5 * m_blades * r_bl ** 2
    # turbine wheel
    rho_t = materials.get(t["material"])["rho"]
    r_hub_t, r_tip_t, cx_r = t["r_hub_rotor_m"], t["r_tip_rotor_m"], t["cx_rotor_m"]
    t_rim = 1.2 * cx_r
    disc = geomlib.turbine_disc_profile(r_hub_t, d_j * 1e-3 / 2, t_rim, 0.8 * cx_r, 1.0 * cx_r,
                                        lay["x_disc_mid_m"] - t_rim / 2, hub_len=2.5 * cx_r)
    m_disc, ip_disc, id_disc, x_disc = geomlib.revolved_inertia(disc, rho_t)
    m_tb = rho_t * t["n_rotor"] * t["chord_rotor_m"] * t["tmax_over_c_rotor"] * t["chord_rotor_m"] * 0.7 * t["h_rotor_m"]
    r_tb = 0.5 * (r_hub_t + r_tip_t)
    m_turb = m_disc + m_tb
    ip_turb = ip_disc + m_tb * r_tb ** 2
    id_turb = id_disc + 0.5 * m_tb * r_tb ** 2

    # ---- beam model
    x_fb, x_rb = lay["x_front_bearing_m"], lay["x_rear_bearing_m"]
    x_imp_cg = x_hub
    x_turb_cg = lay["x_disc_mid_m"]
    L_front_stub = max(x_fb - x_imp_cg, 0.01)
    x0 = x_imp_cg - 0.4 * L_imp    # shaft nose (nut) ahead of the impeller CG
    x_end = x_turb_cg + 1.0 * cx_r
    # Beam segments (x0, x1, r_out, r_in, carries_mass).  The impeller hub and the
    # turbine disc hub are modelled as stiff beam sections of the wheel material
    # (their mass is lumped at the CG, so those segments carry no distributed mass).
    bw = brg["width"] * 1e-3
    E_c = materials.get(c["material"])["E"]
    E_t = materials.get(t["material"])["E"]
    x_hub0 = 0.15 * L_imp
    x_imp_back = lay["x_impeller_back_m"]
    x_tdisc0 = lay["x_disc_mid_m"] - 0.8 * cx_r
    x_tdisc1 = lay["x_disc_mid_m"] + 0.8 * cx_r
    rj = d_j * 1e-3 / 2
    segs = [
        (x0, x_hub0, d_bore_imp / 2, 0.0, E, True),
        (x_hub0, x_imp_back, 0.8 * r1h, d_bore_imp / 2, E_c, False),
        (x_imp_back, x_fb - bw, rj, 0.0, E, True),
        (x_fb - bw, x_fb + bw, rj, 0.0, E, True),
        (x_fb + bw, x_rb - bw, tube_od / 2, tube_id / 2, E, True),
        (x_rb - bw, min(x_rb + bw, x_tdisc0 - 1e-4), rj, 0.0, E, True),
        (min(x_rb + bw, x_tdisc0 - 1e-4), x_tdisc0, rj, 0.0, E, True),
        (x_tdisc0, x_tdisc1, 0.6 * r_hub_t, rj, E_t, False),
        (x_tdisc1, max(x_end, x_tdisc1 + 0.005), rj, 0.0, E, True),
    ]
    nodes = []
    EI, rhoA = [], []
    n_per = 5
    m_seg_imp = m_seg_turb = 0.0
    for (xa, xb, ro_, ri_, Em, has_mass) in segs:
        if xb - xa < 1e-6:
            continue
        xs = np.linspace(xa, xb, n_per + 1)
        I = math.pi / 4 * (ro_ ** 4 - ri_ ** 4)
        A = math.pi * (ro_ ** 2 - ri_ ** 2)
        if has_mass:
            ra = rho_s * A
        else:
            # wheel hub beam: carries the wheel material's mass; the lumped wheel mass is reduced accordingly
            rho_w = rho_c if Em == E_c else rho_t
            ra = rho_w * A
            if Em == E_c:
                m_seg_imp += ra * (xb - xa)
            else:
                m_seg_turb += ra * (xb - xa)
        for j in range(n_per):
            nodes.append(xs[j])
            EI.append(Em * I)
            rhoA.append(ra)
    nodes.append(segs[-1][1])
    nodes = np.array(nodes)

    def nearest(xv):
        return int(np.argmin(np.abs(nodes - xv)))

    k_sup = float(rt("support_stiffness_N_m"))
    masses = {nearest(x_imp_cg): max(m_imp - m_seg_imp, 0.3 * m_imp),
              nearest(x_turb_cg): max(m_turb - m_seg_turb, 0.3 * m_turb)}
    inertias = {nearest(x_imp_cg): id_imp, nearest(x_turb_cg): id_turb}
    springs = {nearest(x_fb): k_sup, nearest(x_rb): k_sup}
    polar = {nearest(x_imp_cg): ip_imp, nearest(x_turb_cg): ip_turb}
    model = RotorModel(nodes, EI, rhoA, masses, inertias, polar, springs)
    w_static = model.static_frequencies(4)
    static_rpm = [float(v * 60 / (2 * math.pi)) for v in w_static]
    rpm_mcs = rpm * mcs
    cs_margin = float(rt("critical_speed_margin"))
    # forward-whirl synchronous criticals up to 2.5 x MCS (gyroscopic stiffening included)
    om_max = 2.5 * rpm_mcs * 2 * math.pi / 60
    crits = model.critical_speeds(om_max, n_scan=30, forward_only=True)
    crit_rpm = [float(cw * 60 / (2 * math.pi)) for cw, fw, fr in crits]
    # rigid-body vs bending by the strain-energy fraction carried in the bearing springs
    rigid = [float(cw * 60 / (2 * math.pi)) for cw, fw, fr in crits if fr > 0.5]
    bending = [float(cw * 60 / (2 * math.pi)) for cw, fw, fr in crits if fr <= 0.5]
    spring_fracs = [float(fr) for cw, fw, fr in crits]
    n_bend = bending[0] if bending else (om_max * 60 / (2 * math.pi))   # none below 2.5 x MCS -> report the scan ceiling
    bending_found = bool(bending)
    # bearing loads at 1 g (static) from the overhung masses
    span = x_rb - x_fb
    F_rb = 9.81 * (m_imp * (x_fb - x_imp_cg) * -1 + m_turb * (x_turb_cg - x_fb)) / span
    F_fb = 9.81 * (m_imp + m_turb) - F_rb
    L10_h = None
    if brg.get("C"):
        P_eq = max(abs(F_fb), abs(F_rb)) * 1.5   # crude equivalent load incl. preload
        L10_h = (brg["C"] * 1e3 / P_eq) ** 3 * 1e6 / (60 * rpm)

    rules = [
        check("ROT-1", "bearing DN at MCS vs rating", DN, brg["dn_limit"], "max", f"{brg['id']} catalogue DN limit",
              unit="mm.rpm", note="larger-DN (hybrid, oil-air) bearing, smaller journal, or lower rpm"),
        check("ROT-2", "bearing temperature rating", float(rt("bearing_T_K")), brg["T_max"], "max", f"{brg['id']} T_max", unit="K"),
        check("ROT-3", "first bending critical / MCS", n_bend / rpm_mcs, cs_margin, "min",
              "API 684 separation margin practice (25 %)", note="stiffer/larger tube, shorter span, lighter overhung wheels"),
        check("ROT-4", "rigid-body criticals below 60 % speed (soft mount)", (max(rigid) / rpm) if rigid else 0.0, 0.6, "max",
              "traverse rigid modes below idle-to-cruise band", hard=False,
              note="stiffer mounts move rigid modes up; keep them below idle or add damping"),
        check("ROT-5", "journal torsional stress", tau_j / 1e6, tau_allow / 3 / 1e6, "max", f"{sh_mat} 0.577 Fty / SF 3", unit="MPa"),
        check("ROT-6", "tube torsional stress", tau_tube / 1e6, tau_allow / 3 / 1e6, "max", f"{sh_mat} 0.577 Fty / SF 3", unit="MPa"),
        check("ROT-7", "shaft tunnel fits inside combustor inner casing", tunnel_od / 2, Ri_comb - 0.003, "max",
              "layout: tunnel OD + 3 mm gap", unit="m", note="smaller tube or larger combustor inner radius"),
        check("ROT-8", "bearing L10 life (info)", L10_h, None, "info", "ISO 281 basic rating (no thermal factors)", unit="h"),
    ]
    return dict(
        shaft_material=sh_mat, bearing=brg, bearing_id=brg["id"], bearing_note=bearing_note, journal_d_m=d_j * 1e-3, DN_mcs=DN,
        tube_od_m=tube_od, tube_id_m=tube_id, tube_wall_m=tube_wall, tunnel_od_m=tunnel_od, tunnel_id_m=tunnel_id,
        impeller_bore_m=d_bore_imp, torque_Nm=T_shaft, tau_journal_Pa=tau_j, tau_tube_Pa=tau_tube,
        m_impeller_kg=m_imp, Ip_impeller=ip_imp, Id_impeller=id_imp, x_impeller_cg_m=x_imp_cg,
        m_turbine_kg=m_turb, Ip_turbine=ip_turb, Id_turbine=id_turb, x_turbine_cg_m=x_turb_cg,
        m_blades_impeller_kg=m_blades, m_turbine_blades_kg=m_tb,
        x_front_bearing_m=x_fb, x_rear_bearing_m=x_rb, bearing_span_m=span, x_shaft_nose_m=x0, x_shaft_end_m=x_end,
        support_stiffness_N_m=k_sup, criticals_rpm=crit_rpm, critical_spring_energy_fraction=spring_fracs,
        static_modes_rpm=static_rpm, rigid_body_rpm=rigid,
        bending_critical_rpm=n_bend, bending_critical_found=bending_found, scan_ceiling_rpm=om_max * 60 / (2 * math.pi),
        bending_margin=n_bend / rpm_mcs, F_front_bearing_N=F_fb, F_rear_bearing_N=F_rb, L10_h=L10_h,
        turbine_disc_profile=disc, impeller_hub_profile=hub, t_rim_turbine_m=t_rim,
        _rules=rules,
    )
