"""Potential-fall state machine (MASTER.md 10.1).

Pure logic, no I/O, so it is unit-testable and cannot be blocked by the phone, network or
backend (safety invariant, MASTER 5.2). Feed one sample at a time with update(); the caller
drives the buzzer from `buzzer` and persists any returned Event.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from cane.common.schema import SAMPLE_RATE_HZ


class State(str, Enum):
    MONITORING = "MONITORING"
    IMPACT = "IMPACT"
    CHECK_STILL = "CHECK_STILL"
    PRE_ALERT = "PRE_ALERT"
    ALERT = "ALERT"


@dataclass
class Config:  # all PROPOSED, tune on collected data
    t_impact_g: float = 3.0         # lower to ~1.4 for a +-1.5 g sensor (then tilt/stillness dominate)
    tilt_trigger_deg: float = 60.0
    tilt_window_s: float = 1.0
    upright_recover_s: float = 3.0
    still_std_g: float = 0.05
    still_required_s: float = 10.0
    pre_alert_s: float = 30.0
    long_press_s: float = 3.0


@dataclass
class Event:
    event_id: str
    kind: str          # potential_fall | help_request | impact_only
    outcome: str       # cancelled_by_user | escalated | acknowledged_on_cane
    confidence: float
    peak_g: float
    tilt_deg: float
    still_s: float
    t: float           # seconds (caller's clock) when the event resolved


@dataclass
class FallFSM:
    upright: np.ndarray
    cfg: Config = field(default_factory=Config)
    state: State = State.MONITORING
    buzzer: str = "off"  # off | beep | continuous
    acknowledged_on_cane: bool = False

    def __post_init__(self) -> None:
        self.upright = np.asarray(self.upright, float)
        self.upright = self.upright / np.linalg.norm(self.upright)
        self._w = max(int(self.cfg.tilt_window_s * SAMPLE_RATE_HZ), 2)
        self._tilt_hist: list[float] = []
        self._mag_hist: list[float] = []
        self._btn_down_at: Optional[float] = None
        self._long_fired = False
        self._reset()

    def _reset(self) -> None:
        self._t_entered = 0.0
        self._peak = 0.0
        self._tilt = 0.0
        self._still_s = 0.0
        self._upright_since: Optional[float] = None
        self._still_since: Optional[float] = None

    def _enter(self, s: State, t: float) -> None:
        self.state = s
        self._t_entered = t

    def update(self, t: float, acc: np.ndarray, button: bool) -> Optional[Event]:
        """t: seconds; acc: (3,) in g; button: True while held. Returns an Event when one resolves."""
        acc = np.asarray(acc, float)
        mag = float(np.linalg.norm(acc))
        cosv = float(np.clip(np.dot(acc, self.upright) / (mag or 1e-9), -1, 1))
        tilt = math.degrees(math.acos(cosv))
        self._tilt_hist = (self._tilt_hist + [tilt])[-self._w:]
        self._mag_hist = (self._mag_hist + [mag])[-self._w:]
        full = len(self._mag_hist) >= self._w
        moving = (float(np.std(self._mag_hist)) >= self.cfg.still_std_g) if full else True

        ev = self._handle_button(t, button)
        if ev:
            return ev

        c = self.cfg
        if self.state is State.MONITORING:
            # sudden tilt: was upright at the start of the 1 s window, tilted now
            fell_over = full and self._tilt_hist[0] < c.tilt_trigger_deg and tilt > c.tilt_trigger_deg
            if mag > c.t_impact_g or fell_over:
                self._reset()
                self._peak, self._tilt = mag, tilt
                self._enter(State.IMPACT, t)
        elif self.state is State.IMPACT:
            self._peak = max(self._peak, mag)
            if tilt < c.tilt_trigger_deg:
                if self._upright_since is None:
                    self._upright_since = t
                if t - self._upright_since >= c.upright_recover_s:
                    self._enter(State.MONITORING, t)
            else:
                self._upright_since = None
                self._tilt = tilt
                if t - self._t_entered >= c.upright_recover_s:
                    self._enter(State.CHECK_STILL, t)
        elif self.state is State.CHECK_STILL:
            self._tilt = tilt
            if tilt < c.tilt_trigger_deg and moving:
                self._enter(State.MONITORING, t)
            elif not moving:
                if self._still_since is None:
                    self._still_since = t
                self._still_s = t - self._still_since
                if self._still_s >= c.still_required_s:
                    self.buzzer = "beep"
                    self._enter(State.PRE_ALERT, t)
            else:
                self._still_since = None
        elif self.state is State.PRE_ALERT:
            if tilt < c.tilt_trigger_deg and moving:  # picked up without pressing the button
                self.buzzer = "off"
                self._enter(State.MONITORING, t)
            elif t - self._t_entered >= c.pre_alert_s:
                self.buzzer = "continuous"
                self._enter(State.ALERT, t)
                # record immediately so the escalation is never lost if nobody acknowledges
                return self._make_event("potential_fall", "escalated", t)
        return None

    def _handle_button(self, t: float, button: bool) -> Optional[Event]:
        c = self.cfg
        if button and self._btn_down_at is None:
            self._btn_down_at = t
            self._long_fired = False
        if button and self._btn_down_at is not None and not self._long_fired \
                and t - self._btn_down_at >= c.long_press_s:
            self._long_fired = True
            if self.state is State.ALERT:  # silence locally; the escalated event was already emitted
                self.buzzer = "off"
                self.acknowledged_on_cane = True
                self._enter(State.MONITORING, t)
                self._reset()
                return None
            if self.state is State.MONITORING:
                return Event(str(uuid.uuid4()), "help_request", "escalated", 1.0, 0.0, 0.0, 0.0, t)
        if not button and self._btn_down_at is not None:
            short = (t - self._btn_down_at) < c.long_press_s and not self._long_fired
            self._btn_down_at = None
            if short and self.state is State.PRE_ALERT:
                return self._finish("potential_fall", "cancelled_by_user", t)
        return None

    def _finish(self, kind: str, outcome: str, t: float) -> Event:
        ev = self._make_event(kind, outcome, t)
        self.buzzer = "off"
        self._enter(State.MONITORING, t)
        self._reset()
        return ev

    def _make_event(self, kind: str, outcome: str, t: float) -> Event:
        c = self.cfg
        score = float(np.mean([
            min(self._peak / (c.t_impact_g * 1.5), 1.0),
            min(self._tilt / 90.0, 1.0),
            min(self._still_s / (c.still_required_s * 2), 1.0),
        ]))
        return Event(str(uuid.uuid4()), kind, outcome, round(score, 2),
                     round(self._peak, 2), round(self._tilt, 1), round(self._still_s, 1), t)
