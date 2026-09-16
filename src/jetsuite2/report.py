"""Markdown design report from the current state."""
from __future__ import annotations

from .rules import format_rules
from .stages import ORDER


def _f(x, n=4):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{n}g}"
    return str(x)


def render(design) -> str:
    o = design.outputs()
    r, c, s, cp, t, cb, lay, ro, me, ge = (o.get(k, {}) for k in ORDER)
    L = []
    L.append(f"# {design.doc['name']} - design report (v{design.store.version})\n")
    L.append(f"Overall rule verdict: **{design.verdict()}**\n")
    L.append("## Requirements and cycle\n")
    L.append("| item | value |\n|---|---|")
    L += [f"| thrust | {_f(r.get('thrust_N'))} N at {_f(r.get('altitude_m'))} m, M {_f(r.get('mach'))} |",
          f"| OPR / T04 | {_f(c.get('OPR'))} / {_f(c.get('T04_K'))} K |",
          f"| airflow / fuel flow | {_f(c.get('W_kg_s'))} kg/s / {_f(c.get('Wf_kg_s'))} kg/s |",
          f"| TSFC | {_f(c.get('TSFC_kg_per_N_h'))} kg/(N h) |",
          f"| Tt3 / Tt5 | {_f(c.get('Tt3_K'))} / {_f(c.get('Tt5_K'))} K |",
          f"| turbine PR / NPR | {_f(c.get('turbine_PR_tt'))} / {_f(c.get('NPR'))} ({'choked' if c.get('nozzle_choked') else 'unchoked'}) |",
          f"| efficiencies assumed (c / t) | {_f(c.get('eta_c_assumed'))} / {_f(c.get('eta_t_assumed'))} |",
          f"| efficiencies estimated (c / t) | {_f(cp.get('eta_tt_est'))} / {_f(t.get('eta_tt_est'))} |"]
    L.append("\n## Spool speed\n")
    L.append(f"{_f(s.get('rpm'))} rpm ({s.get('mode')}); limits: inducer {_f(s.get('rpm_limit_inducer'), 5)}, "
             f"turbine AN2 {_f(s.get('rpm_limit_turbine_AN2'), 5)}, turbine disc {_f(s.get('rpm_limit_turbine_disc'), 5)}, "
             f"bearing DN {_f(s.get('rpm_limit_bearing_DN'), 5)} rpm\n")
    L.append("## Compressor\n")
    L.append("| item | value |\n|---|---|")
    L += [f"| material | {cp.get('material')} |",
          f"| inducer r1h / r1s | {_f((cp.get('r1h_m') or 0)*1e3)} / {_f((cp.get('r1s_m') or 0)*1e3)} mm, M1rel {_f(cp.get('M1s_rel'))} |",
          f"| impeller D2 / b2 / L | {_f((cp.get('D2_m') or 0)*1e3)} / {_f((cp.get('b2_m') or 0)*1e3)} / {_f((cp.get('axial_length_m') or 0)*1e3)} mm |",
          f"| U2 / backsweep / blades | {_f(cp.get('U2_m_s'))} m/s / {_f(cp.get('backsweep_deg'))} deg / {cp.get('n_main')}+{cp.get('n_splitter')} |",
          f"| slip / work coefficient | {_f(cp.get('slip_factor'))} / {_f(cp.get('work_coefficient'))} |",
          f"| exducer root / tip thickness | {_f((cp.get('t_root_m') or 0)*1e3)} / {_f((cp.get('t_tip_m') or 0)*1e3)} mm |",
          f"| diffuser | {cp.get('diffuser_type')}, r3/r2 {_f((cp.get('r3_m') or 0)/(cp.get('r2_m') or 1))}, r4 {_f((cp.get('r4_m') or 0)*1e3)} mm, {cp.get('n_vanes')} vanes, M4 {_f(cp.get('M4'))} |",
          f"| choke margin | {_f(cp.get('choke_margin'))} |"]
    L.append("\n## Turbine\n")
    L.append("| item | value |\n|---|---|")
    L += [f"| material (rotor / NGV) | {t.get('material')} / {t.get('ngv_material')} |",
          f"| psi / phi / reaction | {_f(t.get('psi'))} / {_f(t.get('phi'))} / {_f(t.get('reaction'))} |",
          f"| mean radius / heights | {_f((t.get('r_mean_m') or 0)*1e3)} mm; NGV {_f((t.get('h_ngv_m') or 0)*1e3)} mm, rotor {_f((t.get('h_rotor_m') or 0)*1e3)} mm |",
          f"| tip diameter / hub-tip | {_f((t.get('r_tip_rotor_m') or 0)*2e3)} mm / {_f(t.get('hub_tip_ratio_exit'))} |",
          f"| counts NGV / rotor | {t.get('n_ngv')} / {t.get('n_rotor')} |",
          f"| root stress at MCS / allowable | {_f((t.get('sigma_root_mcs_Pa') or 0)/1e6)} / {_f((t.get('sigma_allow_Pa') or 0)/1e6)} MPa |"]
    L.append("\n## Combustor\n")
    L.append(f"Annular, Ro {_f((cb.get('Ro_m') or 0)*1e3)} mm, Ri {_f((cb.get('Ri_m') or 0)*1e3)} mm, liner {_f((cb.get('L_liner_m') or 0)*1e3)} mm long, "
             f"U_ref {_f(cb.get('U_ref_m_s'))} m/s, residence {_f(cb.get('residence_time_ms'))} ms, {cb.get('n_vaporisers')} vaporisers, igniter {cb.get('igniter')}.\n")
    L.append("## Rotor\n")
    L.append(f"Bearings {ro.get('bearing_id')} (DN {_f(ro.get('DN_mcs'), 3)} at MCS), journal {_f((ro.get('journal_d_m') or 0)*1e3)} mm, "
             f"tube {_f((ro.get('tube_od_m') or 0)*1e3)} x {_f((ro.get('tube_id_m') or 0)*1e3)} mm, span {_f((ro.get('bearing_span_m') or 0)*1e3)} mm. "
             f"Forward criticals: {', '.join(f'{v:.0f}' for v in (ro.get('criticals_rpm') or []))} rpm "
             f"(rigid-body: {', '.join(f'{v:.0f}' for v in (ro.get('rigid_body_rpm') or []))}); first bending "
             f"{'%.0f' % ro['bending_critical_rpm'] if ro.get('bending_critical_found') else 'above scan ceiling %.0f' % ro.get('scan_ceiling_rpm', 0)} rpm.\n")
    L.append("## Envelope and mass\n")
    L.append(f"OD {_f(ge.get('envelope_OD_mm'))} mm x length {_f(ge.get('length_mm'))} mm; estimated dry mass {_f(ge.get('mass_total_kg'), 3)} kg.\n")
    if ge.get("mass"):
        L.append("| part | material | mass kg |\n|---|---|---|")
        for k, v in ge["mass"].items():
            L.append(f"| {k} | {v['material']} | {v['mass_kg']:.3f} |")
    L.append("\n## Design rules\n")
    L.append("```")
    for st in ORDER:
        rs = design.store.doc.get("rules", {}).get(st, [])
        if rs:
            L.append(f"[{st}]")
            L.append(format_rules(rs, only_problems=False))
    L.append("```")
    return "\n".join(L)
