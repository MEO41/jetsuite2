"""Generated reports: the design report (requirements, cycle, components with
their quality assessment, maps, envelope, transients, life, manufacturing,
margins with uncertainty, open risks, fidelity tier per claim) and the
test-readiness report (predicted performance, limits, failure modes and
precursors, abort criteria, confidence per number)."""
from __future__ import annotations

import json
from pathlib import Path

from .rules import format_rules
from .stages import ORDER, CORE, ANALYSIS


def _f(x, n=4):
    if x is None:
        return "-"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, (int, float)):
        return f"{x:.{n}g}"
    return str(x)


def _tier_table(design) -> list[str]:
    L = ["| stage | kind | tier | last run | overrides (ingested) |", "|---|---|---|---|---|"]
    for r in design.status():
        ov = ", ".join(f"{k} [{t}]" for k, t in r["overrides"].items()) or "-"
        L.append(f"| {r['stage']} | {'core' if r['core'] else 'analysis'} | {r['tier']} | {r['at'] or 'not run'}{' (stale)' if r['stale'] else ''} | {ov} |")
    return L


def _uq_section(design) -> list[str]:
    sdir = Path(design.dir) / "studies"
    L = []
    if not sdir.exists():
        return L
    for p in sorted(sdir.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("kind") != "uq":
            continue
        L.append(f"\n### Uncertainty ({r['name']}, {r['n']} LHS samples, from v{r.get('base_version')})\n")
        L.append("| quantity | p05 | p50 | p95 | std |\n|---|---|---|---|---|")
        for k, s in r["stats"].items():
            L.append(f"| {k} | {_f(s['p05'])} | {_f(s['p50'])} | {_f(s['p95'])} | {_f(s['std'], 3)} |")
        L.append(f"\nProbability that at least one design rule fails under the input uncertainty: {100*r['probability_of_rule_failure']:.0f} %.")
        L.append("Uncertainty bands: " + "; ".join(f"{k} +/-{v['sigma']} ({v['source']})" for k, v in r["uncertainties"].items()))
    return L


def render(design) -> str:
    o = design.outputs()
    r, c, s, cp, t, cb, lay, ro, me, ge = (o.get(k, {}) for k in ("requirements", "cycle", "speed", "compressor", "turbine",
                                                                  "combustor", "layout", "rotor", "mechanical", "geometry"))
    mp, od, env, tr, ass, c1d, life, rd, mfg, tb = (o.get(k, {}) for k in ("maps", "offdesign", "envelope", "transient", "assess",
                                                                            "combustor1d", "life", "rotordyn", "manufacturing", "testbench"))
    L = []
    L.append(f"# {design.doc['name']} - design report (v{design.store.version})\n")
    L.append(f"Overall rule verdict: **{design.verdict()}**. Fidelity tier of every claim is listed per stage at the end; "
             f"L1 = correlation / mean-line sizing, L2 = mean-line loss models and FE beam rotordynamics, L3 = ingested solver or test results.\n")
    L.append("## Requirements and cycle\n")
    L.append("| item | value |\n|---|---|")
    L += [f"| thrust | {_f(r.get('thrust_N'))} N at {_f(r.get('altitude_m'))} m, M {_f(r.get('mach'))} |",
          f"| OPR / T04 | {_f(c.get('OPR'))} / {_f(c.get('T04_K'))} K |",
          f"| airflow / fuel flow | {_f(c.get('W_kg_s'))} kg/s / {_f(c.get('Wf_kg_s'))} kg/s |",
          f"| TSFC | {_f(c.get('TSFC_kg_per_N_h'))} kg/(N h) |",
          f"| Tt3 / Tt5 | {_f(c.get('Tt3_K'))} / {_f(c.get('Tt5_K'))} K |",
          f"| turbine PR / NPR | {_f(c.get('turbine_PR_tt'))} / {_f(c.get('NPR'))} ({'choked' if c.get('nozzle_choked') else 'unchoked'}) |",
          f"| efficiencies assumed (c / t) | {_f(c.get('eta_c_assumed'))} / {_f(c.get('eta_t_assumed'))} |",
          f"| efficiencies estimated L1 (c / t) | {_f(cp.get('eta_tt_est'))} / {_f(t.get('eta_tt_est'))} |"]
    if mp.get("design_point"):
        dp = mp["design_point"]; tdp = mp.get("turbine_design_point", {})
        L.append(f"| efficiencies L2 loss model (c / t) | {_f(dp.get('eta'))} / {_f(tdp.get('eta_tt'))} |")
        L.append(f"| L2 design-point PR / surge margin | {_f(dp.get('PR'))} / {_f(dp.get('surge_margin'))} ({dp.get('surge_reason')}) |")
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
          f"| diffuser | {cp.get('diffuser_type')}, r3/r2 {_f((cp.get('r3_m') or 0)/(cp.get('r2_m') or 1))}, r4 {_f((cp.get('r4_m') or 0)*1e3)} mm, {cp.get('n_vanes')} vanes, throat M {_f(cp.get('diffuser_throat_mach'))} |",
          f"| choke margin | {_f(cp.get('choke_margin'))} |"]
    if ass.get("items"):
        L.append("\n### Component quality assessment\n")
        L.append(f"Scores (1 = inside the target band): compressor {_f(ass['scores'].get('compressor'), 2)}, diffuser {_f(ass['scores'].get('diffuser'), 2)}, turbine {_f(ass['scores'].get('turbine'), 2)}. "
                 f"Balje: Ns {_f(ass['balje']['Ns'])}, Ds {_f(ass['balje']['Ds'])}, achievable efficiency ~{_f(ass['balje']['eta_achievable'], 3)}. "
                 f"Slip factors: " + ", ".join(f"{k} {v:.3f}" for k, v in ass["slip"].items()) + ".\n")
        L.append("| id | item | value | target | score | consequence |\n|---|---|---|---|---|---|")
        for it in ass["items"]:
            L.append(f"| {it['id']} | {it['name']} | {_f(it['value'])} {it['unit']} | {_f(it['target'][0])} .. {_f(it['target'][1])} | {_f(it['score'], 2)} | {it['consequence']} |")
        if ass.get("backsweep_trade"):
            L.append("\nBacksweep trade (sizing chain + L2 speed line at the design speed):\n")
            L.append("| backsweep | U2 m/s | r2 mm | t_root mm | eta L1 | eta L2 | SM | choke margin | W1s/W2 |\n|---|---|---|---|---|---|---|---|---|")
            for b in ass["backsweep_trade"]:
                if b.get("ok"):
                    L.append(f"| {b['backsweep']} | {_f(b['U2'])} | {_f(b['r2_mm'])} | {_f(b['t_root_mm'], 3)} | {_f(b['eta_L1'], 3)} | {_f(b['eta_L2'], 3)} | {_f(b['SM'], 3)} | {_f(b['choke_margin'], 3)} | {_f(b['diffusion_ratio'], 3)} |")
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
    if c1d.get("zones"):
        L.append("1-D network (L2): " + "; ".join(f"{k}: phi {v['phi']:.2f}, T {v['T_K']:.0f} K, residence {v['residence_ms']:.2f} ms, Da {v['Damkohler']:.0f}" for k, v in c1d["zones"].items()) + ". ")
        L.append(f"Combustion efficiency {_f(c1d.get('eta_b_model'), 3)}, LBO margin design {_f(c1d.get('lbo_margin_design'))} / idle {_f(c1d.get('lbo_margin_idle'))}, "
                 f"pattern factor {_f(c1d.get('pattern_factor'), 2)} (NGV peak {_f(c1d.get('T_ngv_peak_K'), 4)} K), liner wall {_f(c1d.get('liner_wall_T_K'), 4)} K, "
                 f"altitude relight index {_f(c1d.get('relight', {}).get('index'))}. {c1d.get('uncertainty_note', '')}\n")
    L.append("## Rotor\n")
    L.append(f"Bearings {ro.get('bearing_id')} (DN {_f(ro.get('DN_mcs'), 3)} at MCS), journal {_f((ro.get('journal_d_m') or 0)*1e3)} mm, "
             f"tube {_f((ro.get('tube_od_m') or 0)*1e3)} x {_f((ro.get('tube_id_m') or 0)*1e3)} mm, span {_f((ro.get('bearing_span_m') or 0)*1e3)} mm. "
             f"Forward criticals: {', '.join(f'{v:.0f}' for v in (ro.get('criticals_rpm') or []))} rpm "
             f"(rigid-body: {', '.join(f'{v:.0f}' for v in (ro.get('rigid_body_rpm') or []))}); first bending "
             f"{'%.0f' % ro['bending_critical_rpm'] if ro.get('bending_critical_found') else 'above scan ceiling %.0f' % ro.get('scan_ceiling_rpm', 0)} rpm.\n")
    if rd.get("unbalance"):
        ub = rd["unbalance"]; bm = rd["blade_modes"]
        L.append(f"Rotordynamics campaign (L2): max synchronous amplitude at G{ub['G']} {_f(ub['x_max_um'], 3)} um, AF {_f(ub.get('AF_first_peak'), 3)}; "
                 f"exducer f1 {_f(bm['exducer_f1_Hz'], 4)} Hz, turbine blade f1 {_f(bm['turbine_blade_f1_Hz'], 4)} Hz; "
                 f"resonance crossings in range: {sum(1 for x in bm['crossings'] if x['in_range'])}.\n")
    if od.get("running_line"):
        L.append("## Off-design and envelope (L2 maps)\n")
        L.append(f"Running line at the design condition: idle at N {_f(od['idle']['N_frac'], 2)} ({_f(od['idle']['Fn'], 3)} N), minimum surge margin {_f(od['SM_min'], 3)} at N {_f(od['SM_min_N_frac'], 2)}, "
                 f"max point {_f(od['max_point']['Fn'], 4)} N at T04 {_f(od['max_point']['T04'], 4)} K ({od['max_point'].get('limit')}-limited).\n")
        L.append("| N/N_d | thrust N | TSFC | T04 K | EGT K | SM | PR_c |\n|---|---|---|---|---|---|---|")
        for p in od["running_line"]:
            if p["converged"]:
                L.append(f"| {p['N_frac']:.2f} | {p['Fn']:.0f} | {p['TSFC_kg_N_h']:.3f} | {p['T04']:.0f} | {p['EGT']:.0f} | {p['SM']:+.3f} | {p['PR_c']:.2f} |")
        if env.get("grid"):
            L.append(f"\nEnvelope: {env['n_cleared']}/{env['n_points']} grid points cleared (SM >= floor), worst SM {_f(env.get('worst_SM'))} at "
                     f"{env['worst_point']['alt'] if env.get('worst_point') else '-'} m / M {env['worst_point']['M'] if env.get('worst_point') else '-'} / dT {env['worst_point']['dT'] if env.get('worst_point') else '-'} K; "
                     f"SLS max thrust {_f(env.get('F_sls'), 4)} N.\n")
            L.append("| alt m | M | dT K | thrust N | TSFC | N/N_d | T04 K | SM | limit |\n|---|---|---|---|---|---|---|---|---|")
            for gp in env["grid"]:
                if gp.get("ok") and gp["dT"] == 0:
                    L.append(f"| {gp['alt']:.0f} | {gp['M']} | {gp['dT']} | {gp['Fn']:.0f} | {gp['TSFC_kg_N_h']:.3f} | {gp['N_frac']:.2f} | {gp['T04']:.0f} | {gp['SM']:+.3f} | {gp['limit']} |")
    if tr.get("scenarios"):
        L.append("\n## Transients (L2)\n")
        for k, v in tr["scenarios"].items():
            L.append(f"* **{k}**: " + ", ".join(f"{kk} {_f(vv)}" for kk, vv in v.items()))
    if life.get("creep"):
        L.append("\n## Life (L1, factor-of-3 scatter applied in the verdicts)\n")
        L.append(f"Creep: blade {_f(life['creep']['blade_life_h'], 3)} h, disc rim {_f(life['creep']['rim_life_h'], 3)} h over the mission. "
                 f"LCF: impeller bore {_f(life['lcf']['impeller_cycles'], 3)} cycles, turbine bore {_f(life['lcf']['turbine_cycles_with_thermal'], 3)} cycles "
                 f"(start thermal dT {_f(life['lcf']['thermal_dT_max_K'], 3)} K). Bearing L10 {_f(life['bearing']['L10_h'], 3)} h ({life['bearing']['lubrication']}). "
                 f"Containment: fragment {_f(life['containment']['E_fragment_J'], 3)} J vs casing {_f(life['containment']['t_casing_mm'], 2)} mm (needs {_f(life['containment']['t_required_mm'], 2)} mm).\n")
    if mfg.get("bom"):
        L.append("## Manufacturability (L1)\n")
        st_ = mfg["stackup"]
        L.append(f"Tip clearance stack-up: impeller worst case {_f(st_['impeller']['worst_case_mm'], 2)} mm (RSS {_f(st_['impeller']['rss_mm'], 2)}) against {_f(st_['impeller']['nominal_clearance_mm'], 2)} mm nominal; "
                 f"turbine {_f(st_['turbine']['worst_case_mm'], 2)} / {_f(st_['turbine']['nominal_clearance_mm'], 2)} mm. "
                 f"Balance G{mfg['balance']['grade']}: {_f(mfg['balance']['U_per_plane_gmm'], 3)} g mm per plane. "
                 f"Impeller ({mfg['impeller_machining']['process']}): min passage {_f(mfg['impeller_machining']['passage_width_min_mm'], 3)} mm, wrap {_f(mfg['impeller_machining']['wrap_deg'], 3)} deg; flags: {'; '.join(mfg['impeller_machining']['flags']) or 'none'}. "
                 f"BOM {len(mfg['bom'])} lines, ~{mfg['cost_EUR']:.0f} EUR, lead {mfg['lead_weeks']} weeks.\n")
    banded = [r for r in design.rules() if r.get("band_statement")]
    if banded:
        L.append("## Surge margins with their uncertainty bands\n")
        L.append("Every surge-margin verdict is shown as value, band and the arithmetic of the with-band check.  Terms combine by "
                 "root-sum-square (independent error sources: a rig-fit residual, model-form extrapolations, a dynamics simplification); "
                 "the dominant term names the datum that would shrink the band.  Declared terms are labelled; only the rig term is derived.\n")
        L.append("| rule | value | band | terms | value - band | limit | nominal | with band | tier |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for r in banded:
            terms = "; ".join(f"{k.split(' (')[0]} {v:.3f}{' (declared)' if 'declared' in k else ''}" for k, v in r["band_terms"].items())
            L.append(f"| {r['id']} {r['name']} | {r['value']:+.3f} | +/-{r['band']:.3f} ({r['band_rule']}) | {terms} | {r['value_minus_band']:+.3f} | "
                     f"{r['limit']:.3f} | {'pass' if r['value'] >= r['limit'] else 'FAIL'} | {'pass' if r['pass_with_band'] else 'FAIL'} | {r.get('tier', '-')} |")
        L.append("")
    if mp.get("compressor_map"):
        # the map suite is the primary review artifact: regenerate it from the current stamps and embed it
        try:
            from . import plots
            w = plots.plot_all(design)
            L.append("## Maps and plots\n")
            ctl = o.get("control", {})
            en = [k for k, v in dict(bleed=ctl.get("bleed_enabled"), nozzle=ctl.get("nozzle_variable"), IGV=ctl.get("igv_enabled")).items() if v]
            L.append(f"Schedules in force: {', '.join(en) or 'none (fixed geometry)'}; surge band +/-{mp['compressor_map'].get('surge_band_SM', 0.0):.3f} SM "
                     f"points (rig-calibrated, see docs/validation.md).  Interactive map: `analysis/plots/compressor_map.html`.\n")
            L.append("![compressor map](analysis/plots/compressor_map.png)\n")
            for k in ("turbine", "smith_balje", "campbell"):
                if isinstance(w.get(k), dict) and w[k].get("png"):
                    L.append(f"![{k}](analysis/plots/{Path(w[k]['png']).name})\n")
        except Exception as e:  # plotting must never break the report
            L.append(f"(plots not generated: {e})\n")
    L.append("## Envelope and mass\n")
    L.append(f"OD {_f(ge.get('envelope_OD_mm'))} mm x length {_f(ge.get('length_mm'))} mm; estimated dry mass {_f(ge.get('mass_total_kg'), 3)} kg.\n")
    if ge.get("mass"):
        L.append("| part | material | mass kg |\n|---|---|---|")
        for k, v in ge["mass"].items():
            L.append(f"| {k} | {v['material']} | {v['mass_kg']:.3f} |")
    L += _uq_section(design)
    L.append("\n## Open risks and unresolved items\n")
    problems = [r_ for r_ in design.rules() if r_["verdict"] in ("fail", "warn")]
    if problems:
        for r_ in problems:
            L.append(f"* [{r_['tier']}] **{r_['id']}** {r_['name']}: {_f(r_['value'])} vs {_f(r_['limit'])} {r_['unit']} -> {r_['verdict']}. {r_.get('note', '')}")
    else:
        L.append("* none flagged by the rules")
    L.append("* Surge line: predicted by stall indicators with +/-30 % uncertainty on the margin; no validated vaned-diffuser stall method exists at this fidelity.")
    L.append("* Efficiency correlations, stress concentration factors and life constants are conceptual-level; the UQ study quantifies their effect.")
    L.append("\n## Fidelity tiers\n")
    L += _tier_table(design)
    L.append("\n## Design rules\n")
    L.append("```")
    for st in ORDER:
        rs = design.store.doc.get("rules", {}).get(st, [])
        if rs:
            L.append(f"[{st}]")
            L.append(format_rules(rs, only_problems=False))
    L.append("```")
    return "\n".join(L)


def readiness(design) -> str:
    """Test-readiness report."""
    o = design.outputs()
    cy, od, env, tr, tb, life, rd, c1d, mfg = (o.get(k, {}) for k in ("cycle", "offdesign", "envelope", "transient", "testbench", "life", "rotordyn", "combustor1d", "manufacturing"))
    req = o.get("requirements", {})
    L = [f"# {design.doc['name']} - test-readiness report (v{design.store.version})\n"]
    missing = [k for k in ("maps", "offdesign", "transient", "testbench", "life", "rotordyn") if k not in o]
    if missing:
        L.append(f"**Not ready**: analysis stages not run: {', '.join(missing)} (run `jet analyze`).\n")
    L.append("## Predicted performance (sea-level static bench)\n")
    mx = od.get("max_point", {}); idle = od.get("idle", {})
    uq = _uq_stats(design)
    def band(k, val, n=4):
        s = uq.get(k)
        return f"{_f(val, n)} (p05-p95 {_f(s['p05'], n)} .. {_f(s['p95'], n)})" if s else _f(val, n)
    L.append("| quantity | prediction | confidence / basis |\n|---|---|---|")
    L.append(f"| max thrust | {band('thrust_N', mx.get('Fn'))} N at N {_f(mx.get('N_frac'), 3)} ({mx.get('limit')}-limited) | L2 maps validated vs TurboFlow within 5 %; surge line +/-30 % |")
    L.append(f"| TSFC at max | {band('TSFC', mx.get('TSFC_kg_N_h'))} kg/N/h | cycle + loss models; fleet datasheets within ~10 % |")
    L.append(f"| T04 at max / EGT | {_f(mx.get('T04'), 4)} / {_f(mx.get('EGT'), 4)} K | L2; EGT sensor sees T5 +/- pattern factor |")
    L.append(f"| idle | N {_f(idle.get('N_frac'), 2)}, thrust {_f(idle.get('Fn'), 3)} N, SM {_f(idle.get('SM'), 2)} | L2; low-speed map extrapolated below N 0.4 (L1) |")
    L.append(f"| spool speed at max | {_f(o.get('speed', {}).get('rpm'), 5)} rpm design, {_f(o.get('speed', {}).get('rpm_mcs'), 5)} MCS | limits: {o.get('speed', {}).get('binding_limit')} |")
    if tr.get("scenarios"):
        a = tr["scenarios"]
        L.append(f"| start | light-off {_f(a['start'].get('light_off_s'), 3)} s, self-sustain {_f(a['start'].get('self_sustain_s'), 3)} s, idle {_f(a['start'].get('idle_capture_s'), 3)} s, T04 peak {_f(a['start'].get('T04_peak'), 4)} K | L2 quasi-steady; starter torque assumed |")
        L.append(f"| slam accel idle->95 % | {_f(a['accel'].get('t_95pct_s'), 3)} s, SM min {_f(a['accel'].get('SM_min'), 3)} | L2 |")
    L.append("\n## Operating limits\n")
    lim = tr.get("control", {})
    L.append(f"* T04 limiter {_f(lim.get('T04_limit'))} K; N max {_f(lim.get('N_max_frac'))} x design; accel limiter {lim.get('accel_limit')} x steady Wf/P3; decel floor {lim.get('decel_limit')}.")
    if env.get("grid"):
        L.append(f"* Cleared envelope: {env['n_cleared']}/{env['n_points']} grid points with SM >= floor; worst SM {_f(env.get('worst_SM'))} at "
                 f"{env['worst_point']['alt'] if env.get('worst_point') else '-'} m / M {env['worst_point']['M'] if env.get('worst_point') else '-'} / dT {env['worst_point']['dT'] if env.get('worst_point') else '-'} K.")
    L.append(f"* Bench: sea level static only; ambient temperature offset {_f(req.get('dT_isa_K'))} K assumed.")
    L.append("\n## Expected failure modes and precursors\n")
    fm = [
        ("compressor surge (low speed / slam accel)", f"SM min {_f(od.get('SM_min'))} on the running line; {_f(tr.get('scenarios', {}).get('accel', {}).get('SM_min'))} during accel", "P3 oscillation, thrust drop, EGT rise; audible chuffing"),
        ("turbine over-temperature", f"T04 limiter {_f(lim.get('T04_limit'))} K; hot-start peak {_f(tr.get('scenarios', {}).get('hot_start', {}).get('T04_peak'), 4)} K", "EGT above the limiter, slow acceleration, discolouration of the NGV"),
        ("rotor critical / vibration", f"criticals {', '.join(f'{v:.0f}' for v in (o.get('rotor', {}).get('criticals_rpm') or []))} rpm; G2.5 amplitude {_f(rd.get('unbalance', {}).get('x_max_um'), 3)} um", "vibration peak while traversing rigid modes; growth with time = unbalance change"),
        ("bearing distress", f"DN {_f(o.get('rotor', {}).get('DN_mcs'), 3)}, L10 {_f(life.get('bearing', {}).get('L10_h'), 3)} h", "bearing housing temperature > 450 K, rising vibration, metal in the oil"),
        ("combustor blow-out (lean, decel)", f"LBO margin idle {_f(c1d.get('lbo_margin_idle'))}", "EGT drop > 100 K/s with fuel on; relight needed"),
        ("blade resonance", f"{sum(1 for x in rd.get('blade_modes', {}).get('crossings', []) if x.get('in_range'))} crossings in range", "vibration at vane-passing orders; dwell restrictions"),
        ("impeller rub", f"worst-case clearance remaining {_f(mfg.get('stackup', {}).get('impeller', {}).get('remaining_worst_mm'), 2)} mm", "P3 loss, vibration, witness marks on the shroud"),
    ]
    L.append("| failure mode | predicted margin | precursor to watch |\n|---|---|---|")
    for a, b, c in fm:
        L.append(f"| {a} | {b} | {c} |")
    L.append("\n## Abort criteria\n")
    for a in tb.get("abort_criteria", ["run `jet analyze testbench` for the abort list"]):
        L.append(f"* {a}")
    L.append("\n## Instrumentation plan\n")
    if tb.get("instrumentation"):
        L.append("| measurement | sensor | location | range | expected | tolerance | closes |\n|---|---|---|---|---|---|---|")
        for i in tb["instrumentation"]:
            L.append(f"| {i['measurement']} | {i['sensor']} | {i['location']} | {i['range']} | {i['expected']} | {i['tolerance']} | {i['closes']} |")
    L.append("\n## Test procedure (virtual bench run)\n")
    for p in tb.get("profile", []):
        L.append(f"* t = {p['t']:.0f} s: {p['phase']} (target N {p['target']:.2f})")
    if tb.get("files"):
        L.append(f"\nPredicted data products: {', '.join(tb['files'].values())}")
    L.append("\n## Confidence\n")
    L.append("* Cycle and sizing: L1 correlations, validated against the boomsonic_v0 tool chain (3-5 %) and fleet datasheets.")
    L.append("* Maps and matching: L2 mean-line loss models, validated vs independent code (PR within 5 %, efficiency 1-5 pts); surge line +/-30 %.")
    L.append("* Stresses and life: closed-form with conceptual factors; factor-of-3 life scatter; FE hand-off available (`jet export fea`).")
    L.append("* Numbers with an L3 tag come from ingested solver/test results (see `jet status`).")
    return "\n".join(L)


def _uq_stats(design) -> dict:
    sdir = Path(design.dir) / "studies"
    if not sdir.exists():
        return {}
    for p in sorted(sdir.glob("*.json"), reverse=True):
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("kind") == "uq":
            return r.get("stats", {})
    return {}
