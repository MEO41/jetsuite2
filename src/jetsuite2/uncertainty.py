"""Surge-margin uncertainty: named terms, an explicit combination rule, and the arithmetic every
"passes with / without the band" statement must show (work packages C and D).

Terms (all in absolute SAE surge-margin points):

* ``rig``            -- the fixed-geometry stall-model band derived from the HECC / CC3 residuals
                        (``closs.SURGE_BAND_SM``, 0.077).  Derived.
* ``igv``            -- IGV pre-swirl extrapolation.  The stall model was calibrated on fixed-geometry rigs
                        only, and pre-swirl acts on the inducer incidence that *is* the low-speed stall
                        criterion.  Term = ``IGV_EXTRAPOLATION_FRACTION`` x |SM(igv) - SM(0 deg at the same
                        corrected point)|, i.e. half of the benefit the pre-swirl is credited with.  Declared
                        fraction; zero whenever the IGV is open.
* ``lowspeed``       -- similarity extension below the lowest mapped speed line (``LOWSPEED_EXTENSION_SM``).
                        Declared; zero on mapped speed lines.
* ``transient``      -- quasi-steady component matching in a transient (no volume dynamics, no heat-soak
                        effect on the compressor).  ``TRANSIENT_MODEL_FORM_SM``.  Declared, pending test data.

Combination: root-sum-square.  The terms are independent error sources (a rig-fit residual, a
model-form extrapolation, a dynamics simplification) with no common cause, and none is a bias of
known sign, so RSS is the consistent choice; linear addition would be the choice only if they were
correlated or one-sided, and worst-case is reserved for hard limits (burst, overspeed).  The dominant
term is always named so the reader knows which datum would shrink the band.
"""
from __future__ import annotations

import math

from .perf import closs

IGV_EXTRAPOLATION_FRACTION = 0.5     # declared: half of the credited pre-swirl benefit
LOWSPEED_EXTENSION_SM = 0.03        # declared: similarity extension below the lowest mapped line
TRANSIENT_MODEL_FORM_SM = 0.03      # declared: quasi-steady matching in a transient, pending test data
COMBINATION = "RSS"


def igv_term(cmap, Nc_frac: float, W_corr: float, PR: float, igv_deg: float) -> float:
    """Extrapolation term at one corrected point: fraction of the SM benefit credited to the pre-swirl."""
    if not igv_deg or cmap is None:
        return 0.0
    try:
        sm_igv = cmap.surge_margin(Nc_frac, W_corr, PR, igv_deg)
        sm_0 = cmap.surge_margin(Nc_frac, W_corr, PR, 0.0)
    except TypeError:
        return 0.0
    return IGV_EXTRAPOLATION_FRACTION * abs(sm_igv - sm_0)


def surge_band(igv: float = 0.0, lowspeed: bool = False, transient: bool = False) -> dict:
    """Combined band with its terms.  Returns total, terms, dominant term and the rule used."""
    terms = {"rig (HECC/CC3 residuals, derived)": float(closs.SURGE_BAND_SM)}
    if igv > 0:
        terms["igv extrapolation (0.5 x credited pre-swirl benefit, declared)"] = float(igv)
    if lowspeed:
        terms["low-speed similarity extension (declared)"] = LOWSPEED_EXTENSION_SM
    if transient:
        terms["transient quasi-steady model form (declared)"] = TRANSIENT_MODEL_FORM_SM
    total = math.sqrt(sum(v * v for v in terms.values()))
    dominant = max(terms, key=terms.get)
    return dict(total=total, terms=terms, dominant=dominant, rule=COMBINATION)


def with_band(value: float, limit: float, band: dict) -> dict:
    """The arithmetic behind 'passes nominally / with the band'."""
    lo = value - band["total"]
    return dict(value=value, band=band["total"], value_minus_band=lo, limit=limit,
                pass_nominal=value >= limit, pass_with_band=lo >= limit,
                statement=(f"{value:+.3f} - {band['total']:.3f} = {lo:+.3f} vs limit {limit:.3f}: "
                           f"{'passes' if lo >= limit else 'fails'} with the band"
                           f"{'' if (lo >= limit) == (value >= limit) else (' (passes nominally)' if value >= limit else '')}; "
                           f"dominant term: {band['dominant'].split(' (')[0]} {band['terms'][band['dominant']]:.3f}"))


def annotate_rule(rule: dict, band: dict) -> dict:
    """Attach the band, its terms and the with-band verdict to a surge-margin rule record."""
    if rule.get("value") is None or rule.get("limit") is None:
        return rule
    wb = with_band(float(rule["value"]), float(rule["limit"]), band)
    rule["band"] = band["total"]
    rule["band_terms"] = band["terms"]
    rule["band_rule"] = band["rule"]
    rule["band_dominant"] = band["dominant"]
    rule["value_minus_band"] = wb["value_minus_band"]
    rule["pass_with_band"] = wb["pass_with_band"]
    rule["band_statement"] = wb["statement"]
    return rule


def format_terms(band: dict) -> str:
    return " + ".join(f"{k.split(' (')[0]} {v:.3f}" for k, v in band["terms"].items()) + f" ({band['rule']}) = {band['total']:.3f}"
