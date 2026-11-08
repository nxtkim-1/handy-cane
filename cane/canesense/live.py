"""Latest-sample snapshot for the phone's Live view (GET /live, mobile/PROTOCOL.md).

Written by the sampling loop (CaneRuntime.step), read by the link server thread. In-memory only:
no I/O, never blocks the loop beyond a short lock. The heavy part (strike counting over 10 s) runs
once per second. In the real two-process deployment the link process cannot see this memory;
firmware must publish a snapshot another way (see cane/README.md).
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

import numpy as np

from cane.canesense.features import FLAT_DEG, T_ACTIVE, detect_strikes
from cane.canesense.fsm import State
from cane.common.schema import SAMPLE_RATE_HZ

WINDOW_10S = 10 * SAMPLE_RATE_HZ
FSM_IMPACT_STATES = (State.IMPACT, State.CHECK_STILL, State.PRE_ALERT, State.ALERT)


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LiveTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mags: deque[float] = deque(maxlen=WINDOW_10S)
        self._n = 0
        self._snap: dict | None = None

    def update(self, now_ms: int, acc: np.ndarray, tilt_deg: float, fsm_state: State) -> None:
        self._mags.append(float(np.linalg.norm(acc)))
        self._n += 1
        if self._snap is not None and self._n % SAMPLE_RATE_HZ != 0:
            return  # recompute once per second
        arr = np.fromiter(self._mags, float)
        last = arr[-SAMPLE_RATE_HZ:]
        std = float(last.std()) if len(last) > 1 else 0.0
        strikes = int(len(detect_strikes(arr)))
        if fsm_state in FSM_IMPACT_STATES:
            state = "impact"
        elif tilt_deg > FLAT_DEG and std < T_ACTIVE:
            state = "flat"
        elif std > T_ACTIVE:
            state = "walking"
        else:
            state = "idle"
        snap = dict(ts=_iso(now_ms), mag=round(float(last.mean()), 3),
                    dyn=round(float(np.maximum(last - 1.0, 0.0).mean()), 3),
                    state=state, strikes_last_10s=strikes)
        with self._lock:
            self._snap = snap

    def snapshot(self) -> dict | None:
        with self._lock:
            return dict(self._snap) if self._snap else None
