"""Analysis stage - rotordynamics campaign (L2).

Builds on the rotor stage's two-plane beam model (``jetsuite2.rotordyn``):

* Campbell diagram: forward/backward whirl frequencies vs spin speed with
  the 1x and the impeller / diffuser / NGV / turbine-blade passing orders;
* critical-speed map: forward criticals vs bearing support stiffness;
* unbalance response: synchronous amplitude at the impeller and turbine for
  the ISO 1940 G2.5 residual unbalance with the support damping (API 684
  amplification factor at the criticals);
* blade natural frequencies vs engine-order excitation (impeller exducer
  cantilever plate, turbine blade cantilever beam) with the resonance
  crossings inside the operating range (Campbell / SAFE-diagram screening).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.linalg import solve

from ..library import materials
from ..rotordyn import RotorModel
from ..rules import check
from .common import inp, out
from . import rotor as rotor_stage

TIER = "L2"
CORE = False

DEFAULTS = {
    "support_stiffness_sweep": [5e5, 1e6, 2e6, 5e6, 1e7, 2e7, 5e7, 1e8],
    "support_damping_N_s_m": 800.0,
    "balance_grade_G": 2.5,
    "n_speeds": 60,
    "plots": True,
    "_doc": {"support_stiffness_sweep": "bearing support stiffness values for the critical-speed map [N/m]",
             "support_damping_N_s_m": "viscous damping of each support [N s/m] (O-ring / squeeze film)",
             "balance_grade_G": "ISO 1940 balance quality grade for the unbalance response", "n_speeds": "Campbell speed points",
             "plots": "write plots"},
}

READS = ["inputs.rotordyn.*", "inputs.rotor.*", "outputs.rotor.*", "outputs.compressor.*", "outputs.turbine.*",
         "outputs.speed.*", "outputs.layout.*", "outputs.combustor.Ri_m", "outputs.cycle.P_turb_W", "outputs.speed.journal_d_min_mm"]


def _build_model(doc: dict, k_sup: float, extra=None):
    """Re-assemble the rotor stage's beam model (same segments, masses, inertias) for a given support stiffness."""
    d2 = {"inputs": {**doc["inputs"], "rotor": {**doc["inputs"].get("rotor", {}), "support_stiffness_N_m": k_sup}},
          "outputs": doc["outputs"]}
    # rotor.run exposes the model through a hook: rebuild by calling the stage with a capture flag
    cap = {}
    out_ = rotor_stage.run(d2, _capture=cap) if "_capture" in rotor_stage.run.__code__.co_varnames else None
    return cap.get("model"), cap, out_


def run(doc: dict) -> dict:
    g = lambda k: inp(doc, "rotordyn", k, DEFAULTS[k])  # noqa: E731
    ro, c, t, sp = out(doc, "rotor"), out(doc, "compressor"), out(doc, "turbine"), out(doc, "speed")
    k_nom = float(doc["inputs"].get("rotor", {}).get("support_stiffness_N_m", 1e7))
    model, cap, _ = _build_model(doc, k_nom)
    if model is None:
        raise RuntimeError("rotor stage does not expose its beam model")
    rpm_mcs = sp["rpm_mcs"]
    # ---- Campbell diagram
    n_sp = int(g("n_speeds"))
    speeds = np.linspace(0.05, 1.6, n_sp) * rpm_mcs
    camp = dict(rpm=[], forward=[], backward=[])
    for s in speeds:
        w = model.whirl(s * 2 * math.pi / 60, n_modes=6)
        fw = [f * 60 / (2 * math.pi) for f, is_f, fr in w if is_f][:3]
        bw = [f * 60 / (2 * math.pi) for f, is_f, fr in w if not is_f][:3]
        camp["rpm"].append(float(s)); camp["forward"].append(fw); camp["backward"].append(bw)
    # ---- critical speed map vs support stiffness
    csm = []
    for k in g("support_stiffness_sweep"):
        m_k, cap_k, _ = _build_model(doc, float(k))
        crits = m_k.critical_speeds(2.0 * rpm_mcs * 2 * math.pi / 60, n_scan=24)
        csm.append(dict(k=float(k), criticals_rpm=[cw * 60 / (2 * math.pi) for cw, fwd, fr in crits],
                        rigid=[cw * 60 / (2 * math.pi) for cw, fwd, fr in crits if fr > 0.5],
                        bending=[cw * 60 / (2 * math.pi) for cw, fwd, fr in crits if fr <= 0.5]))
    # ---- unbalance response (synchronous): [K - w^2 M + i w (C + w G)] q = w^2 U
    G_grade = float(g("balance_grade_G"))
    c_sup = float(g("support_damping_N_s_m"))
    m_imp, m_tur = ro["m_impeller_kg"], ro["m_turbine_kg"]
    n_imp, n_tur = cap["nodes"]["impeller"], cap["nodes"]["turbine"]
    n_fb, n_rb = cap["nodes"]["front_bearing"], cap["nodes"]["rear_bearing"]
    n = model.n
    resp = dict(rpm=[], x_imp_um=[], x_tur_um=[], F_fb_N=[], F_rb_N=[])
    e_per = G_grade * 1e-3 / (sp["omega_rad_s"])        # permissible eccentricity [m] (G = e w)
    U_imp, U_tur = m_imp * e_per, m_tur * e_per          # residual unbalance [kg m], worst case in phase
    for s in np.linspace(0.1, 1.3, 40) * rpm_mcs:
        w = s * 2 * math.pi / 60
        K = model.K.astype(complex); M = model.M; Gm = model.G
        Cd = np.zeros_like(K)
        for nd in (n_fb, n_rb):
            for d in (2 * nd, 2 * n + 2 * nd):
                Cd[d, d] += c_sup
        A = K - w * w * M + 1j * w * (Cd + w * Gm)
        F = np.zeros(4 * n, dtype=complex)
        F[2 * n_imp] += U_imp * w * w; F[2 * n + 2 * n_imp] += -1j * U_imp * w * w
        F[2 * n_tur] += U_tur * w * w; F[2 * n + 2 * n_tur] += -1j * U_tur * w * w
        q = solve(A, F)
        resp["rpm"].append(float(s))
        resp["x_imp_um"].append(float(abs(q[2 * n_imp]) * 1e6)); resp["x_tur_um"].append(float(abs(q[2 * n_tur]) * 1e6))
        resp["F_fb_N"].append(float(abs(k_nom * q[2 * n_fb] + 1j * w * c_sup * q[2 * n_fb])))
        resp["F_rb_N"].append(float(abs(k_nom * q[2 * n_rb] + 1j * w * c_sup * q[2 * n_rb])))
    x_max = max(max(resp["x_imp_um"]), max(resp["x_tur_um"]))
    # amplification factor at the first response peak (half-power)
    xi = np.array(resp["x_imp_um"]); rr = np.array(resp["rpm"])
    ip = int(np.argmax(xi)); AF = None
    if 0 < ip < len(xi) - 1:
        half = xi[ip] / math.sqrt(2)
        lo = rr[max(np.where(xi[:ip] <= half)[0].max(), 0)] if np.any(xi[:ip] <= half) else rr[0]
        hi = rr[ip + np.where(xi[ip:] <= half)[0].min()] if np.any(xi[ip:] <= half) else rr[-1]
        AF = float(rr[ip] / max(hi - lo, 1e-6))
    # ---- blade natural frequencies vs engine orders
    mat_c = materials.get(c["material"]); mat_t = materials.get(t["material"])
    b2, t_root, t_tip = c["b2_m"], c["t_root_m"], c["t_tip_m"]
    t_eff = 0.5 * (t_root + t_tip)
    # exducer: cantilever plate strip of span b2 (first bending, clamped-free): f = (1.875^2/(2 pi L^2)) sqrt(E I/(rho A)) = 0.1615 t/L^2 sqrt(E/rho)
    f_exd = 0.1615 * t_eff / b2 ** 2 * math.sqrt(mat_c["E"] / mat_c["rho"]) * 1.15   # +15 % taper stiffening
    f_exd2 = 6.27 * f_exd                                                            # second bending
    # turbine blade: cantilever beam, thickness ~ tmax, length = blade height
    h_b = t["h_rotor_m"]; tb = t["tmax_over_c_rotor"] * t["chord_rotor_m"]
    f_tb = 0.1615 * tb / h_b ** 2 * math.sqrt(mat_t["E"] / mat_t["rho"]) * 1.1
    f_tb *= math.sqrt(1 + 0.25 * (sp["omega_rad_s"] / (2 * math.pi * f_tb)) ** 2) if f_tb > 0 else 1.0   # centrifugal stiffening (Southwell)
    orders = {"impeller 1x": 1, "diffuser vanes": int(c["n_vanes"] or 0), "NGV count": int(t["n_ngv"]), "rotor blades": int(t["n_rotor"]),
              "main blades": int(c["n_main"]), "main+splitter": int(c["n_main"] + c["n_splitter"])}
    idle_rpm, max_rpm = 0.35 * sp["rpm"], rpm_mcs
    crossings = []
    for bname, f in (("impeller exducer mode 1", f_exd), ("impeller exducer mode 2", f_exd2), ("turbine blade mode 1", f_tb)):
        for oname, k in orders.items():
            if k <= 0:
                continue
            rpm_cross = f * 60 / k
            in_range = idle_rpm <= rpm_cross <= max_rpm
            rel = "diffuser vanes" in oname or "NGV" in oname or "1x" in oname
            excites = (("exducer" in bname and ("diffuser" in oname or "1x" in oname)) or
                       ("turbine" in bname and ("NGV" in oname or "1x" in oname)))
            if excites:
                crossings.append(dict(blade=bname, order=oname, k=k, f_Hz=f, rpm=rpm_cross, in_range=in_range,
                                      margin_to_max=(max_rpm - rpm_cross) / max_rpm, margin_to_idle=(rpm_cross - idle_rpm) / idle_rpm))
    in_range = [x for x in crossings if x["in_range"]]
    near_max = [x for x in crossings if abs(x["rpm"] - sp["rpm"]) / sp["rpm"] < 0.10]
    ddir = doc.get("_design_dir")
    plots = _plot(camp, csm, resp, crossings, rpm_mcs, sp["rpm"], ddir) if bool(g("plots")) and ddir else {}
    bend_nom = ro["bending_critical_rpm"]
    rules = [
        check("RD-1", "first forward bending critical / MCS (nominal support)", bend_nom / rpm_mcs, 1.25, "min",
              "API 684 separation margin", note="see the critical-speed map for the stiffness that helps"),
        check("RD-2", "max synchronous vibration amplitude at G2.5 residual unbalance", x_max, 25.0, "max",
              "ISO 1940 G2.5; 25 um pk at the wheels is a common limit for tip clearance/seal rub", unit="um",
              note="better balance grade, more support damping, or move the criticals"),
        check("RD-3", "amplification factor at the first response peak", AF, 8.0, "max", "API 684: AF < 8 for a well-damped critical",
              hard=False, note="add squeeze-film / O-ring damping"),
        check("RD-4", "blade resonance crossings within the operating range", float(len(in_range)), 0.0, "max",
              "Campbell: exducer vs diffuser vane passing, turbine blade vs NGV passing", hard=False, warn_margin=0.0,
              note="; ".join(f"{x['blade']} x {x['order']} at {x['rpm']:.0f} rpm" for x in in_range[:4])),
        check("RD-5", "blade resonance within +/-10 % of the design speed", float(len(near_max)), 0.0, "max",
              "no crossing at the dwell speed", warn_margin=0.0, note="change the vane/NGV count"),
        check("RD-6", "max bearing dynamic load at G2.5 / static capacity C0", max(max(resp["F_fb_N"]), max(resp["F_rb_N"])) / (ro["bearing"]["C0"] * 1e3),
              0.1, "max", "dynamic load should stay a small fraction of C0", hard=False),
    ]
    return dict(campbell=camp, critical_speed_map=csm, unbalance=dict(G=G_grade, e_per_um=e_per * 1e6, U_imp_gmm=U_imp * 1e6,
                U_tur_gmm=U_tur * 1e6, response=resp, x_max_um=x_max, AF_first_peak=AF, damping=c_sup),
                blade_modes=dict(exducer_f1_Hz=f_exd, exducer_f2_Hz=f_exd2, turbine_blade_f1_Hz=f_tb, orders=orders, crossings=crossings),
                plots=plots, _rules=rules)


def _plot(camp, csm, resp, crossings, rpm_mcs, rpm_des, ddir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path
    adir = Path(ddir) / "analysis"; adir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.8))
    rpm = camp["rpm"]
    for i in range(3):
        ax[0].plot(rpm, [f[i] if i < len(f) else float("nan") for f in camp["forward"]], "b-", lw=1, label="forward" if i == 0 else None)
        ax[0].plot(rpm, [f[i] if i < len(f) else float("nan") for f in camp["backward"]], "c--", lw=1, label="backward" if i == 0 else None)
    ax[0].plot(rpm, rpm, "k-", lw=1.5, label="1x")
    ax[0].axvspan(0.35 * rpm_des, rpm_mcs, color="g", alpha=0.08)
    ax[0].set_xlabel("spin speed [rpm]"); ax[0].set_ylabel("whirl frequency [cpm]"); ax[0].set_title("Campbell"); ax[0].legend(fontsize=8)
    ax[0].set_ylim(0, 2.5 * rpm_mcs); ax[0].grid(alpha=.3)
    for e in csm:
        for cr in e["criticals_rpm"]:
            ax[1].plot(e["k"], cr, "ko", ms=3)
    ax[1].axhline(rpm_mcs, color="r", ls="--", label="MCS"); ax[1].axhline(1.25 * rpm_mcs, color="r", ls=":", label="1.25 MCS")
    ax[1].set_xscale("log"); ax[1].set_xlabel("support stiffness [N/m]"); ax[1].set_ylabel("critical speed [rpm]"); ax[1].set_title("critical speed map")
    ax[1].grid(alpha=.3); ax[1].legend(fontsize=8)
    ax[2].plot(resp["rpm"], resp["x_imp_um"], "b-", label="impeller"); ax[2].plot(resp["rpm"], resp["x_tur_um"], "r-", label="turbine")
    ax[2].set_xlabel("rpm"); ax[2].set_ylabel("amplitude [um pk]"); ax[2].set_title("unbalance response (G2.5)"); ax[2].grid(alpha=.3); ax[2].legend(fontsize=8)
    fig.tight_layout(); p = adir / "rotordynamics.png"; fig.savefig(p, dpi=110); plt.close(fig)
    return {"rotordynamics": str(p)}
