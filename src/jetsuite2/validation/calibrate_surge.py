"""Calibrate the vaned-diffuser stall criterion on the measured rigs and derive the surge
uncertainty band from the residuals.

    python -m jetsuite2.validation.calibrate_surge [--write]

Cases (validation/data/rigs.json):
  HECC        vaned, 100 % speed: surge at 0.951 W_design (measured, NASA/CR-2014-218114)
  CC3 vaned   design speed: last stable point at 0.939 W_design (NTRS 20140009577 Fig. 2)
  CC3 vaneless design speed: stable to <= 0.72 W_design (Fig. 8) -- must NOT be flagged

Free parameter: STALL_K (Mach slope of the tolerable vane incidence).  STALL_I0 (the
low-Mach limit, +6 deg) is taken from Japikse's diffuser range data and is not fitted
because neither rig exercises low inlet Mach.  The CC3 vane leading-edge angle is not
tabulated in the sources used; it is set to give the same design incidence HECC has
(-4.4 deg), which is stated as an assumption in the results.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from .. import gas
from ..perf import closs

DATA = Path(__file__).with_name("data")


def geom(case: dict, vane_le=None, n_vanes=None, r4=None) -> closs.CompressorGeometry:
    g = dict(case["geometry"])
    g.pop("note", None)
    if vane_le is not None:
        g["vane_le_angle"] = vane_le
    if n_vanes is not None:
        g["n_vanes"] = n_vanes
    if r4 is not None:
        g["r4"] = r4
    if g.get("vane_le_angle") is None:
        g["vane_le_angle"] = 0.0
    if g.get("vane_throat") is None:
        g["vane_throat"] = 0.0
    return closs.CompressorGeometry(**g)


def surge_flow(g, omega, T01, P01, W_design):
    """Highest flow at which any stall indicator trips on the speed line (fraction of W_design),
    and the choke flow."""
    sl = closs.speedline(g, omega, T01, P01, n_pts=40)
    if not sl.get("ok"):
        return None, None, sl.get("reason")
    return sl["stall_indicator_W"], sl["choke_W"], sl["surge_reason"]


def run(write: bool = False) -> dict:
    rigs = json.loads((DATA / "rigs.json").read_text(encoding="utf-8"))
    out = {"cases": {}, "assumptions": []}
    # ------------------------------------------------------------------ HECC (fully sourced)
    h = rigs["hecc"]
    gh = geom(h)
    om = h["design"]["rpm"] * 2 * math.pi / 60
    T01, P01 = h["design"]["T01"], h["design"]["P01"]
    dp = closs.evaluate(gh, h["design"]["W"], om, T01, P01)
    out["cases"]["hecc_design"] = dict(PR_model=dp.PR_tt, PR_meas=h["design"]["PR_tt"], eta_model=dp.eta_tt, eta_meas=h["design"]["eta_tt"],
                                       M3=dp.M3, alpha3=dp.alpha3, incidence_vd=dp.incidence_vd, stall_flag=dp.stall)
    # incidence and M3 at the measured surge flow
    sp = closs.evaluate(gh, h["surge"]["W_last_stable"], om, T01, P01)
    out["cases"]["hecc_surge_point"] = dict(M3=sp.M3, incidence_vd=sp.incidence_vd, alpha3=sp.alpha3, PR_model=sp.PR_tt,
                                            PR_meas=h["surge"]["PR_last_stable"])
    # ---- fit STALL_K so the HECC stall trips at the measured surge incidence / Mach:
    #      i_stall(M3_s) = i_s  ->  K = (I0 - i_s) / (M3_s - 0.5)
    K_fit = (closs.STALL_I0 - sp.incidence_vd) / (sp.M3 - 0.5)
    closs.STALL_K = float(K_fit)
    dp = closs.evaluate(gh, h["design"]["W"], om, T01, P01)       # re-evaluate the design point with the fitted constant
    out["cases"]["hecc_design"].update(stall_flag=dp.stall)
    Ws_h, Wc_h, reason_h = surge_flow(gh, om, T01, P01, h["design"]["W"])
    out["fit"] = dict(STALL_I0=closs.STALL_I0, STALL_K=float(K_fit), fitted_on="hecc surge point",
                      i_stall_at_M3_design=closs.diffuser_stall_incidence(dp.M3))
    out["cases"]["hecc_surge"] = dict(W_pred=Ws_h, W_meas=h["surge"]["W_last_stable"], reason=reason_h,
                                      err_flow=(Ws_h - h["surge"]["W_last_stable"]) / h["design"]["W"] if Ws_h else None,
                                      W_choke_pred=Wc_h, W_choke_meas=h["choke"]["W"],
                                      err_choke=(Wc_h - h["choke"]["W"]) / h["design"]["W"] if Wc_h else None)
    # ------------------------------------------------------------------ CC3 vaned (LE angle assumed)
    c = rigs["cc3_vaned"]
    omc = c["design"]["rpm"] * 2 * math.pi / 60
    Tc, Pc = c["design"]["T01"], c["design"]["P01"]
    g0 = geom(c, vane_le=0.0)
    g0.n_vanes = 0
    d0 = closs.evaluate(g0, c["design"]["W"], omc, Tc, Pc)
    i_hecc_design = dp.incidence_vd
    vane_le = d0.alpha3 - i_hecc_design            # same design incidence as HECC
    A_th = c["design"]["W"] / gas.mass_flow_function(d0.T02, d0.P02 * 0.985, 0.70, 1.0)
    gc = geom(c, vane_le=vane_le)
    gc.vane_throat = A_th / (gc.n_vanes * gc.b3)
    out["assumptions"].append(f"CC3 vane LE angle {vane_le:.2f} deg set for HECC's design incidence ({i_hecc_design:.2f} deg); throat sized for M 0.70")
    dc = closs.evaluate(gc, c["design"]["W"], omc, Tc, Pc)
    Ws_c, Wc_c, reason_c = surge_flow(gc, omc, Tc, Pc, c["design"]["W"])
    out["cases"]["cc3_vaned_design"] = dict(PR_ts_model=dc.PR_ts, PR_ts_meas=c["design"]["PR_ts"], eta_model=dc.eta_tt,
                                            eta_meas=c["design"]["eta_tt"], M3=dc.M3, incidence_vd=dc.incidence_vd, stall_flag=dc.stall)
    out["cases"]["cc3_vaned_surge"] = dict(W_pred=Ws_c, W_meas=c["surge"]["W_last_stable"], reason=reason_c,
                                           err_flow=(Ws_c - c["surge"]["W_last_stable"]) / c["design"]["W"] if Ws_c else None,
                                           W_choke_pred=Wc_c, W_choke_meas=c["choke"]["W"],
                                           err_choke=(Wc_c - c["choke"]["W"]) / c["design"]["W"] if Wc_c else None)
    # ------------------------------------------------------------------ CC3 vaneless (must stay unstalled to 0.72)
    v = rigs["cc3_vaneless"]
    gv = geom(c, vane_le=0.0, n_vanes=0, r4=1.18 * c["geometry"]["r2"])
    Wmin = v["stable_range"]["W_min_measured"]
    pts = []
    for W in np.linspace(Wmin, v["design"]["W"], 8):
        r = closs.evaluate(gv, W, omc, Tc, Pc)
        pts.append(dict(W=W, ok=r.ok, stall=r.stall, alpha3=r.alpha3, M3=r.M3, PR=r.PR_tt, eta=r.eta_tt))
    flagged = [p for p in pts if p["ok"] and p["stall"]]
    out["cases"]["cc3_vaneless"] = dict(points=pts, false_stall_flags=len(flagged),
                                        W_first_flag=min((p["W"] for p in flagged), default=None), W_min_measured=Wmin)
    # ------------------------------------------------------------------ uncertainty band from residuals
    errs = [abs(out["cases"]["hecc_surge"]["err_flow"] or 0), abs(out["cases"]["cc3_vaned_surge"]["err_flow"] or 0)]
    readoff = 0.01        # digitising uncertainty of the CC3 point (fraction of design flow)
    band_flow = math.sqrt(max(errs) ** 2 + readoff ** 2)
    # surge margin (SAE) sensitivity to a flow error: d(SM) ~ (1 + |slope|) dW/W ~ 1.3 dW/W on these steep lines
    band_SM = 1.3 * band_flow
    out["band"] = dict(flow_fraction=band_flow, surge_margin_abs=band_SM, residuals=errs,
                       note="band = rss(max |surge-flow residual|, 1 % read-off); SM band = 1.3 x flow band (absolute, e.g. 0.05 = 5 points of SM)")
    if write:
        (DATA / "surge_calibration.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return out


def main():
    res = run(write="--write" in sys.argv)
    print(json.dumps({k: v for k, v in res.items() if k != "cases"}, indent=1, default=float))
    for k, v in res["cases"].items():
        if k == "cc3_vaneless":
            print(k, "false flags", v["false_stall_flags"], "first flag W", v["W_first_flag"], "of measured stable min", v["W_min_measured"])
            for p in v["points"]:
                print(f"   W {p['W']:.3f} ok {p['ok']} stall '{p['stall']}' alpha3 {p['alpha3']:.1f} M3 {p['M3']:.3f} PR {p['PR']:.3f}")
        else:
            print(k, {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()})


if __name__ == "__main__":
    main()
