"""Analysis stage - transients and abnormal cases on the component maps (L2).

Scenarios (all at the design flight condition unless noted):

* start: starter-motored spool-up, light-off, self-sustaining speed, idle capture
* slam acceleration idle -> 100 %: time to 95 %, minimum surge margin, T04 peak
* deceleration 100 % -> idle: time, lean-limit fuel floor respected
* hot start: fuel schedule x1.5 during start -> T04 overshoot
* hung start: starter torque halved -> does the rotor reach self-sustain
* governor failure: fuel at the acceleration limit -> overspeed reached and T04
* flameout at 60 % and windmilling decay: windmill speed at the flight Mach, relight window

The rotor inertia comes from the rotor stage (impeller + turbine wheel polar
inertia + shaft allowance).  Heat soak is a first-order metal temperature
lag reported for information.  Below the lowest mapped speed line the
compressor map is extended by similarity (labelled L1 in this region).
"""
from __future__ import annotations

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
    "accel_limit": 1.3, "decel_limit": 0.45, "T04_limit": 1200.0, "N_max_frac": 1.05, "idle_frac": 0.50,
    "fuel_ramp_s": 0.3, "starter_torque_Nm": 0.5, "starter_cutoff_frac": 0.35, "light_off_N_frac": 0.10,
    "self_sustain_frac": 0.22, "dt_s": 0.05, "plots": True,
    "_doc": {"accel_limit": "acceleration limiter: max Wf/P3 as a multiple of the steady schedule",
             "decel_limit": "deceleration floor: min Wf/P3 as a fraction of the steady schedule (lean blow-out)",
             "T04_limit": "over-temperature limiter [K]", "N_max_frac": "overspeed governor / design speed",
             "idle_frac": "idle speed / design speed", "fuel_ramp_s": "fuel system first-order lag [s]",
             "starter_torque_Nm": "starter motor torque [N m] up to the cutoff speed", "starter_cutoff_frac": "starter cutoff speed / design",
             "light_off_N_frac": "speed at which ignition is attempted / design", "self_sustain_frac": "expected self-sustaining speed / design",
             "dt_s": "integration time step [s]", "plots": "write transient plots"},
}

READS = ["inputs.transient.*", "inputs.cycle.*", "outputs.maps.compressor_map", "outputs.maps.turbine_map",
         "outputs.speed.rpm", "outputs.cycle.*", "outputs.requirements.altitude_m", "outputs.requirements.mach",
         "outputs.requirements.dT_isa_K", "outputs.rotor.Ip_impeller", "outputs.rotor.Ip_turbine",
         "outputs.offdesign.running_line"]


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "transient", k, DEFAULTS[k])  # noqa: E731
    E = engine_from_doc(doc)
    req = out(doc, "requirements")
    amb = matching.Ambient.at(req["altitude_m"], req["mach"], req["dT_isa_K"])
    ctrl = ptr.Control(accel_limit=float(g("accel_limit")), decel_limit=float(g("decel_limit")), T04_limit=float(g("T04_limit")),
                       N_max_frac=float(g("N_max_frac")), idle_frac=float(g("idle_frac")), fuel_ramp_s=float(g("fuel_ramp_s")),
                       light_off_N_frac=float(g("light_off_N_frac")), starter_torque_Nm=float(g("starter_torque_Nm")),
                       starter_cutoff_frac=float(g("starter_cutoff_frac")), self_sustain_frac=float(g("self_sustain_frac")))
    dt = float(g("dt_s"))
    sched = ptr.steady_schedule(E, amb, [0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.05])
    if len(sched["N"]) < 4:
        raise RuntimeError("steady schedule did not converge on enough speeds")
    results = {}
    # ---- start
    st = ptr.simulate(E, amb, ctrl, sched, 0.03, ctrl.idle_frac, t_end=25.0, dt=dt, starter=True)
    h = st["hist"]
    t_idle = next((t for t, n in zip(h["t"], h["N_frac"]) if n >= 0.98 * ctrl.idle_frac), None)
    results["start"] = dict(light_off_s=st["events"].get("light_off_s"), self_sustain_s=st["events"].get("self_sustain_s"),
                            idle_capture_s=t_idle, T04_peak=max(h["T04"]), EGT_peak=max(h["EGT"]), final_N_frac=st["final_N_frac"],
                            ok=t_idle is not None)
    x_idle = st["x"]
    # ---- slam acceleration idle -> 100 %
    ac = ptr.simulate(E, amb, ctrl, sched, ctrl.idle_frac, 1.0, t_end=12.0, dt=dt, x0=x_idle)
    h = ac["hist"]
    t95 = next((t for t, n in zip(h["t"], h["N_frac"]) if n >= 0.95), None)
    sm = [s for s in h["SM"] if s == s]
    results["accel"] = dict(t_95pct_s=t95, SM_min=min(sm) if sm else None, T04_peak=max(h["T04"]), Fn_final=h["Fn"][-1],
                            ok=t95 is not None)
    # ---- deceleration 100 % -> idle
    de = ptr.simulate(E, amb, ctrl, sched, 1.0, ctrl.idle_frac, t_end=12.0, dt=dt, x0=ac["x"])
    h = de["hist"]
    t_dec = next((t for t, n in zip(h["t"], h["N_frac"]) if n <= 1.02 * ctrl.idle_frac), None)
    results["decel"] = dict(t_to_idle_s=t_dec, Wf_min=min(h["Wf"]), T04_min=min(h["T04"]), ok=t_dec is not None)
    # ---- hot start (rich schedule) and hung start (weak starter)
    hot_ctrl = ptr.Control(**{**ctrl.__dict__, "accel_limit": ctrl.accel_limit * 1.5})
    hs = ptr.simulate(E, amb, hot_ctrl, sched, 0.03, ctrl.idle_frac, t_end=25.0, dt=dt, starter=True)
    results["hot_start"] = dict(T04_peak=max(hs["hist"]["T04"]), over_limit=max(hs["hist"]["T04"]) > ctrl.T04_limit)
    hung_ctrl = ptr.Control(**{**ctrl.__dict__, "starter_torque_Nm": 0.5 * ctrl.starter_torque_Nm})
    hg = ptr.simulate(E, amb, hung_ctrl, sched, 0.03, ctrl.idle_frac, t_end=25.0, dt=dt, starter=True)
    results["hung_start"] = dict(final_N_frac=hg["final_N_frac"], self_sustain_s=hg["events"].get("self_sustain_s"),
                                 hung=hg["final_N_frac"] < ctrl.self_sustain_frac + 0.05)
    # ---- governor failure: fuel at the accel limit from 100 %
    gf = ptr.simulate(E, amb, ctrl, sched, 1.0, 1.0, t_end=6.0, dt=dt, governor_fail=True, x0=ac["x"])
    results["overspeed"] = dict(N_peak_frac=max(gf["hist"]["N_frac"]), T04_peak=max(gf["hist"]["T04"]),
                                time_to_105pct_s=next((t for t, n in zip(gf["hist"]["t"], gf["hist"]["N_frac"]) if n >= 1.05), None))
    # ---- flameout at 60 % and windmilling
    fo = ptr.simulate(E, amb, ctrl, sched, 0.6, 0.6, t_end=20.0, dt=dt, fuel_on=False, x0=x_idle)
    Nw = fo["hist"]["N_frac"][-1]
    relight_possible = Nw >= ctrl.light_off_N_frac
    results["flameout"] = dict(windmill_N_frac=Nw, decay_to_light_off_s=next((t for t, n in zip(fo["hist"]["t"], fo["hist"]["N_frac"])
                                                                            if n <= ctrl.light_off_N_frac), None),
                               relight_possible_at_M=relight_possible, flight_mach=amb.M0)
    ddir = doc.get("_design_dir")
    plots = _plot(st, ac, de, Path(ddir) / "analysis") if bool(g("plots")) and ddir else {}
    rules = [
        check("TRN-1", "start reaches idle", 1.0 if results["start"]["ok"] else 0.0, 1.0, "min", "start sequence simulation", warn_margin=0.0,
              note="more starter torque, earlier light-off or richer start schedule"),
        check("TRN-2", "start light-off to self-sustain time", (results["start"]["self_sustain_s"] or 99) - (results["start"]["light_off_s"] or 0),
              8.0, "max", "micro-turbojet practice 3-8 s", unit="s", hard=False),
        check("TRN-3", "slam acceleration idle -> 95 % time", results["accel"]["t_95pct_s"] if results["accel"]["ok"] else None, 6.0, "max",
              "class practice 3-6 s (JetCat ~4 s)", unit="s", hard=False, note="raise the accel limiter (watch SM)"),
        check("TRN-4", "minimum surge margin during the slam acceleration", results["accel"]["SM_min"], 0.05, "min",
              "transient excursion toward surge; surge line uncertainty +/-30 %", note="lower accel_limit or add bleed"),
        check("TRN-5", "T04 peak during acceleration vs limit", results["accel"]["T04_peak"], ctrl.T04_limit, "max",
              "over-temperature limiter (the limiter holds the peak at the limit)", unit="K", warn_margin=0.0),
        check("TRN-6", "deceleration 100 % -> idle time", results["decel"]["t_to_idle_s"] if results["decel"]["ok"] else None, 8.0, "max",
              "class practice", unit="s", hard=False),
        check("TRN-7", "hot start T04 peak (schedule x1.5)", results["hot_start"]["T04_peak"], ctrl.T04_limit + 100, "max",
              "abnormal case: rich start", unit="K", hard=False),
        check("TRN-8", "hung start with half starter torque avoided", 0.0 if results["hung_start"]["hung"] else 1.0, 1.0, "min",
              "abnormal case", hard=False, warn_margin=0.0, note="starter torque margin is thin"),
        check("TRN-9", "overspeed on governor failure (peak N / design)", results["overspeed"]["N_peak_frac"], 1.15, "max",
              "burst margin 1.2 x MCS must cover the overspeed reached before the fuel cut", hard=False),
    ]
    return dict(control=ctrl.__dict__, scenarios=results, I_rotor=E.I_rotor, plots=plots, _rules=rules)


def _plot(st, ac, de, adir: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    adir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
    for a, (name, r) in zip(ax, (("start", st), ("slam accel", ac), ("decel", de))):
        h = r["hist"]
        a.plot(h["t"], h["N_frac"], "k-", label="N/N_design")
        a2 = a.twinx()
        a2.plot(h["t"], h["T04"], "r-", lw=1, label="T04 [K]")
        a2.plot(h["t"], [100 * s if s == s else float("nan") for s in h["SM"]], "b--", lw=1, label="SM [%]")
        a.set_title(name); a.set_xlabel("t [s]"); a.set_ylabel("N/N_design"); a.grid(alpha=.3)
        a2.set_ylabel("T04 [K] / SM [%]")
        a.legend(loc="upper left", fontsize=8); a2.legend(loc="lower right", fontsize=8)
    fig.suptitle("Transients (L2 maps, quasi-steady components)")
    p = adir / "transients.png"; fig.tight_layout(); fig.savefig(p, dpi=110); plt.close(fig)
    return {"transients": str(p)}
