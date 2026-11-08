"""Tests for the canonical sync outbox adapter (link.py, outbox.py, link_server.py).
Run from pi/:   python3 ../tests/canelink_adapter_tests.py
Localhost only; no hardware."""
import os, sys, json, threading, urllib.request
sys.path.insert(0, os.getcwd())

import numpy as np
from outbox import Store
from link import CaneLink
import link_server

RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" :: " + str(detail) if detail else ""))

UP = [0, 0, 1]
MINUTE_FIELDS = {"n_samples", "mag_mean", "mag_std", "mag_max", "dyn_mean", "active_s", "strike_count",
                 "strike_iv_mean", "strike_iv_cv", "upright_s", "flat_s", "max_impact_g"}
T0 = 1_762_600_020.0        # exactly on a minute boundary (divisible by 60)
assert T0 % 60 == 0

def records(store):
    return store.pull(0, 2000)["records"]

# 1. minute rollover: one minute record with all canonical fields
st = Store(":memory:"); lk = CaneLink(st, UP)
for i in range(60 * 100):                              # a full minute at 100 Hz, constant upright
    lk.feed(T0 + i / 100, 0.0, 0.0, 1.0)
check("no record before rollover", records(st) == [])
lk.feed(T0 + 60.0, 0.0, 0.0, 1.0)                      # first sample of the next minute
recs = records(st)
check("exactly one minute record at rollover", len(recs) == 1 and recs[0]["type"] == "minute", recs)
m = recs[0]
check("minute has all canonical fields", MINUTE_FIELDS <= set(m), MINUTE_FIELDS - set(m))
check("minute values sane", 2990 <= m["n_samples"] <= 3010 and 58 <= m["upright_s"] <= 60
      and abs(m["mag_mean"] - 1.0) < 1e-6 and m["flat_s"] == 0 and m["strike_count"] == 0, m)
check("minute ts is minute start", m["ts"].endswith(":00Z"), m["ts"])

# 2. downsampling bound over 61 s at 100 Hz
st = Store(":memory:"); lk = CaneLink(st, UP)
for i in range(61 * 100):
    lk.feed(T0 + i / 100, 0.0, 0.0, 1.0)
lk.flush()
ns = [r["n_samples"] for r in records(st)]
check("downsampled n_samples <= 3300", ns and max(ns) <= 3300 and sum(ns) == 3050, ns)

# 3. event mappings
st = Store(":memory:"); lk = CaneLink(st, UP)
lk.fall_resolved("escalated", ts_ms=1000, peak_g=2.5, tilt_deg=85.0, still_s=30.0, impact=True)
lk.fall_resolved("cancelled_by_user", ts_ms=2000, peak_g=None, tilt_deg=80.0, still_s=5.0, impact=False)
lk.help_request(ts_ms=3000)
ev = records(st)
check("three event records", len(ev) == 3 and all(e["type"] == "event" for e in ev))
check("fall escalated mapping", ev[0]["kind"] == "potential_fall" and ev[0]["outcome"] == "escalated"
      and ev[0]["peak_g"] == 2.5 and ev[0]["cause"] == "cane_down_impact", ev[0])
check("fall cancelled mapping, None omitted", ev[1]["outcome"] == "cancelled_by_user"
      and "peak_g" not in ev[1] and ev[1]["tilt_deg"] == 80.0 and ev[1]["cause"] == "cane_down_still", ev[1])
check("help_request mapping", ev[2]["kind"] == "help_request" and ev[2]["outcome"] == "escalated"
      and ev[2]["cause"] == "sos_hold" and "peak_g" not in ev[2], ev[2])
check("no confidence anywhere", all("confidence" not in e for e in ev))
check("source + unique event_id", all(e["source"] == "cane_reader" for e in ev)
      and len({e["event_id"] for e in ev}) == 3)

# 4. real HTTP end to end
st = Store(":memory:", device_id="cane-test", sensor_model="LIS3DH", fw_version="0.4.0")
lk = CaneLink(st, UP)
lk.help_request(ts_ms=5_000)
lk.fall_resolved("escalated", ts_ms=6_000, peak_g=2.0, tilt_deg=80.0, still_s=9.0, impact=True)
srv = link_server.serve(st, "127.0.0.1", 0)
base = f"http://127.0.0.1:{srv.server_address[1]}"
def http(path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())
try:
    info = http("/info")
    check("/info", info["device_id"] == "cane-test" and info["last_seq"] == 2 and info["unsynced_count"] == 2
          and info["sensor_model"] == "LIS3DH", info)
    pulled = http("/pull?after_seq=0&limit=500")
    seqs = [r["seq"] for r in pulled["records"]]
    check("/pull ascending, complete", seqs == sorted(seqs) == [1, 2] and pulled["more"] is False
          and pulled["next_cursor"] == 2, pulled)
    check("/pull is read-only", http("/info")["unsynced_count"] == 2)
    check("/pull quality unsynced", all(r["time_quality"] == "unsynced" for r in pulled["records"]))
    ts_before = pulled["records"][0]["ts"]
    http("/time", {"phone_utc_ms": st._now_ms() + 3_600_000})
    after = http("/pull?after_seq=0")["records"]
    check("/time corrects unsynced rows", all(r["time_quality"] == "corrected" for r in after)
          and after[0]["ts"] != ts_before, after[0])
    http("/ack", {"up_to_seq": 1})
    check("/ack marks synced", http("/info")["unsynced_count"] == 1)
    http("/ack", {"up_to_seq": 0})
    check("/ack lower value is a no-op", http("/info")["unsynced_count"] == 1)
finally:
    srv.shutdown(); srv.server_close()

# 5. containment: a failing store never raises and disables the adapter
class Boom:
    def add(self, *a, **k): raise RuntimeError("disk full")
lk = CaneLink(Boom(), UP)
try:
    for i in range(61 * 100):
        lk.feed(T0 + i / 100, 0.0, 0.0, 1.0)
    check("feed() contained, adapter disabled", lk.disabled)
    lk = CaneLink(Boom(), UP)
    lk.fall_resolved("escalated", ts_ms=1, peak_g=1.0, tilt_deg=1.0, still_s=1.0, impact=False)
    lk.help_request(ts_ms=1); lk.flush()
    check("event calls contained, adapter disabled", lk.disabled)
except Exception as e:
    check("contained", False, repr(e))

# 6. reader wiring: drive the REAL cane_reader.Cane against a temp outbox (no hardware, no network/audio)
import tempfile, shutil, time as _time, sqlite3
os.environ.setdefault("CANE_SOURCE", "fake:data/raw/__suite__.csv")
assert not os.getenv("CANE_DISCORD_WEBHOOK"), "webhook must be unset: no real alert transport"
import config as C, db, alerts, voice
alerts.notify = lambda text: None            # stubs: nothing leaves the process
voice.say = lambda key=None, text=None: None
from cane_reader import Cane

class FakeHW:
    kind = "LIS3DH"
    def beep(self, *a): pass
    def led(self, *a): pass

_TMP = tempfile.mkdtemp(prefix="canelink_wiring_")
_N = [0]
_CLOCK = [1_762_600_000.0]
_real_time = _time.time
_time.time = lambda: _CLOCK[0]               # fake wall clock: no sleeps; restored in finally below

def new_cane():
    _N[0] += 1
    C.DB_PATH = db.DB_PATH = os.path.join(_TMP, f"cane_{_N[0]}.db")
    C.LINK_DB_PATH = os.path.join(_TMP, f"outbox_{_N[0]}.db")
    cane = Cane(FakeHW())
    assert cane.link is not None and not cane.link.disabled
    return cane

def canon(cane):
    return [r for r in cane.link.store.pull(0, 2000)["records"] if r["type"] == "event"]

def local_types(cane):
    return [r[0] for r in cane.con.execute("SELECT type FROM events ORDER BY ts")]

try:
    # a. down-flow started then cancelled
    cane = new_cane()
    cane.start_flow(False); _CLOCK[0] += 5
    cane.cancel_flow("he picked up his cane")
    ev = canon(cane)
    check("a: down + cancel -> one potential_fall/cancelled_by_user",
          len(ev) == 1 and ev[0]["kind"] == "potential_fall" and ev[0]["outcome"] == "cancelled_by_user", ev)
    check("a: cause cane_down_*, no confidence", ev[0]["cause"].startswith("cane_down_") and "confidence" not in ev[0], ev[0])

    # b. escalation via the timer path (both timelines), then cancel after escalation
    for impact, limit in ((False, C.ALERT_AFTER_S), (True, C.ALERT_AFTER_IMPACT_S)):
        cane = new_cane()
        cane.start_flow(impact)
        cane.tick_flow(_CLOCK[0] + limit - 1)
        check(f"b: impact={impact} no record before the alert threshold", canon(cane) == [])
        cane.tick_flow(_CLOCK[0] + limit + 1)
        ev = canon(cane)
        check(f"b: impact={impact} timer escalation -> one potential_fall/escalated",
              len(ev) == 1 and ev[0]["kind"] == "potential_fall" and ev[0]["outcome"] == "escalated"
              and ev[0]["cause"] == ("cane_down_impact" if impact else "cane_down_still"), ev)
        cane.tick_flow(_CLOCK[0] + limit + 2)
        cane.cancel_flow("he pressed I'm OK")
        check(f"b: impact={impact} cancel after escalation writes no second record", len(canon(cane)) == 1, canon(cane))

    # c. SOS hold with no active flow
    cane = new_cane()
    cane.on_button("SOS_HOLD", _CLOCK[0])
    ev = canon(cane)
    check("c: SOS (no flow) -> one help_request/escalated",
          len(ev) == 1 and ev[0]["kind"] == "help_request" and ev[0]["outcome"] == "escalated"
          and ev[0]["cause"] == "sos_hold", ev)
    cane.cancel_flow("he pressed I'm OK")
    check("c: cancel after SOS-only flow writes no potential_fall",
          [e["kind"] for e in canon(cane)] == ["help_request"], canon(cane))

    # d. SOS during an active down-flow
    cane = new_cane()
    cane.start_flow(False)
    cane.on_button("SOS_HOLD", _CLOCK[0] + 1)
    cane.cancel_flow("he pressed I'm OK")
    kinds = sorted(e["kind"] for e in canon(cane))
    check("d: SOS during down-flow -> help_request AND potential_fall",
          kinds == ["help_request", "potential_fall"], kinds)
    pf = [e for e in canon(cane) if e["kind"] == "potential_fall"][0]
    check("d: flow still resolves as potential_fall/cancelled_by_user", pf["outcome"] == "cancelled_by_user", pf)

    # e. stumble: local db only, zero canonical event records
    cane = new_cane()
    cane.handle_events([("stumble", {"peak_g": 1.8, "recovery_s": 0.4})], _CLOCK[0])
    check("e: stumble writes NO canonical event record", canon(cane) == [], canon(cane))
    check("e: stumble still logged to the local db", local_types(cane) == ["stumble"] and cane.stumbles_today == 1,
          local_types(cane))
    check("e: link has no impact_only", not hasattr(cane.link, "impact_only"))

    # f. minute flush through the reader's link
    cane = new_cane()
    t0 = float(int(_CLOCK[0] // 60) * 60)
    for i in range(60 * 100):
        cane.link.feed(t0 + i / 100, 0.0, 0.0, 1.0)
    cane.link.feed(t0 + 60.0, 0.0, 0.0, 1.0)
    mins = [r for r in cane.link.store.pull(0, 2000)["records"] if r["type"] == "minute"]
    check("f: minute boundary -> one minute record", len(mins) == 1, len(mins))

    # g. voice cues are logged as cue:<key> events (phone playback via /events)
    def cues(c):
        return [t for t in local_types(c) if t.startswith("cue:")]
    cane = new_cane()
    cane.start_flow(True)
    check("g: impact start_flow logs no cue:dropped", cues(cane) == [], cues(cane))
    cane = new_cane()
    cane.start_flow(False)
    check("g: non-impact start_flow -> cue:dropped", cues(cane) == ["cue:dropped"], cues(cane))
    cane.tick_flow(_CLOCK[0] + C.ASK_AFTER_S + 1)
    check("g: ask point -> cue:ask_ok", cues(cane) == ["cue:dropped", "cue:ask_ok"], cues(cane))
    cane.tick_flow(_CLOCK[0] + C.ALERT_AFTER_S + 1)
    check("g: escalation -> cue:help", cues(cane).count("cue:help") == 1, cues(cane))
    cane.tick_flow(_CLOCK[0] + C.ALERT_AFTER_S + C.REPEAT_HELP_S + 5)
    check("g: repeated help line logs NO extra cue", cues(cane).count("cue:help") == 1, cues(cane))
    cane.cancel_flow("he pressed I'm OK")
    check("g: cancel -> cue:cancelled", cues(cane).count("cue:cancelled") == 1, cues(cane))
    cane = new_cane()
    cane.on_button("SOS_HOLD", _CLOCK[0])
    check("g: SOS hold -> cue:sos then cue:help", sorted(cues(cane)) == ["cue:help", "cue:sos"], cues(cane))
    check("g: no cue:sit ever logged", all(t != "cue:sit" for t in cues(cane)))
finally:
    _time.time = _real_time
    shutil.rmtree(_TMP, ignore_errors=True)

fails = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed" + (f" - FAILED: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
