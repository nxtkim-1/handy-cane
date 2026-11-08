"""Simulated Grove hardware: scripted accelerometer scenarios, button, buzzer (no Pi needed)."""
from __future__ import annotations

import numpy as np

UP = np.array([0.0, 0.0, 1.0])
HZ = 50


class SimSensor:
    """Plays a script of (kind, seconds) segments: idle | walk | drop | lying. Then idles forever."""

    def __init__(self, script: list[tuple[str, float]], seed: int = 0):
        self.rng = np.random.default_rng(seed)
        self.samples: list[np.ndarray] = []
        for kind, secs in script:
            self.samples.extend(self._segment(kind, secs))
        self.i = 0

    def _segment(self, kind: str, secs: float):
        n = int(secs * HZ)
        noise = lambda s=0.006: self.rng.normal(0, s, 3)
        out = []
        for k in range(n):
            if kind == "walk":
                a = UP + noise(0.02)
                if k % HZ == 10:
                    a = a + np.array([0.1, 0, 0.9])  # cane-tip strike once per second
            elif kind == "drop":
                a = np.array([4.0, 0.0, 0.5]) if k == 0 else np.array([1.0, 0, 0.0]) + noise()
            elif kind == "lying":
                a = np.array([1.0, 0.0, 0.0]) + noise()
            else:
                a = UP + noise()
            out.append(a)
        return out

    def read(self) -> np.ndarray:
        a = self.samples[self.i] if self.i < len(self.samples) else UP
        self.i += 1
        return a


class SimButton:
    def __init__(self):
        self.windows: list[tuple[float, float]] = []  # (start_s, end_s) in sim time
        self.t = 0.0

    def press(self, start_s: float, end_s: float) -> None:
        self.windows.append((start_s, end_s))

    def pressed(self) -> bool:
        return any(s <= self.t < e for s, e in self.windows)


class SimBuzzer:
    def __init__(self):
        self.mode, self.log = "off", []

    def set(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.log.append(mode)
