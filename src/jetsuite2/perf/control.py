"""Schedules: the controller's tables (from the ``control`` stage) as callables of
corrected speed fraction, plus a no-schedule default for 'unscheduled' comparisons."""
from __future__ import annotations

import numpy as np


class Schedules:
    def __init__(self, ctrl: dict | None):
        c = ctrl or {}
        self.N = np.array(c.get("N_grid", [0.2, 1.1]), float)
        self._bleed = np.array(c.get("bleed_frac", [0.0, 0.0]), float)
        self._a8 = np.array(c.get("A8_ratio", [1.0, 1.0]), float)
        self._igv = np.array(c.get("igv_deg", [0.0, 0.0]), float)
        self._acc = np.array(c.get("accel_mult", [1.3, 1.3]), float)
        self._dec = np.array(c.get("decel_mult", [0.45, 0.45]), float)
        self.idle_N = float(c.get("idle_N", 0.5))
        self.N_max_frac = float(c.get("N_max_frac", 1.05))
        self.T04_limit = float(c.get("T04_limit_K", 1200.0))
        self.fuel_lag = float(c.get("fuel_lag_s", 0.3))
        self.gain = float(c.get("governor_gain", 8.0))
        st = c.get("start", {})
        self.light_off_N = float(st.get("light_off_N", 0.10))
        self.starter_cutoff_N = float(st.get("starter_cutoff_N", 0.35))
        self.start_ramp_rate = float(st.get("ramp_rate", 0.25))
        self.starter_torque = float(st.get("starter_torque_Nm", 0.5))
        self.enabled = dict(bleed=bool(c.get("bleed_enabled", False)), nozzle=bool(c.get("nozzle_variable", False)),
                            igv=bool(c.get("igv_enabled", False)))

    def _i(self, tab, Nc):
        return float(np.interp(Nc, self.N, tab))

    def bleed(self, Nc): return self._i(self._bleed, Nc)
    def a8(self, Nc): return self._i(self._a8, Nc)
    def igv(self, Nc): return self._i(self._igv, Nc)
    def accel(self, Nc): return self._i(self._acc, Nc)
    def decel(self, Nc): return self._i(self._dec, Nc)

    def unscheduled(self) -> "Schedules":
        """Same limiters and governor, but bleed closed, nozzle at design, IGV open."""
        u = Schedules(None)
        u.N, u._acc, u._dec = self.N, self._acc, self._dec
        u.idle_N, u.N_max_frac, u.T04_limit, u.fuel_lag, u.gain = self.idle_N, self.N_max_frac, self.T04_limit, self.fuel_lag, self.gain
        u.light_off_N, u.starter_cutoff_N, u.start_ramp_rate, u.starter_torque = self.light_off_N, self.starter_cutoff_N, self.start_ramp_rate, self.starter_torque
        u._bleed = np.zeros_like(self.N); u._a8 = np.ones_like(self.N); u._igv = np.zeros_like(self.N)
        return u
