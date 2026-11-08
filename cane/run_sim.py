"""Runnable cane simulator: python -m cane.run_sim [--port 8765] [--db cane.db]

Plays a scripted session (walk, idle, drop, lying still, button cancel, then a second
un-cancelled drop) in fast-forward, then keeps serving the sync API so a phone, the mobile
app's HTTP transport, or curl can pull the data:
    curl localhost:8765/info
    curl "localhost:8765/pull?after_seq=0&limit=50"
"""
from __future__ import annotations

import argparse
import time

from cane.canelink.server import serve
from cane.canesense.runtime import CaneRuntime
from cane.canesense.sim_hw import HZ, UP, SimBuzzer, SimButton, SimSensor
from cane.canesense.store import Store

SCRIPT = [("walk", 150), ("idle", 20), ("drop", 0.02), ("lying", 60),   # drop, cancelled at ~t=190s
          ("walk", 60), ("drop", 0.02), ("lying", 90)]                  # second drop, never cancelled


def run_session(store: Store, start_ms: int = 1_790_000_000_000 // 60000 * 60000) -> SimBuzzer:
    sensor, button, buzzer = SimSensor(SCRIPT), SimButton(), SimBuzzer()
    button.press(190.0, 190.4)  # short press inside the pre-alert window cancels it
    rt = CaneRuntime(sensor, button, buzzer, store, UP)
    total = len(sensor.samples) + 10 * HZ
    for i in range(total):
        button.t = i / HZ
        rt.step(start_ms + int(i * 1000 / HZ))
    rt.close_minute()
    return buzzer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--db", default=":memory:")
    a = ap.parse_args()
    clock = [1_790_000_000_000 // 60000 * 60000]
    store = Store(a.db, device_id="cane-sim", sensor_model="simulated", now_ms=lambda: clock[0])
    buzzer = run_session(store)
    print("session done; buzzer transitions:", buzzer.log)
    print("info:", store.info())
    srv = serve(store, port=a.port)
    print(f"serving sync API on http://localhost:{a.port}  (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
