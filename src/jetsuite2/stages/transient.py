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

from ..perf import matching, transient as ptr, closs
from ..rules import check
from .. import uncertainty as unc
from .common import inp, out
from .offdesign import engine_from_doc

TIER = "L2"
CORE = False

DEFAULTS = {
    "accel_limit": 1.3, "decel_limit": 0.45, "T04_limit": 1200.0, "N_max_frac": 1.05, "idle_frac": 0.50,
    "fuel_ramp_s": 0.3, "starter_torque_Nm": 0.5, "starter_cutoff_frac": 0.35, "light_off_N_frac": 0.10,
    "self_sustain_frac": 0.22, "dt_s": 0.05, "plots": True, "workers": 3,
    "_doc": {"accel_limit": "acceleration limiter: max Wf/P3 as a multiple of the steady schedule",
             "decel_limit": "deceleration floor: min Wf/P3 as a fraction of the steady schedule (lean blow-out)",
             "T04_limit": "over-temperature limiter [K]", "N_max_frac": "overspeed governor / design speed",
             "idle_frac": "idle speed / design speed", "fuel_ramp_s": "fuel system first-order lag [s]",
             "starter_torque_Nm": "starter motor torque [N m] up to the cutoff speed", "starter_cutoff_frac": "starter cutoff speed / design",
             "light_off_N_frac": "speed at which ignition is attempted / design", "self_sustain_frac": "expected self-sustaining speed / design",
             "dt_s": "integration time step [s]", "plots": "write transient plots", "workers": "process-pool workers for the independent start scenarios (1 = serial)"},
}

READS = ["inputs.transient.*", "inputs.cycle.*", "outputs.maps.compressor_map", "outputs.maps.turbine_map",
         "outputs.speed.rpm", "outputs.cycle.*", "outputs.requirements.altitude_m", "outputs.requirements.mach",
         "outputs.requirements.dT_isa_K", "outputs.rotor.Ip_impeller", "outputs.rotor.Ip_turbine",
         "outputs.offdesign.running_line", "outputs.offdesign.steady_schedule", "outputs.control.*"]


def _sim_job(args):
    """Process-pool entry: one simulate() call (module-level for pickling)."""
    E, amb, ctrl, sched, N0, target, t_end, dt, kw = args
    return ptr.simulate(E, amb, ctrl, sched, N0, target, t_end=t_end, dt=dt, **kw)


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "transient", k, DEFAULTS[k])  # noqa: E731
    E = engine_from_doc(doc)
    req = out(doc, "requirements")
    amb = matching.Ambient.at(req["altitude_m"], req["mach"], req["dT_isa_K"])
    # the controller comes from the control stage (schedules); the legacy per-stage limiter inputs only apply
    # when no control stage output exists
    if E.sched is not None and doc["outputs"].get("control"):
        ctrl = ptr.controller_from_schedules(E.sched)
        ctrl.self_sustain_frac = float(g("self_sustain_frac"))
    else:
        ctrl = ptr.Control(accel_limit=float(g("accel_limit")), decel_limit=float(g("decel_limit")), T04_limit=float(g("T04_limit")),
                           N_max_frac=float(g("N_max_frac")), idle_frac=float(g("idle_frac")), fuel_ramp_s=float(g("fuel_ramp_s")),
                           light_off_N_frac=float(g("light_off_N_frac")), starter_torque_Nm=float(g("starter_torque_Nm")),
                           starter_cutoff_frac=float(g("starter_cutoff_frac")), self_sustain_frac=float(g("self_sustain_frac")))
    dt = float(g("dt_s"))
    cached = (doc["outputs"].get("offdesign") or {}).get("steady_schedule")
    if cached and len(cached.get("N", [])) >= 6 and min(cached["N"]) <= 0.46 and max(cached["N"]) >= 1.0:
        sched = cached                                           # same engine, same ambient (offdesign runs at the design condition)
    else:
        sched = ptr.steady_schedule(E, amb, [0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.05])
    if len(sched["N"]) < 4:
        raise RuntimeError("steady schedule did not converge on enough speeds")
    results = {}
    Tt2, Pt2, _ = amb.ram(E.intake_rec)
    from ..perf.maps import corr_flow as _cf

    def _traj(h, step=4):
        """Compressor-map trajectory (corrected flow, PR, SM, N) thinned for storage."""
        return dict(t=h["t"][::step], N_frac=h["N_frac"][::step],
                    W_corr=[_cf(w, Tt2, Pt2) for w in h["W"][::step]],
                    PR_c=[p / Pt2 for p in h["P3"][::step]], SM=h["SM"][::step])
    trajectories = {}
    # ---- start, hot start and hung start are independent 25 s simulations: run them concurrently
    hot_ctrl = ptr.Control(**{**ctrl.__dict__, "accel_limit": ctrl.accel_limit * 1.5})
    E_hot = matching.EngineModel(**{**E.__dict__})
    if E.sched is not None:
        import copy as _copy
        sh = _copy.deepcopy(E.sched); sh._acc = sh._acc * 1.5; sh.start_ramp_rate = sh.start_ramp_rate * 2.0
        E_hot.sched = sh
    hung_ctrl = ptr.Control(**{**ctrl.__dict__, "starter_torque_Nm": 0.5 * ctrl.starter_torque_Nm})
    jobs = {"start": (E, amb, ctrl, sched, 0.03, ctrl.idle_frac, 25.0, dt, dict(starter=True)),
            "hot": (E_hot, amb, hot_ctrl, sched, 0.03, ctrl.idle_frac, 25.0, dt, dict(starter=True)),
            "hung": (E, amb, hung_ctrl, sched, 0.03, ctrl.idle_frac, 25.0, dt, dict(starter=True))}
    workers = int(g("workers"))
    pool = None
    futs = {}
    if workers > 1:
        try:
            from concurrent.futures import ProcessPoolExecutor
            pool = ProcessPoolExecutor(max_workers=min(workers, 3))
            futs = {k: pool.submit(_sim_job, v) for k, v in jobs.items()}
        except Exception:  # noqa: BLE001
            pool = None
    def _get(k):
        return futs[k].result() if pool is not None else _sim_job(jobs[k])
    st = _get("start")
    trajectories["start"] = _traj(st["hist"])
    h = st["hist"]
    t_idle = next((t for t, n in zip(h["t"], h["N_frac"]) if n >= 0.98 * ctrl.idle_frac), None)
    results["start"] = dict(light_off_s=st["events"].get("light_off_s"), self_sustain_s=st["events"].get("self_sustain_s"),
                            idle_capture_s=t_idle, T04_peak=max(h["T04"]), EGT_peak=max(h["EGT"]), final_N_frac=st["final_N_frac"],
                            ok=t_idle is not None)
    x_idle = st["x"]
    # ---- slam acceleration idle -> 100 %
    ac = ptr.simulate(E, amb, ctrl, sched, ctrl.idle_frac, 1.0, t_end=12.0, dt=dt, x0=x_idle)
    trajectories["accel"] = _traj(ac["hist"])
    h = ac["hist"]
    t95 = next((t for t, n in zip(h["t"], h["N_frac"]) if n >= 0.95), None)
    sm = [s for s in h["SM"] if s == s]
    # band at the minimum-SM instant of the slam: rig + igv extrapolation (if the IGV is scheduled there) + transient model form
    i_min = int(np.nanargmin(np.array(h["SM"], float))) if sm else 0
    Nc_min = h["N_frac"][i_min] * (E.N_design / math.sqrt(Tt2 / 288.15)) / E.cmap.Nc_design
    igv_at = E.sched.igv(Nc_min) if E.sched is not None else 0.0
    band_accel = unc.surge_band(igv=unc.igv_term(E.cmap, Nc_min, _cf(h["W"][i_min], Tt2, Pt2), h["P3"][i_min] / Pt2, igv_at),
                                lowspeed=Nc_min < float(E.cmap.N.min()) - 1e-9, transient=True)
    results["accel"] = dict(t_95pct_s=t95, SM_min=min(sm) if sm else None, T04_peak=max(h["T04"]), Fn_final=h["Fn"][-1],
                            SM_min_N_frac=h["N_frac"][i_min], SM_min_band=band_accel,
                            ok=t95 is not None)
    # ---- deceleration 100 % -> idle
    de = ptr.simulate(E, amb, ctrl, sched, 1.0, ctrl.idle_frac, t_end=12.0, dt=dt, x0=ac["x"])
    trajectories["decel"] = _traj(de["hist"])
    h = de["hist"]
    t_dec = next((t for t, n in zip(h["t"], h["N_frac"]) if n <= 1.02 * ctrl.idle_frac), None)
    results["decel"] = dict(t_to_idle_s=t_dec, Wf_min=min(h["Wf"]), T04_min=min(h["T04"]), ok=t_dec is not None)
    # ---- hot start (rich schedule) and hung start (weak starter): results from the pool
    hs = _get("hot")
    results["hot_start"] = dict(T04_peak=max(hs["hist"]["T04"]), over_limit=max(hs["hist"]["T04"]) > ctrl.T04_limit)
    hg = _get("hung")
    if pool is not None:
        pool.shutdown(wait=True)
    results["hung_start"] = dict(final_N_frac=hg["final_N_frac"], self_sustain_s=hg["events"].get("self_sustain_s"),
                                 hung=hg["final_N_frac"] < ctrl.self_sustain_frac + 0.05)
    # ---- sensor-loss fallbacks (ECU logic): P3 sensor lost -> N-only fuel schedule with the accel line x0.8;
    #      EGT / T04 sensor lost -> accel line x0.8 and the T04 limit lowered 50 K (the ceiling still acts on the model T04)
    p3 = ptr.simulate(E, amb, ctrl, sched, ctrl.idle_frac, 1.0, t_end=12.0, dt=dt, x0=x_idle, p3_sensor_lost=True, accel_derate=0.8)
    hp = p3["hist"]; smp = [s_ for s_ in hp["SM"] if s_ == s_]
    results["p3_sensor_loss"] = dict(SM_min=min(smp) if smp else None, T04_peak=max(hp["T04"]),
                                     t_95pct_s=next((t for t, n in zip(hp["t"], hp["N_frac"]) if n >= 0.95), None), ok=True)
    trajectories["accel_p3_lost"] = _traj(hp)
    ctrl_d = ptr.Control(**{**ctrl.__dict__, "T04_limit": ctrl.T04_limit - 50.0})
    dr = ptr.simulate(E, amb, ctrl_d, sched, ctrl.idle_frac, 1.0, t_end=12.0, dt=dt, x0=x_idle, accel_derate=0.8)
    hd = dr["hist"]; smd = [s_ for s_ in hd["SM"] if s_ == s_]
    results["egt_derate"] = dict(SM_min=min(smd) if smd else None, T04_peak=max(hd["T04"]), Fn_final=hd["Fn"][-1],
                                 t_95pct_s=next((t for t, n in zip(hd["t"], hd["N_frac"]) if n >= 0.95), None), ok=True)
    # ---- IGV actuator failure (if IGVs are fitted): slam acceleration with the vanes stuck at the failure position
    ctl_out = doc["outputs"].get("control", {}) or {}
    if E.sched is not None and E.sched.enabled.get("igv"):
        import copy as _copy
        sh_f = _copy.deepcopy(E.sched)
        sh_f._igv = np.full_like(sh_f.N, float(ctl_out.get("igv_fail_deg", 0.0)))
        E_f = matching.EngineModel(**{**E.__dict__, "sched": sh_f})
        sched_f = ptr.steady_schedule(E_f, amb, [0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.05])
        if len(sched_f["N"]) >= 4:
            idle_f = ptr.simulate(E_f, amb, ctrl, sched_f, ctrl.idle_frac, ctrl.idle_frac, t_end=3.0, dt=dt)
            af = ptr.simulate(E_f, amb, ctrl, sched_f, ctrl.idle_frac, 1.0, t_end=12.0, dt=dt, x0=idle_f["x"])
            trajectories["accel_igv_failed"] = _traj(af["hist"])
            hf = af["hist"]; smf = [s for s in hf["SM"] if s == s]
            results["igv_failed"] = dict(position=ctl_out.get("igv_fail_position"), igv_deg=float(ctl_out.get("igv_fail_deg", 0.0)),
                                         SM_min=min(smf) if smf else None, SM_idle=(idle_f["hist"]["SM"][-1] if idle_f["hist"]["SM"] else None),
                                         t_95pct_s=next((t for t, n in zip(hf["t"], hf["N_frac"]) if n >= 0.95), None),
                                         Fn_final=hf["Fn"][-1], ok=True)
        else:
            results["igv_failed"] = dict(position=ctl_out.get("igv_fail_position"), SM_min=None, ok=False, note="no steady running line with the IGV failed")
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
        unc.annotate_rule(check("TRN-4", "minimum surge margin during the slam acceleration", results["accel"]["SM_min"], 0.05, "min",
              f"transient excursion toward surge at N {results['accel']['SM_min_N_frac']:.2f}; band +/-{band_accel['total']:.3f} = {unc.format_terms(band_accel)}",
              warn_margin=band_accel["total"] / 0.05, note="lower accel_limit or add bleed"), band_accel),
        check("TRN-5", "T04 peak during acceleration vs limit", results["accel"]["T04_peak"], ctrl.T04_limit, "max",
              "over-temperature limiter (the limiter holds the peak at the limit)", unit="K", warn_margin=0.0),
        check("TRN-6", "deceleration 100 % -> idle time", results["decel"]["t_to_idle_s"] if results["decel"]["ok"] else None, 8.0, "max",
              "class practice", unit="s", hard=False),
        check("TRN-7", "hot start T04 peak (schedule x1.5)", results["hot_start"]["T04_peak"], ctrl.T04_limit + 100, "max",
              "abnormal case: rich start", unit="K", hard=False),
        check("TRN-8", "hung start with half starter torque avoided", 0.0 if results["hung_start"]["hung"] else 1.0, 1.0, "min",
              "abnormal case", hard=False, warn_margin=0.0, note="starter torque margin is thin"),
        unc.annotate_rule(check("TRN-10", "surge margin with the IGV actuator failed (slam accel, vanes at the failure position)",
              results.get("igv_failed", {}).get("SM_min") if results.get("igv_failed") else None, 0.0, "min",
              f"failed-{results.get('igv_failed', {}).get('position', '-')} IGV at {results.get('igv_failed', {}).get('igv_deg', 0.0):.0f} deg; "
              f"band +/-{unc.surge_band(transient=True)['total']:.3f} = {unc.format_terms(unc.surge_band(transient=True))}", hard=False,
              warn_margin=0.0,
              note="the engine must at least not surge with a stuck IGV: fail-closed (pre-swirl kept) or a bleed interlock"),
              unc.surge_band(transient=True)),
        check("TRN-11", "slam accel with the P3 sensor lost (N-only schedule, accel x0.8): surge margin", results["p3_sensor_loss"]["SM_min"], 0.0, "min",
              f"ECU fallback; T04 peak {results['p3_sensor_loss']['T04_peak']:.0f} K, t95 {results['p3_sensor_loss']['t_95pct_s']}", hard=False, warn_margin=0.0,
              note="the N-only schedule must stay below the surge line without the P3 feedback: derate more or add a bleed interlock"),
        check("TRN-12", "slam accel with the EGT sensor lost (accel x0.8, T04 limit -50 K): time to 95 %", results["egt_derate"]["t_95pct_s"] or 99.0, 12.0, "max",
              f"derated acceleration must still reach 95 % within the run; T04 peak {results['egt_derate']['T04_peak']:.0f} K", unit="s", hard=False),
        check("TRN-9", "overspeed on governor failure (peak N / design)", results["overspeed"]["N_peak_frac"], 1.15, "max",
              "burst margin 1.2 x MCS must cover the overspeed reached before the fuel cut", hard=False),
    ]
    return dict(control=ctrl.__dict__, scheduled=bool(E.sched is not None and doc["outputs"].get("control")),
                schedules_enabled=(E.sched.enabled if E.sched is not None else {}), scenarios=results, trajectories=trajectories, I_rotor=E.I_rotor,
                plots=plots, _rules=rules)


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
