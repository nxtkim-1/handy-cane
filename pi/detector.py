"""Turns the raw accelerometer stream into cane events. Pure logic, no hardware, easy to test."""
import math
import numpy as np
import config as C

class CaneDetector:
    def __init__(self, up=(0.0, 0.0, 1.0)):
        self.up = np.array(up, float) / np.linalg.norm(up)
        self.grav = None
        self.dyn_avg = 0.0
        self.tilt = 0.0
        self.last_strike = None
        self.last_impact = -1e9
        self.stumble_candidate = None
        self.last_stumble = -1e9
        self.still_since = None
        self.down = False
        self.up_since = None
        self.parked_since = None
        self.evening = False

    @property
    def upright(self):
        return self.tilt < C.UPRIGHT_MAX_DEG

    @property
    def moving(self):
        return self.dyn_avg > C.STILL_G

    def parked(self, t):
        """Hung on a desk or leaning: stiller than any hand can hold it for 3 s."""
        return self.parked_since is not None and t - self.parked_since > 3

    def update(self, t, ax, ay, az):
        """t in seconds, acceleration in g. Returns a list of (event, info) tuples."""
        a = np.array([ax, ay, az])
        self.grav = a if self.grav is None else 0.95 * self.grav + 0.05 * a
        dyn = float(np.linalg.norm(a - self.grav))
        total = float(np.linalg.norm(a))
        self.dyn_avg = 0.97 * self.dyn_avg + 0.03 * dyn
        g = self.grav / (np.linalg.norm(self.grav) + 1e-9)
        self.tilt = math.degrees(math.acos(max(-1.0, min(1.0, float(g @ self.up)))))
        events = []

        # parked = extremely still
        if self.dyn_avg < C.PARKED_G:
            self.parked_since = self.parked_since or t
        else:
            self.parked_since = None

        if total > C.IMPACT_G:
            self.last_impact = t

        # strikes and stride timing, only while upright and not lying down
        if self.upright and not self.down and dyn > C.STRIKE_G:
            if self.last_strike is None or t - self.last_strike > C.STRIKE_REFRACTORY_S:
                if self.last_strike is not None:
                    interval = t - self.last_strike
                    if C.STRIDE_MIN_S <= interval <= C.STRIDE_MAX_S:
                        events.append(("stride", {"interval": round(interval, 3)}))
                self.last_strike = t

        # stumble: a sharp jolt, then the cane is still upright 2 s later (he caught himself)
        threshold = C.STUMBLE_G * (C.EVENING_STUMBLE_SCALE if self.evening else 1.0)
        if self.upright and dyn > threshold and self.stumble_candidate is None and t - self.last_stumble > 3:
            self.stumble_candidate = (t, dyn)
        if self.stumble_candidate and t - self.stumble_candidate[0] > 2:
            t0, peak = self.stumble_candidate
            self.stumble_candidate = None
            if self.upright and not self.down:
                self.last_stumble = t0
                events.append(("stumble", {"peak_g": round(peak, 2), "evening": self.evening}))

        # cane lying still on the ground
        lying = self.tilt > C.DOWN_MIN_DEG and self.dyn_avg < C.STILL_G
        if not self.down:
            if lying:
                self.still_since = self.still_since or t
                if t - self.still_since > C.DOWN_CONFIRM_S:
                    self.down = True
                    self.up_since = None
                    events.append(("down", {"impact": t - self.last_impact < 3}))
            else:
                self.still_since = None
        else:
            if self.tilt < 45:
                self.up_since = self.up_since or t
                if t - self.up_since > C.PICKUP_CONFIRM_S:
                    self.down = False
                    self.still_since = None
                    self.last_strike = None
                    events.append(("pickup", {}))
            else:
                self.up_since = None
        return events
