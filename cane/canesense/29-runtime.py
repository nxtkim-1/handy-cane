"""Sampling loop: sensor -> features + fall FSM -> buzzer/store (MASTER 6.4, 8.2).

Hardware is injected (Sensor, Button, Buzzer protocols), so the same loop runs on a Pi with real
Grove devices or against a simulator. This module never touches the network.
"""
from __future__ import annotations

from typing import Callable, Protocol

import numpy as np

from cane.canesense.features import minute_features
from cane.canesense.features import tilt_deg
from cane.canesense.fsm import Event, FallFSM
from cane.canesense.live import LiveTracker
from cane.canesense.store import Store
from cane.common.schema import SAMPLE_RATE_HZ


class Sensor(Protocol):
    def read(self) -> np.ndarray: ...  # (3,) acceleration in g


class Button(Protocol):
    def pressed(self) -> bool: ...


class Buzzer(Protocol):
    def set(self, mode: str) -> None: ...  # off | beep | continuous


class CaneRuntime:
    def __init__(self, sensor: Sensor, button: Button, buzzer: Buzzer, store: Store,
                 upright: np.ndarray, fsm: FallFSM | None = None,
                 live: LiveTracker | None = None):
        self.sensor, self.button, self.buzzer, self.store = sensor, button, buzzer, store
        self.live = live
        self.upright = np.asarray(upright, float)
        self.fsm = fsm or FallFSM(self.upright)
        self._buf: list[np.ndarray] = []
        self._minute: int | None = None
        self.sensor_faults = 0

    def step(self, now_ms: int) -> None:
        """Take one sample at wall time now_ms. Call at 50 Hz."""
        minute = now_ms // 60000
        if self._minute is not None and minute != self._minute:
            self._flush(self._minute)
        self._minute = minute
        try:
            acc = np.asarray(self.sensor.read(), float)
            self._buf.append(acc)
        except Exception:  # I2C error: keep running, minute will show n_samples short/0
            self.sensor_faults += 1
            acc = None
        if acc is not None:
            ev = self.fsm.update(now_ms / 1000.0, acc, self.button.pressed())
            self.buzzer.set(self.fsm.buzzer)
            if self.live is not None:
                self.live.update(now_ms, acc, float(tilt_deg(acc[None, :], self.upright)[0]), self.fsm.state)
            if ev:
                self._write_event(ev, now_ms)

    def _flush(self, minute: int) -> None:
        feats = minute_features(np.array(self._buf).reshape(-1, 3), self.upright)
        self.store.add("minute", minute * 60000, feats)
        self._buf = []

    def _write_event(self, ev: Event, now_ms: int) -> None:
        self.store.add("event", now_ms, dict(
            event_id=ev.event_id, kind=ev.kind, outcome=ev.outcome, confidence=ev.confidence,
            peak_g=ev.peak_g, tilt_deg=ev.tilt_deg, still_s=ev.still_s, raw_snippet_b64=None))

    def close_minute(self) -> None:
        if self._minute is not None and self._buf:
            self._flush(self._minute)
