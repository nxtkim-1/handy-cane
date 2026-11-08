import json
import threading
import urllib.error
import urllib.request

import numpy as np

from cane.canelink.server import serve
from cane.canesense.live import LiveTracker
from cane.canesense.runtime import CaneRuntime
from cane.canesense.sim_hw import HZ, UP, SimBuzzer, SimButton, SimSensor
from cane.canesense.store import Store

START = 1_790_000_040_000
KEYS = {"ts", "mag", "dyn", "state", "strikes_last_10s"}


def run(script, seconds_extra=0):
    sensor, button, buzzer = SimSensor(script), SimButton(), SimBuzzer()
    live = LiveTracker()
    rt = CaneRuntime(sensor, button, buzzer, Store(now_ms=lambda: START), UP, live=live)
    for i in range(len(sensor.samples) + seconds_extra * HZ):
        button.t = i / HZ
        rt.step(START + int(i * 1000 / HZ))
    return live


def get(port, path):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}"))


def test_none_before_any_sample():
    assert LiveTracker().snapshot() is None


def test_idle_shape_and_values():
    snap = run([("idle", 12)]).snapshot()
    assert set(snap) == KEYS
    assert snap["state"] == "idle" and snap["strikes_last_10s"] == 0
    assert abs(snap["mag"] - 1.0) < 0.02 and snap["dyn"] < 0.02
    assert snap["ts"].endswith("Z") and "T" in snap["ts"]


def test_walking_counts_strikes():
    snap = run([("walk", 15)]).snapshot()
    assert snap["state"] == "walking"
    assert 8 <= snap["strikes_last_10s"] <= 10


def test_flat_after_lying_and_impact_during_fall():
    live = run([("walk", 5), ("drop", 0.02), ("lying", 2)])
    assert live.snapshot()["state"] == "impact"  # FSM is in IMPACT/CHECK_STILL
    # a lying cane that the FSM already finished with reads as flat
    t = LiveTracker()
    from cane.canesense.fsm import State
    for i in range(120):
        t.update(START + i * 20, np.array([1.0, 0.0, 0.0]), 90.0, State.MONITORING)
    assert t.snapshot()["state"] == "flat"


def test_live_route_and_503_without_source():
    live = run([("walk", 12)])
    srv = serve(Store(now_ms=lambda: START), host="127.0.0.1", port=0, live=live)
    srv2 = serve(Store(now_ms=lambda: START), host="127.0.0.1", port=0)
    try:
        body = get(srv.server_address[1], "/live")
        assert set(body) == KEYS and body["state"] in ("idle", "walking", "flat", "impact")
        assert isinstance(body["strikes_last_10s"], int) and isinstance(body["mag"], float)
        try:
            get(srv2.server_address[1], "/live")
            assert False, "expected 503"
        except urllib.error.HTTPError as e:
            assert e.code == 503 and json.load(e)["error"]["code"] == "no_live_data"
    finally:
        srv.shutdown(); srv2.shutdown()


def test_concurrent_reads_while_updating():
    t = LiveTracker()
    stop = threading.Event()
    seen = []

    def reader():
        while not stop.is_set():
            s = t.snapshot()
            if s:
                seen.append(set(s))

    th = threading.Thread(target=reader); th.start()
    from cane.canesense.fsm import State
    for i in range(1000):
        t.update(START + i * 20, np.array([0, 0, 1.0]), 0.0, State.MONITORING)
    stop.set(); th.join()
    assert all(k == KEYS for k in seen)
