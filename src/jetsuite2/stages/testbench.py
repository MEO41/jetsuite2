"""Analysis stage - virtual test bench (L2).

Runs the transient and steady models the way a test cell would and writes
the same data products: a time-stamped log (CSV) of the test procedure
(start, idle stabilisation, throttle steps up and down, an endurance cycle,
shutdown) with N, EGT (T5), P3, fuel flow, thrust, vibration proxy and
metal temperature, plus a steady-state performance table at the throttle
steps.  Also emits the instrumentation plan (what to measure, where, range,
expected value +/- tolerance) and the abort criteria used during the run.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

from ..perf import matching, transient as ptr
from ..rules import check
from .common import inp, out
from .offdesign import engine_from_doc

TIER = "L2"
CORE = False

DEFAULTS = {
    "throttle_steps": [0.42, 0.6, 0.8, 0.9, 1.0, 0.9, 0.7, 0.42],
    "dwell_s": 8.0,
    "endurance_cycles": 2,
    "dt_s": 0.05,
    "abort": {"EGT_max_K": 1250.0, "N_max_frac": 1.07, "vib_max_um": 40.0, "P3_min_frac_at_max": 0.9},
    "_doc": {"throttle_steps": "sequence of speed demands after idle", "dwell_s": "dwell at each step [s]",
             "endurance_cycles": "idle-max-idle cycles after the throttle steps", "dt_s": "log interval",
             "abort": "abort criteria applied during the virtual run"},
}

READS = ["inputs.testbench.*", "inputs.transient.*", "inputs.cycle.*", "outputs.maps.compressor_map", "outputs.maps.turbine_map",
         "outputs.speed.rpm", "outputs.cycle.*", "outputs.requirements.*", "outputs.rotor.Ip_impeller", "outputs.rotor.Ip_turbine",
         "outputs.transient.control", "outputs.offdesign.running_line", "outputs.layout.*", "outputs.rotordyn.unbalance",
         "outputs.combustor1d.pattern_factor"]


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "testbench", k, DEFAULTS[k])  # noqa: E731
    E = engine_from_doc(doc)
    req = out(doc, "requirements")
    amb = matching.Ambient.at(0.0, 0.0, req["dT_isa_K"])       # test cell: sea level static, ambient offset kept
    ctrl_in = doc["outputs"].get("transient", {}).get("control") or {}
    ctrl = ptr.Control(**{k: v for k, v in ctrl_in.items() if k in ptr.Control.__dataclass_fields__}) if ctrl_in else ptr.Control()
    dt = float(g("dt_s"))
    sched = ptr.steady_schedule(E, amb, [0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.05])
    steps = [float(s) for s in g("throttle_steps")]
    dwell = float(g("dwell_s"))
    # ---- procedure: start (starter), idle 10 s, steps, endurance cycles, shutdown (fuel off)
    profile = [(0.0, "start", ctrl.idle_frac)]
    t = 20.0
    profile.append((t, "idle", ctrl.idle_frac)); t += 10.0
    for s in steps:
        profile.append((t, f"step {s:.2f}", s)); t += dwell
    for _ in range(int(g("endurance_cycles"))):
        profile.append((t, "endurance max", 1.0)); t += dwell
        profile.append((t, "endurance idle", ctrl.idle_frac)); t += dwell
    profile.append((t, "shutdown", 0.0)); t_end = t + 15.0
    def target(tt):
        tf = ctrl.idle_frac
        for t0, name, val in profile:
            if tt >= t0:
                tf = val
        return tf
    # run in segments so the fuel-off shutdown is represented
    res = ptr.simulate(E, amb, ctrl, sched, 0.03, target, t_end=profile[-1][0], dt=dt, starter=True)
    h = res["hist"]
    sd = ptr.simulate(E, amb, ctrl, sched, res["final_N_frac"], 0.0, t_end=15.0, dt=dt, fuel_on=False, x0=res["x"])
    for k in h:
        h[k] += ([tt + profile[-1][0] for tt in sd["hist"]["t"]] if k == "t" else sd["hist"][k])
    # vibration proxy from the unbalance response (amplitude vs rpm) if available
    ub = doc["outputs"].get("rotordyn", {}).get("unbalance")
    vib = []
    for nf in h["N_frac"]:
        if ub:
            vib.append(float(np.interp(nf * E.N_design, ub["response"]["rpm"], ub["response"]["x_imp_um"])))
        else:
            vib.append(float("nan"))
    # ---- abort criteria evaluation
    ab = dict(DEFAULTS["abort"]); ab.update(g("abort") or {})
    aborts = []
    for i, tt in enumerate(h["t"]):
        if h["EGT"][i] > ab["EGT_max_K"]:
            aborts.append((tt, f"EGT {h['EGT'][i]:.0f} K > {ab['EGT_max_K']:.0f}"))
        if h["N_frac"][i] > ab["N_max_frac"]:
            aborts.append((tt, f"N {h['N_frac'][i]:.3f} > {ab['N_max_frac']}"))
        if vib[i] == vib[i] and vib[i] > ab["vib_max_um"]:
            aborts.append((tt, f"vibration {vib[i]:.0f} um > {ab['vib_max_um']}"))
    # ---- data products
    ddir = doc.get("_design_dir")
    files = {}
    if ddir:
        adir = Path(ddir) / "analysis"; adir.mkdir(parents=True, exist_ok=True)
        p = adir / "testbench_log.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "N_rpm", "N_frac", "EGT_K", "T04_K", "P3_Pa", "Wf_kg_s", "thrust_N", "W_kg_s", "vib_um", "T_metal_K"])
            for i in range(len(h["t"])):
                w.writerow([f"{h['t'][i]:.2f}", f"{h['N_frac'][i]*E.N_design:.0f}", f"{h['N_frac'][i]:.4f}", f"{h['EGT'][i]:.1f}", f"{h['T04'][i]:.1f}",
                            f"{h['P3'][i]:.0f}", f"{h['Wf'][i]:.5f}", f"{h['Fn'][i]:.1f}", f"{h['W'][i]:.4f}", f"{vib[i]:.1f}", f"{h['T_metal'][i]:.1f}"])
        files["log_csv"] = str(p)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
        ax[0].plot(h["t"], [n * E.N_design for n in h["N_frac"]], "k-"); ax[0].set_ylabel("N [rpm]")
        ax[1].plot(h["t"], h["EGT"], "r-", label="EGT"); ax[1].plot(h["t"], h["T04"], "m--", label="T04"); ax[1].set_ylabel("K"); ax[1].legend(fontsize=8)
        ax[2].plot(h["t"], h["Fn"], "b-", label="thrust [N]"); ax[2].set_ylabel("N"); ax2 = ax[2].twinx(); ax2.plot(h["t"], [w * 3600 for w in h["Wf"]], "g-", label="fuel [kg/h]"); ax2.set_ylabel("kg/h")
        for t0, name, val in profile:
            ax[0].axvline(t0, color="0.7", lw=0.5)
        ax[2].set_xlabel("t [s]"); fig.suptitle("Virtual test bench run (sea level static)")
        for a in ax:
            a.grid(alpha=.3)
        pp = adir / "testbench_run.png"; fig.tight_layout(); fig.savefig(pp, dpi=110); plt.close(fig)
        files["plot"] = str(pp)
    # ---- steady table at the throttle steps (end of each dwell)
    table = []
    for t0, name, val in profile:
        if not name.startswith("step"):
            continue
        i = min(range(len(h["t"])), key=lambda k: abs(h["t"][k] - (t0 + dwell - 0.5)))
        table.append(dict(step=name, N_frac=h["N_frac"][i], EGT=h["EGT"][i], P3=h["P3"][i], Wf=h["Wf"][i], Fn=h["Fn"][i], W=h["W"][i]))
    # ---- instrumentation plan
    lay = out(doc, "layout"); cy = out(doc, "cycle")
    mx = max(table, key=lambda r: r["Fn"]) if table else None
    PF = doc["outputs"].get("combustor1d", {}).get("pattern_factor", 0.25)
    instr = [
        dict(measurement="spool speed N", sensor="optical / magnetic pickup on the shaft nut", location="impeller nose", range="0-150 krpm",
             expected=f"{E.N_design:.0f} rpm at max", tolerance="+/-0.5 %", closes="all speed-referenced predictions"),
        dict(measurement="thrust", sensor="load cell in the thrust frame", location="engine mount", range=f"0-{1.5*req['thrust_N']:.0f} N",
             expected=f"{mx['Fn'] if mx else req['thrust_N']:.0f} N at max", tolerance="+/-2 %", closes="cycle + nozzle model"),
        dict(measurement="fuel flow", sensor="turbine or Coriolis flowmeter", location="pump outlet", range="0-4 kg/h",
             expected=f"{(mx['Wf'] if mx else cy['Wf_kg_s'])*3600:.2f} kg/h at max", tolerance="+/-1.5 %", closes="TSFC, eta_b"),
        dict(measurement="EGT (T5)", sensor="4 x K thermocouples, circumferentially averaged", location=f"jet pipe x = {lay['x_nozzle0_m']*1e3:.0f} mm",
             range="0-1300 K", expected=f"{(mx['EGT'] if mx else cy['Tt5_K']):.0f} K at max", tolerance=f"+/-{0.5*PF*(cy['T04_K']-cy['Tt3_K']):.0f} K (pattern factor)",
             closes="turbine efficiency, T04 back-calculation"),
        dict(measurement="P3 (compressor exit total)", sensor="pitot rake at the deswirl exit", location=f"x = {lay['x_deswirl_end_m']*1e3:.0f} mm",
             range="0-6 bar abs", expected=f"{cy['Pt3_Pa']/1e5:.2f} bar at max", tolerance="+/-1 %", closes="compressor map, running line"),
        dict(measurement="T3", sensor="K thermocouple", location="deswirl exit", range="300-600 K", expected=f"{cy['Tt3_K']:.0f} K", tolerance="+/-3 K",
             closes="compressor efficiency"),
        dict(measurement="P2 / T2 (inlet)", sensor="static taps + thermocouple in the bellmouth", location="inlet throat", range="0.8-1.1 bar",
             expected="ambient minus bellmouth depression", tolerance="+/-0.2 %", closes="airflow (bellmouth calibration)"),
        dict(measurement="airflow", sensor="calibrated bellmouth (dP)", location="inlet", range=f"0-{1.3*cy['W_kg_s']:.2f} kg/s",
             expected=f"{cy['W_kg_s']:.3f} kg/s at design", tolerance="+/-2 %", closes="compressor map flow scale"),
        dict(measurement="vibration", sensor="2 x accelerometers (radial, 90 deg apart)", location="front bearing housing", range="0-50 g",
             expected="< 10 g rms", tolerance="-", closes="rotordynamics (criticals, unbalance response)"),
        dict(measurement="bearing temperature", sensor="thermocouple on the outer ring", location="front and rear bearing housings", range="300-500 K",
             expected="< 420 K", tolerance="+/-5 K", closes="bearing thermal model, lubrication"),
        dict(measurement="oil / lubrication flow", sensor="flow switch", location="oil-mist line", range="-", expected="per bearing spec", tolerance="-",
             closes="lubrication assumptions"),
    ]
    abort_criteria = [f"EGT > {ab['EGT_max_K']:.0f} K", f"N > {ab['N_max_frac']:.2f} N_design", f"vibration > {ab['vib_max_um']:.0f} um pk at the housing",
                      "P3 falls while N rises (surge)", "bearing temperature > 450 K or rising > 5 K/s", "fuel pressure loss or flame-out (EGT drop > 100 K/s)",
                      "any thrust-frame anomaly"]
    rules = [
        check("TB-1", "virtual run completed without abort", float(len(aborts)), 0.0, "max", "abort criteria", hard=False, warn_margin=0.0,
              note="; ".join(f"t={t0:.1f}s {m}" for t0, m in aborts[:3])),
        check("TB-2", "max thrust reached on the bench vs design", (mx["Fn"] / req["thrust_N"]) if mx else None, 0.95, "min",
              "throttle step to 100 %", hard=False),
    ]
    return dict(profile=[dict(t=t0, phase=n, target=v) for t0, n, v in profile], steady_table=table, aborts=aborts,
                instrumentation=instr, abort_criteria=abort_criteria, files=files, duration_s=h["t"][-1], _rules=rules)
