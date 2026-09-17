"""Cold-flow compressor rig definition (ROADMAP section 2): a compressor-only test article the suite
can design and instrument, written from the design state.

The rig is the cheapest route to a measured surge line for *this* compressor: the impeller and diffuser
of the design (and its IGV row if fitted), an electric drive sized from the compressor power at each
speed line, a collector, plenum and throttle valve, and an instrumentation plan whose ranges come from
the predicted map.  The run matrix walks each speed line from choke to the predicted surge band; the
expected outcomes are the map quantities the rig would replace (surge flow per line, choke flow, design
efficiency) and the uncertainty terms it would shrink (the rig band, the IGV extrapolation term).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import uncertainty as unc


def define(design) -> dict:
    o = design.outputs()
    c, cy, sp, lay = o["compressor"], o["cycle"], o["speed"], o["layout"]
    mp = o.get("maps") or {}
    cm = mp.get("compressor_map") or {}
    ctl = o.get("control", {}) or {}
    igv = lay.get("igv") or {}
    W = cy["W_kg_s"]
    # compressor power at design from the cycle (W dh) with the loss-model efficiency
    dh = cy.get("dh_c_J_kg") or (cy.get("Tt3_K", 0) - cy.get("Tt2_K", 0)) * 1005.0
    P_c = W * dh
    N_d = sp["rpm"]
    lines = sorted(cm.get("lines", []), key=lambda l: l["N_frac"])
    # drive: power ~ N^3 along the map; size for 110 % speed with 25 % margin, torque at 50 % speed for start-up
    P_drive = 1.25 * P_c * 1.10 ** 3
    torque_d = P_c / (N_d * 2 * math.pi / 60)
    speedlines = []
    for ln in lines:
        Wc = ln["W_corr"]; PR = ln["PR"]; eta = ln["eta"]
        speedlines.append(dict(N_frac=ln["N_frac"], rpm=ln["N_frac"] * N_d, W_corr_surge=ln["surge_W_corr"], PR_surge=ln["surge_PR"],
                               W_corr_choke=ln["choke_W_corr"], PR_range=[min(PR), max(PR)], eta_max=max(eta),
                               surge_reason=ln.get("surge_reason"),
                               W_band=[ln["surge_W_corr"] * (1 - unc.surge_band()["total"]), ln["surge_W_corr"] * (1 + unc.surge_band()["total"])]))
    PR_max = max((max(l["PR"]) for l in lines), default=cy["OPR"])
    T3_max = cy.get("Tt3_K", 500.0) * 1.1
    article = dict(
        impeller=dict(D2_mm=c["D2_m"] * 1e3, r1s_mm=c["r1s_m"] * 1e3, b2_mm=c["b2_m"] * 1e3, n_main=c.get("n_main"), n_splitter=c.get("n_splitter"),
                      backsweep_deg=c.get("backsweep_deg"), material=c["material"], tip_clearance_mm=c["tip_clearance_m"] * 1e3,
                      cad_part="impeller.step (same file as the engine)"),
        diffuser=dict(type=design.doc["inputs"]["compressor"].get("diffuser_type", "vaned"), r3_over_r2=c.get("r3_m", 0) / c["r2_m"] if c.get("r3_m") else None,
                      r4_mm=c["r4_m"] * 1e3, n_vanes=c.get("n_vanes"), vane_LE_deg=c.get("vane_le_angle_deg"),
                      throat_mm=(c.get("vane_throat_geometric_m") or 0) * 1e3, cad_part="diffuser.step"),
        igv=(dict(fitted=True, n_vanes=igv.get("n_vanes"), chord_mm=igv.get("chord_m", 0) * 1e3, settings_deg=ctl.get("igv_settings", [0.0]),
                  actuation="manual indexed ring on the rig (0 / half / full setting), position read by potentiometer")
             if igv.get("fitted") else dict(fitted=False, note="no IGV on the engine; a bolt-on IGV ring is optional to create the pre-swirl datum")),
        deswirl_and_collector=dict(note="engine deswirl cascade replaced by a plenum collector (r = 1.6 r4) with 4 static taps; exit to the throttle"),
        shaft_and_bearings=dict(bearing=o["rotor"].get("bearing_id"), note="engine front bearing pair on a rig shaft; rear support replaced by the drive coupling"),
    )
    drive = dict(type="electric (PMSM) with VFD, or a cold-air turbine if > 60 kW", power_kW=P_drive / 1e3, max_rpm=1.10 * N_d,
                 torque_Nm_at_design=torque_d, torque_meter="inline strain-gauge torque meter, 0.5 % FS", coupling="quill shaft, torsionally soft",
                 note=f"compressor power at design {P_c/1e3:.1f} kW; sized with 25 % margin at 110 % speed")
    instruments = [
        dict(measurement="inlet total pressure / temperature", sensor="4 Pt probes + 2 PT100 in the bellmouth", range=f"0.7-1.1 bar, 260-330 K", accuracy="0.1 % / 0.3 K", closes="corrected flow and speed"),
        dict(measurement="mass flow", sensor="calibrated bellmouth or upstream venturi (dP)", range=f"0-{1.3*W:.2f} kg/s", accuracy="0.5 %", closes="every map point"),
        dict(measurement="impeller exit static pressure", sensor="4 x Kulite fast statics at r = 1.03 r2, 20 kHz", range=f"0-{PR_max*1.2:.1f} bar", accuracy="0.5 %",
             closes="stall precursors (rotating stall), surge onset, diffuser inlet Mach"),
        dict(measurement="diffuser exit total pressure / temperature", sensor="3 x 5-element Pt rakes + 3 TC rakes at r4", range=f"0-{PR_max*1.2:.1f} bar, 300-{T3_max:.0f} K", accuracy="0.2 % / 0.5 K",
             closes="stage PR, isentropic efficiency (torque cross-check)"),
        dict(measurement="collector static pressure", sensor="4 static taps", range=f"0-{PR_max*1.2:.1f} bar", accuracy="0.2 %", closes="back-pressure control"),
        dict(measurement="spool speed", sensor="60-tooth wheel + magnetic pickup", range=f"0-{1.15*N_d:.0f} rpm", accuracy="0.05 %", closes="corrected speed"),
        dict(measurement="shaft torque", sensor=drive["torque_meter"], range=f"0-{1.5*torque_d:.2f} N m", accuracy="0.5 %", closes="power-based efficiency"),
        dict(measurement="tip clearance", sensor="2 capacitive probes over the exducer", range="0-1 mm", accuracy="10 um", closes="clearance effect on efficiency and surge (MFG-2)"),
        dict(measurement="casing vibration", sensor="2 accelerometers (radial, axial)", range="0-50 g, 20 kHz", accuracy="-", closes="surge trip, rotor health"),
        dict(measurement="throttle position", sensor="motorised butterfly / cone valve with encoder", range="0-100 %", accuracy="0.1 %", closes="operating point control"),
    ]
    run_matrix = []
    for s in speedlines:
        run_matrix.append(dict(speed_line=s["N_frac"], rpm=s["rpm"], procedure="open throttle to choke, record 8 points closing toward surge; last 3 points at 2 % flow steps inside the predicted band",
                               predicted=dict(W_corr_choke=s["W_corr_choke"], W_corr_surge=s["W_corr_surge"], surge_band_W_corr=s["W_band"], PR_surge=s["PR_surge"]),
                               igv_settings=article["igv"].get("settings_deg", [0.0]) if article["igv"]["fitted"] else [0.0]))
    safety = dict(surge_detection="Kulite rms > 3 x baseline or collector pressure drop > 5 % in 20 ms -> throttle opens fully (< 100 ms actuator)",
                  overspeed="trip at 112 % design speed", vibration="trip at 20 g casing", temperature=f"trip at {T3_max:.0f} K diffuser exit",
                  max_surge_cycles="stop the line after 3 surge events; inspect the exducer")
    expected = dict(replaces=["compressor_map.lines[*].surge_W_corr (measured)", "compressor_map.lines[*].choke_W_corr", "design-point eta (torque and rake)"],
                    shrinks=[f"rig band {unc.surge_band()['total']:.3f} -> read-off band ~0.02 (this compressor, no transcription unknowns)",
                             "IGV extrapolation term -> measured pre-swirl effect" if article["igv"]["fitted"] else "IGV term only if the optional IGV ring is fitted"],
                    ingest=dict(stage="maps", fields="surge_W_corr per line, choke_W_corr, eta_design", tier="L3", via="jet ingest handoff/compressor_rig/ingest_template.json"))
    return dict(design=design.doc["name"], version=design.store.version, at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                test_article=article, drive=drive, instrumentation=instruments, speedlines=speedlines, run_matrix=run_matrix, safety=safety, expected=expected,
                design_point=dict(W_kg_s=W, PR=cy["OPR"], rpm=N_d, P_compressor_kW=P_c / 1e3))


def render(r: dict) -> str:
    L = [f"# Cold-flow compressor rig: {r['design']} v{r['version']:04d}", "", f"Generated {r['at']}. Compressor-only test article for a measured surge line, choke flow and efficiency of this design's compressor.", "",
         "## Test article", ""]
    a = r["test_article"]
    L.append(f"- Impeller: D2 {a['impeller']['D2_mm']:.1f} mm, inducer tip r {a['impeller']['r1s_mm']:.1f} mm, b2 {a['impeller']['b2_mm']:.2f} mm, {a['impeller']['n_main']} + {a['impeller']['n_splitter']} blades, backsweep {a['impeller']['backsweep_deg']} deg, {a['impeller']['material']}, tip clearance {a['impeller']['tip_clearance_mm']:.2f} mm ({a['impeller']['cad_part']}).")
    d = a["diffuser"]
    L.append(f"- Diffuser: {d['type']}, r4 {d['r4_mm']:.1f} mm, {d['n_vanes']} vanes, LE angle {d['vane_LE_deg']} deg, throat {d['throat_mm']:.2f} mm ({d['cad_part']}).")
    L.append(f"- IGV: {'fitted, ' + str(a['igv']['n_vanes']) + ' vanes, settings ' + str(a['igv']['settings_deg']) + ' deg; ' + a['igv']['actuation'] if a['igv']['fitted'] else a['igv']['note']}")
    L.append(f"- {a['deswirl_and_collector']['note']}.")
    L.append(f"- Bearings: {a['shaft_and_bearings']['bearing']}; {a['shaft_and_bearings']['note']}.")
    dr = r["drive"]
    L += ["", "## Drive", "", f"{dr['type']}: {dr['power_kW']:.1f} kW, {dr['max_rpm']:.0f} rpm max, {dr['torque_Nm_at_design']:.2f} N m at design; {dr['torque_meter']}; {dr['coupling']}. {dr['note']}.", "",
          "## Instrumentation", "", "| measurement | sensor | range | accuracy | closes |", "|---|---|---|---|---|"]
    for i in r["instrumentation"]:
        L.append(f"| {i['measurement']} | {i['sensor']} | {i['range']} | {i['accuracy']} | {i['closes']} |")
    L += ["", "## Run matrix (predicted values from the L2 map; the band is the rig-calibrated +/- SM band in flow)", "",
          "| N/N_d | rpm | W_corr choke | W_corr surge (predicted) | band | PR at surge | IGV settings |", "|---|---|---|---|---|---|---|"]
    for m in r["run_matrix"]:
        p = m["predicted"]
        L.append(f"| {m['speed_line']:.2f} | {m['rpm']:.0f} | {p['W_corr_choke']:.3f} | {p['W_corr_surge']:.3f} | {p['surge_band_W_corr'][0]:.3f}-{p['surge_band_W_corr'][1]:.3f} | {p['PR_surge']:.2f} | {m['igv_settings']} |")
    L += ["", f"Procedure per line: {r['run_matrix'][0]['procedure'] if r['run_matrix'] else '-'}", "", "## Safety", ""]
    L += [f"- {k}: {v}" for k, v in r["safety"].items()]
    e = r["expected"]
    L += ["", "## What the rig closes", "", "Replaces: " + "; ".join(e["replaces"]), "", "Shrinks: " + "; ".join(e["shrinks"]), "",
          f"Ingest: stage `{e['ingest']['stage']}`, fields {e['ingest']['fields']}, tier {e['ingest']['tier']} ({e['ingest']['via']})", ""]
    return "\n".join(L)


def write(design, out_dir=None) -> dict:
    r = define(design)
    out = Path(out_dir or (Path(design.dir) / "handoff" / "compressor_rig"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "compressor_rig.json").write_text(json.dumps(r, indent=1, default=float), encoding="utf-8")
    (out / "compressor_rig.md").write_text(render(r), encoding="utf-8")
    tmpl = [dict(stage="maps", tier="L3", source="cold-flow rig <date>", fields={"surge_W_corr_measured": None, "choke_W_corr_measured": None, "eta_design_measured": None})]
    (out / "ingest_template.json").write_text(json.dumps(tmpl, indent=1), encoding="utf-8")
    return dict(dir=str(out), files=["compressor_rig.md", "compressor_rig.json", "ingest_template.json"], n_lines=len(r["run_matrix"]))
