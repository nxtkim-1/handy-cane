"""Runnable cane simulator: python -m cane.run_sim [--port 8765] [--db cane.db]

Each run appends a fresh session (data ends "now") to cane_sim.db, so restarting gives new alerts.
Plays a scripted session (walk, idle, drop, lying still, button cancel, then a second
un-cancelled drop) in fast-forward, then keeps serving the sync API so a phone, the mobile
app's HTTP transport, or curl can pull the data:
    curl localhost:8765/info
    curl "localhost:8765/pull?after_seq=0&limit=50"
"""
from __future__ import annotations

import argparse
import threading
import time

from cane.canelink.server import serve
from cane.canesense.features import tilt_deg
from cane.canesense.fsm import FallFSM
from cane.canesense.live import LiveTracker
from cane.canesense.runtime import CaneRuntime
from cane.canesense.sim_hw import HZ, UP, SimBuzzer, SimButton, SimSensor
from cane.canesense.store import Store

SCRIPT = [("walk", 150), ("idle", 20), ("drop", 0.02), ("lying", 60),   # drop, cancelled at ~t=190s
          ("walk", 60), ("drop", 0.02), ("lying", 90)]                  # second drop, never cancelled


DEMO_LOOP = [("walk", 20), ("idle", 10)]  # endless real-time loop behind GET /live


def run_session(store: Store, start_ms: int = 1_790_000_000_000 // 60000 * 60000,
                live: LiveTracker | None = None) -> SimBuzzer:
    sensor, button, buzzer = SimSensor(SCRIPT), SimButton(), SimBuzzer()
    button.press(190.0, 190.4)  # short press inside the pre-alert window cancels it
    rt = CaneRuntime(sensor, button, buzzer, store, UP, live=live)
    total = len(sensor.samples) + 10 * HZ
    for i in range(total):
        button.t = i / HZ
        rt.step(start_ms + int(i * 1000 / HZ))
    rt.close_minute()
    return buzzer


def live_loop(live: LiveTracker, stop: threading.Event, speed: float = 1.0) -> None:
    """Feed the Live view in real time with a walk/idle loop, stamped with the wall clock."""
    fsm = FallFSM(UP)
    while not stop.is_set():
        sensor = SimSensor(DEMO_LOOP, seed=int(time.time()) % 1000)
        for acc in sensor.samples:
            if stop.is_set():
                return
            now_ms = int(time.time() * 1000)
            fsm.update(now_ms / 1000.0, acc, False)
            live.update(now_ms, acc, float(tilt_deg(acc[None, :], UP)[0]), fsm.state)
            time.sleep(1.0 / (HZ * speed))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--db", default="cane_sim.db", help="kept on disk so sequence numbers survive restarts")
    ap.add_argument("--no-live", action="store_true", help="do not serve GET /live")
    a = ap.parse_args()
    # Play the session so it ENDS about now: the data then lands on today, not on a fixed old date.
    now_ms = int(time.time() * 1000)
    total_s = sum(secs for _, secs in SCRIPT) + 10
    start_ms = now_ms // 60000 * 60000 - (int(total_s // 60) + 1) * 60000
    store = Store(a.db, device_id="cane-sim", sensor_model="simulated", now_ms=lambda: now_ms)
    buzzer = run_session(store, start_ms=start_ms)
    print("session done; buzzer transitions:", buzzer.log)
    print("info:", store.info())
    live = None if a.no_live else LiveTracker()
    stop = threading.Event()
    if live is not None:
        threading.Thread(target=live_loop, args=(live, stop), daemon=True).start()
    srv = serve(store, port=a.port, live=live)
    print(f"serving sync API on http://localhost:{a.port}  (Ctrl-C to stop)")
    if live is not None:
        print("GET /live shows a walk(20s)/idle(10s) demo loop in real time")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        srv.shutdown()


if __name__ == "__main__":
    main()
