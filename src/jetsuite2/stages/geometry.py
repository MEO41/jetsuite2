"""Stage 10 - geometry sheet: every dimension the CAD needs, in millimetres,
grouped by part, plus the standard-hardware picks and an analytical mass
estimate per part.

The CAD builder consumes only this sheet.  Each part group carries its own
value hash so the CAD stage can rebuild just the parts whose numbers moved.
"""
from __future__ import annotations

import math

from .. import geomlib
from ..library import materials, components
from ..rules import check
from ..state.store import canonical_hash
from .common import inp, out

DEFAULTS = {
    "flange_bolt_spacing_mm": 38.0,
    "flange_screw_class": "12.9",
    "vane_thickness_mm": "auto",
    "back_plate_mm": 4.0,
    "inlet_wall_mm": 2.0,
    "shroud_wall_mm": 3.0,
    "housing_wall_mm": 4.0,
    "_doc": {
        "flange_bolt_spacing_mm": "circumferential spacing of casing flange screws",
        "flange_screw_class": "ISO 4762 property class for flange screws",
        "vane_thickness_mm": "'auto' or diffuser vane thickness [mm]",
        "back_plate_mm": "diffuser back plate thickness",
        "inlet_wall_mm": "inlet/shroud wall thickness", "shroud_wall_mm": "compressor shroud casting wall",
        "housing_wall_mm": "bearing housing wall thickness",
    },
}

READS = ["inputs.geometry.*", "outputs.compressor.*", "outputs.turbine.*", "outputs.combustor.*",
         "outputs.layout.*", "outputs.rotor.*", "outputs.requirements.max_mass_kg", "outputs.cycle.W_kg_s",
         "outputs.requirements.thrust_N"]

MM = 1e3


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "geometry", k, DEFAULTS[k])  # noqa: E731
    c, t, cb, lay, ro = (out(doc, "compressor"), out(doc, "turbine"), out(doc, "combustor"),
                         out(doc, "layout"), out(doc, "rotor"))
    max_mass = out(doc, "requirements", "max_mass_kg")
    brg = ro["bearing"]
    sheet: dict[str, dict] = {}
    mass: dict[str, dict] = {}

    def add_mass(part, material, volume_m3):
        rho = materials.get(material)["rho"]
        mass[part] = dict(material=material, volume_cm3=volume_m3 * 1e6, mass_kg=volume_m3 * rho)

    # ------------------------------------------------------------ impeller
    r2, r1s, r1h, L_imp = c["r2_m"], c["r1s_m"], c["r1h_m"], c["axial_length_m"]
    hub = [(x * MM, r * MM) for x, r in ro["impeller_hub_profile"]]
    shroud = [(x * MM, r * MM) for x, r in geomlib.impeller_shroud_curve(r1s, r2, L_imp, c["b2_m"])]
    nut = components.locknut(ro["impeller_bore_m"] * MM)
    sheet["impeller"] = dict(
        material=c["material"], hub_profile=hub, shroud_curve=shroud,
        r1s=r1s * MM, r1h=r1h * MM, r2=r2 * MM, b2=c["b2_m"] * MM, axial_length=L_imp * MM,
        n_main=c["n_main"], n_splitter=c["n_splitter"], splitter_length_frac=c["splitter_length_frac"],
        beta_le_hub=c["blade_angle_le_h_deg"], beta_le_rms=c["blade_angle_le_rms_deg"], beta_le_shroud=c["blade_angle_le_s_deg"],
        backsweep=c["backsweep_deg"], t_root=c["t_root_m"] * MM, t_tip=c["t_tip_m"] * MM,
        bore_d=ro["impeller_bore_m"] * MM, tip_clearance=c["tip_clearance_m"] * MM, nut=nut["id"], nut_thread=nut["thread"],
        nut_od=nut["od"], nut_height=nut["height"], rim_thickness=0.06 * r2 * MM,
    )
    add_mass("impeller", c["material"], (ro["m_impeller_kg"]) / materials.get(c["material"])["rho"])

    # ------------------------------------------------------------ inlet / shroud
    wall_in, wall_sh = float(g("inlet_wall_mm")), float(g("shroud_wall_mm"))
    sheet["inlet"] = dict(material="Al6061-T6", x0=lay["x_inlet0_m"] * MM, x1=0.0, r_throat=r1s * MM + c["tip_clearance_m"] * MM,
                          lip_radius=0.35 * r1s * MM, wall=wall_in, shroud_curve=shroud, shroud_wall=wall_sh,
                          r_flange=c["r4_m"] * MM + 6.0, x_exit=L_imp * MM - c["b2_m"] * MM)
    add_mass("inlet_shroud", "Al6061-T6", geomlib.ring_volume(r1s + wall_in * 1e-3, r1s, abs(lay["x_inlet0_m"]))
             + 2 * math.pi * 0.5 * (r1s + r2) * wall_sh * 1e-3 * math.hypot(L_imp, r2 - r1s) * 1.2)

    # ------------------------------------------------------------ diffuser
    vt_in = g("vane_thickness_mm")
    vane_t = max(1.0, 0.012 * r2 * MM) if str(vt_in).lower() == "auto" else float(vt_in)
    bp = float(g("back_plate_mm"))
    sheet["diffuser"] = dict(
        material="Al2618-T61", type=c["diffuser_type"], r2=r2 * MM, r3=c["r3_m"] * MM, r4=c["r4_m"] * MM,
        width=c["b4_m"] * MM, n_vanes=c["n_vanes"], vane_le_angle=c["vane_le_angle_deg"], vane_te_angle=c["vane_te_angle_deg"],
        vane_thickness=vane_t, back_plate=bp, x_channel0=lay["x_diffuser0_m"] * MM, x_channel1=L_imp * MM,
        x_impeller_back=lay["x_impeller_back_m"] * MM,
        n_deswirl=c["n_deswirl"], r_deswirl_inner=c["r_deswirl_inner_m"] * MM, deswirl_length=c["deswirl_length_m"] * MM,
        x_deswirl_end=lay["x_deswirl_end_m"] * MM,
    )
    V_diff = (geomlib.ring_volume(c["r4_m"] + 0.003, r2 * 0.75, bp * 1e-3)   # back plate
              + c["n_vanes"] * vane_t * 1e-3 * c["b4_m"] * (c["r4_m"] - c["r3_m"]) * 1.3
              + geomlib.ring_volume(c["r4_m"], c["r_deswirl_inner_m"], 0.003)
              + c["n_deswirl"] * 0.0015 * (c["r4_m"] - c["r_deswirl_inner_m"]) * c["deswirl_length_m"])
    add_mass("diffuser", "Al2618-T61", V_diff)

    # ------------------------------------------------------------ casings
    wall_c = lay["casing_wall_m"]
    r_env = lay["envelope_radius_m"]
    spacing = float(g("flange_bolt_spacing_mm"))
    n_bolts = max(int(round(2 * math.pi * r_env * MM / spacing)), 6)
    screw = components.screw_for_flange(clamp_load_N=(cb["Ro_m"] ** 2 * math.pi) * 4e5, n_screws=n_bolts,
                                        cls=g("flange_screw_class"))
    x_c0, x_c1 = lay["x_deswirl_end_m"] - 0.004, lay["x_ngv0_m"] + 0.002
    sheet["casing"] = dict(
        material=cb["casing_material"], r_outer=r_env * MM, wall=wall_c * MM, x0=x_c0 * MM, x1=x_c1 * MM,
        n_bolts=n_bolts, screw=screw["id"], screw_dk=screw["dk"], screw_k=screw["k"], flange_thickness=3.0 * wall_c * MM,
        flange_width=screw["dk"] + 4.0, flange_x=[x_c0 * MM, x_c1 * MM],
    )
    add_mass("outer_casing", cb["casing_material"], geomlib.ring_volume(r_env, r_env - wall_c, x_c1 - x_c0)
             + 2 * geomlib.ring_volume(r_env + (screw["dk"] + 4) * 1e-3, r_env, 3 * wall_c))

    # ------------------------------------------------------------ combustor
    holes = {k: dict(v) for k, v in cb["holes"].items()}
    for h in holes.values():
        h["d"] = h.pop("d_m") * MM
    sheet["combustor"] = dict(
        liner_material=cb["liner_material"], x0=lay["x_combustor0_m"] * MM, L_liner=cb["L_liner_m"] * MM,
        L_transition=cb["L_transition_m"] * MM, Ro=cb["Ro_m"] * MM, Ri=cb["Ri_m"] * MM,
        r_liner_outer=cb["r_liner_outer_m"] * MM, r_liner_inner=cb["r_liner_inner_m"] * MM, liner_wall=cb["liner_wall_m"] * MM,
        holes=holes, n_vaporisers=cb["n_vaporisers"], vaporiser_d=cb["vaporiser_d_m"] * MM,
        vaporiser_length=cb["vaporiser_length_m"] * MM, vaporiser_r=cb["vaporiser_r_m"] * MM,
        igniter=cb["igniter"], igniter_d=components.igniter()["d"], igniter_x_frac=cb["igniter_x_frac"], n_igniters=cb["n_igniters"],
        exit_r_out=cb["liner_exit_r_out_m"] * MM, exit_r_in=cb["liner_exit_r_in_m"] * MM,
        inner_casing_r=cb["Ri_m"] * MM, inner_casing_wall=cb["casing_wall_m"] * MM,
    )
    L_l = cb["L_liner_m"] + cb["L_transition_m"]
    V_liner = (2 * math.pi * cb["r_liner_outer_m"] * cb["liner_wall_m"] * L_l
               + 2 * math.pi * cb["r_liner_inner_m"] * cb["liner_wall_m"] * L_l
               + geomlib.ring_volume(cb["r_liner_outer_m"], cb["r_liner_inner_m"], cb["liner_wall_m"])
               + cb["n_vaporisers"] * math.pi * cb["vaporiser_d_m"] * 0.6e-3 * cb["vaporiser_length_m"] * 1.4)
    add_mass("combustor_liners", cb["liner_material"], V_liner)
    add_mass("inner_casing", cb["casing_material"], 2 * math.pi * cb["Ri_m"] * cb["casing_wall_m"] * L_l)

    # ------------------------------------------------------------ NGV + turbine
    sheet["ngv"] = dict(
        material=t["ngv_material"], n=t["n_ngv"], r_hub=t["r_hub_ngv_m"] * MM, r_tip=t["r_tip_ngv_m"] * MM,
        cx=t["cx_ngv_m"] * MM, chord=t["chord_ngv_m"] * MM, stagger=t["stagger_ngv_deg"], angle_in=0.0,
        angle_out=t["alpha2_deg"], tmax_over_c=t["tmax_over_c_ngv"], te_thickness=t["te_thickness_m"] * MM,
        x0=lay["x_ngv0_m"] * MM, ring_thickness=2.5,
    )
    V_ngv = (t["n_ngv"] * t["chord_ngv_m"] ** 2 * t["tmax_over_c_ngv"] * 0.7 * t["h_ngv_m"]
             + geomlib.ring_volume(t["r_tip_ngv_m"] + 2.5e-3, t["r_tip_ngv_m"], t["cx_ngv_m"] * 1.4)
             + geomlib.ring_volume(t["r_hub_ngv_m"], t["r_hub_ngv_m"] - 2.5e-3, t["cx_ngv_m"] * 1.4))
    add_mass("ngv_ring", t["ngv_material"], V_ngv)
    disc = [(x * MM, r * MM) for x, r in ro["turbine_disc_profile"]]
    sheet["turbine"] = dict(
        material=t["material"], n=t["n_rotor"], r_hub=t["r_hub_rotor_m"] * MM, r_tip=t["r_tip_rotor_m"] * MM,
        cx=t["cx_rotor_m"] * MM, chord=t["chord_rotor_m"] * MM, stagger=t["stagger_rotor_deg"],
        angle_in=t["beta2_deg"], angle_out=t["beta3_deg"], tmax_over_c=t["tmax_over_c_rotor"],
        te_thickness=t["te_thickness_m"] * MM, tip_clearance=t["tip_clearance_m"] * MM,
        x0=lay["x_rotor0_m"] * MM, x_disc_mid=lay["x_disc_mid_m"] * MM, disc_profile=disc, bore_d=ro["journal_d_m"] * MM,
        t_rim=ro["t_rim_turbine_m"] * MM,
    )
    add_mass("turbine_wheel", t["material"], ro["m_turbine_kg"] / materials.get(t["material"])["rho"])
    sheet["turbine_shroud"] = dict(material="AISI321", r_in=t["r_tip_rotor_m"] * MM + t["tip_clearance_m"] * MM,
                                   wall=2.0, x0=lay["x_rotor0_m"] * MM - 2.0, x1=lay["x_rotor1_m"] * MM + 2.0)
    add_mass("turbine_shroud", "AISI321", geomlib.ring_volume(t["r_tip_rotor_m"] + 2.5e-3, t["r_tip_rotor_m"] + 0.5e-3,
                                                              t["cx_rotor_m"] + 4e-3))

    # ------------------------------------------------------------ shaft, bearings, housings
    dj = ro["journal_d_m"] * MM
    bw = brg["width"]
    ring_ext = components.retaining_ring(dj, "external")
    ring_int = components.retaining_ring(brg["od"], "internal")
    hw = float(g("housing_wall_mm"))
    x_fb, x_rb = ro["x_front_bearing_m"] * MM, ro["x_rear_bearing_m"] * MM
    sheet["shaft"] = dict(
        material=ro["shaft_material"], x_nose=ro["x_shaft_nose_m"] * MM, x_end=ro["x_shaft_end_m"] * MM,
        d_nose=ro["impeller_bore_m"] * MM, d_journal=dj, tube_od=ro["tube_od_m"] * MM, tube_id=ro["tube_id_m"] * MM,
        x_front_bearing=x_fb, x_rear_bearing=x_rb, bearing_width=bw, nut_front=nut["id"], nut_rear=components.locknut(dj)["id"],
        retaining_ring=ring_ext["id"], ring_groove_d=ring_ext["d2"], ring_groove_w=ring_ext["m"], ring_thickness=ring_ext["s"],
    )
    seg = [(x_fb - bw - ro["x_shaft_nose_m"] * MM, ro["impeller_bore_m"] * MM / 2), (2 * bw, dj / 2),
           (x_rb - x_fb - 2 * bw, ro["tube_od_m"] * MM / 2), (2 * bw, dj / 2),
           (ro["x_shaft_end_m"] * MM - x_rb - bw, dj / 2)]
    V_shaft = sum(math.pi * (rr * 1e-3) ** 2 * (L * 1e-3) for L, rr in seg) - geomlib.tube_volume(ro["tube_id_m"], 0, (x_rb - x_fb - 2 * bw) * 1e-3)
    add_mass("shaft", ro["shaft_material"], max(V_shaft, 0.0))
    sheet["bearings"] = dict(
        id=brg["id"], bore=brg["bore"], od=brg["od"], width=bw, n_balls=brg["n_balls"], ball_d=brg["ball_d"],
        hybrid=brg.get("hybrid", False), x_front=x_fb, x_rear=x_rb, internal_ring=ring_int["id"],
        internal_ring_groove_d=ring_int["d2"], internal_ring_groove_w=ring_int["m"],
    )
    mass["bearings"] = dict(material="steel/ceramic", volume_cm3=None, mass_kg=2 * brg.get("mass_g", 25) * 1e-3)
    oring = components.o_ring(brg["od"] + 2 * hw)
    sheet["housings"] = dict(
        material="AISI321", wall=hw, tunnel_od=ro["tunnel_od_m"] * MM, tunnel_id=ro["tunnel_id_m"] * MM,
        front_housing_x0=lay["x_impeller_back_m"] * MM + 2.0, front_housing_x1=x_fb + bw, front_housing_r_out=brg["od"] / 2 + hw,
        rear_housing_x0=x_rb - bw, rear_housing_x1=x_rb + bw + 3.0, rear_housing_r_out=brg["od"] / 2 + hw,
        tunnel_x0=x_fb + bw, tunnel_x1=x_rb - bw, oring=oring["id"], oring_cs=oring["cs"], oring_groove_depth=oring["groove_depth"],
        oring_groove_width=oring["groove_width"], seal="labyrinth-generic", labyrinth_teeth=4,
        labyrinth_clearance=max(0.10, 0.004 * dj), bearing_bore=brg["od"],
    )
    V_h = (geomlib.ring_volume(ro["tunnel_od_m"], ro["tunnel_id_m"], (x_rb - x_fb - 2 * bw) * 1e-3)
           + 2 * geomlib.ring_volume((brg["od"] / 2 + hw) * 1e-3, brg["od"] / 2 * 1e-3, 2.2 * bw * 1e-3)
           + geomlib.ring_volume(cb["Ri_m"], (brg["od"] / 2 + hw) * 1e-3, 3e-3) * 2)
    add_mass("housings_tunnel", "AISI321", V_h)

    # ------------------------------------------------------------ nozzle
    sheet["nozzle"] = dict(material="AISI321", x0=lay["x_nozzle0_m"] * MM, x_exit=lay["x_nozzle_exit_m"] * MM,
                           r_in=t["r_tip_rotor_m"] * MM + 2.0, r8=lay["r8_m"] * MM, wall=1.2,
                           tail_cone_r0=t["r_hub_rotor_m"] * MM, tail_cone_L=lay["L_tail_cone_m"] * MM, n_struts=4,
                           egt_probe=components.egt_probe()["id"], egt_thread=components.egt_probe()["thread"])
    V_noz = 2 * math.pi * 0.5 * (t["r_tip_rotor_m"] + lay["r8_m"]) * 1.2e-3 * lay["L_nozzle_m"] * 1.1 \
        + math.pi * t["r_hub_rotor_m"] * 1.0e-3 * math.hypot(lay["L_tail_cone_m"], t["r_hub_rotor_m"])
    add_mass("nozzle_tailcone", "AISI321", V_noz)

    # ------------------------------------------------------------ totals & hashes
    m_parts = sum(v["mass_kg"] for v in mass.values())
    m_acc = 0.06 * m_parts + 0.05   # fasteners, fittings, wiring allowance
    m_total = m_parts + m_acc
    hashes = {k: canonical_hash(v) for k, v in sheet.items()}
    F = out(doc, "requirements", "thrust_N")
    rules = [
        check("GEO-1", "dry mass estimate vs limit", m_total, float(max_mass) if max_mass else None, "max",
              "requirements.max_mass_kg", unit="kg"),
        check("GEO-2", "thrust/weight (info)", F / (m_total * 9.81), None, "info", "-", unit="-"),
        check("GEO-3", "flange screws count (info)", n_bolts, None, "info", f"ISO 4762 {screw['id']}"),
    ]
    return dict(sheet=sheet, hashes=hashes, mass=mass, mass_parts_kg=m_parts, mass_accessories_kg=m_acc,
                mass_total_kg=m_total, envelope_OD_mm=lay["OD_m"] * MM, length_mm=lay["length_m"] * MM,
                _rules=rules)
