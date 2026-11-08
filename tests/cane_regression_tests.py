"""Regression coverage for the smart-cane device runtime (TEST ARTIFACT - not production code).

Covers down / parked / OK / SOS contexts against the real detector + reader code,
using FakeCane (CSV replay) and stubbed external transports.

Run from a COPY of the project (never the production folder):
    cp -r <project> /tmp/cane-test && cd /tmp/cane-test
    python3 /path/to/cane_regression_tests.py

External transport proof: the suite asserts CANE_DISCORD_WEBHOOK is empty and
monkeypatches alerts.notify / voice.say to a local recorder, so ZERO network or
audio calls leave the process. Any word like "sent" in output means "recorded by
the stub", never a real send.

Timer values are overridden in-memory only (no config.py edits).
"""
import os, sys, time, threading, json

sys.path.insert(0, os.getcwd())  # run from the project copy; imports resolve there
os.environ["CANE_SOURCE"] = "fake:data/raw/__suite__.csv"
assert not os.getenv("CANE_DISCORD_WEBHOOK"), "webhook must be unset: no real alert transport"

import config as C
# fast demo timers, in-memory only
C.ASK_AFTER_S, C.ALERT_AFTER_S = 2, 4
C.ASK_AFTER_IMPACT_S, C.ALERT_AFTER_IMPACT_S = 1, 2
C.REPEAT_HELP_S = 3
C.DOWN_CONFIRM_S = 1.0
C.PICKUP_CONFIRM_S = 0.5

import alerts, voice, hardware, db

SENT = []  # stub record: (channel, key_or_text)
alerts.notify = lambda text: SENT.append(("alert", text))
voice.say = lambda key=None, text=None: SENT.append(("voice", text or C.PHRASES.get(key, key)))

import csv
import numpy as np

def write_csv(path, segments):
    """segments: list of (n_samples, ax, ay, az) or ('strike', n, period_s, peak_g)."""
    rows, t = [], 0.0
    for seg in segments:
        if seg[0] == "strike":
            _, n, period, peak = seg
            per = int(period * 100)
            for i in range(n):
                phase = (i % per) / per
                spike = peak * np.exp(-phase * 8) if phase < 0.3 else 0
                rows.append((round(t, 2), 0.0, 0.0, round(1 + spike, 4))); t += 0.01
        else:
            n, ax, ay, az = seg
            for _ in range(int(n)):
                rows.append((round(t, 2), ax, ay, az)); t += 0.01
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["t", "ax", "ay", "az"]); w.writerows(rows)

from cane_reader import Cane

RESULTS = []

def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" :: " + str(detail) if detail else ""))

import tempfile, shutil
TMP = tempfile.mkdtemp(prefix="cane_suite_")
_ACTIVE = []   # (thread, hw, cane, con) of the running scenario
_N = [0]

def _stop_active():
    """Stop the previous scenario's threads without touching production code: SystemExit
    raised inside a thread ends it silently, so the reader loop and the CSV feeder both exit
    before the next scenario starts."""
    class _Stop:
        def empty(self): raise SystemExit
    def _halt(*a, **k): raise SystemExit
    while _ACTIVE:
        th, hw, cane, con = _ACTIVE.pop()
        hw._put = _halt
        cane.hw.events = _Stop()
        th.join(5)
        assert not th.is_alive(), "previous scenario thread did not stop"
        for c in (con, cane.con):
            try: c.close()
            except Exception: pass

def fresh_cane(segments, run_s):
    _stop_active()
    _N[0] += 1
    # unique DB and CSV per scenario: nothing is ever deleted under a live writer
    C.DB_PATH = db.DB_PATH = os.path.join(TMP, f"cane_{_N[0]}.db")
    csv_path = os.path.join(TMP, f"scenario_{_N[0]}.csv")
    C.SOURCE = "fake:" + csv_path
    SENT.clear()
    write_csv(csv_path, segments)
    hw = hardware.open_cane()
    cane = Cane(hw)
    th = threading.Thread(target=cane.run, daemon=True); th.start()
    time.sleep(run_s)
    con = db.connect()
    _ACTIVE.append((th, hw, cane, con))
    return cane, con

# 1. walking: strides counted
cane, con = fresh_cane([(100, 0, 0, 1), ("strike", 800, 1.1, 0.9)], 10)
n = con.execute("SELECT count(*) FROM strides").fetchone()[0]
check("walking strides counted", 4 <= n <= 12, f"{n} strides in ~7.3s of 1.1s strikes")

# 2. plain drop: down -> ask -> alert, then OK cancels and records family update
cane, con = fresh_cane([(150, 0, 0, 1), (1300, 1, 0, 0)], 10)  # EMA lag puts 'down' ~3.5s in; alert ~8s, OK at 10s, replay 14.5s
types = [r[0] for r in con.execute("SELECT type FROM events ORDER BY ts")]
cane.on_button("OK_PRESS", time.time()); time.sleep(0.3)
types = [r[0] for r in con.execute("SELECT type FROM events ORDER BY ts")]
check("plain drop alert flow", "cane_down" in types and "alert" in types, types)
check("OK cancels after alert", "flow_cancelled" in types, types)
check("family update recorded after cancel", any("okay" in t for c, t in SENT if c == "alert"),
      [t for c, t in SENT if c == "alert"])

# 3. impact drop uses the fast timeline
cane, con = fresh_cane([(100, 0, 0, 1), (5, 0, 0, 3.2), (500, 1, 0, 0)], 6)
d = con.execute("SELECT detail FROM events WHERE type='cane_down'").fetchone()
check("impact flagged on down", d and json.loads(d[0]).get("impact") is True, d)
check("impact alert reason mentions impact",
      any("hard impact" in t for c, t in SENT if c == "alert"), SENT[-3:])

# 4. parked cane (upright, dead still): button ignored
cane, con = fresh_cane([(700, 0, 0, 1)], 8)   # 7s motionless upright -> parked at ~3s
cane.on_button("SOS_HOLD", time.time()); time.sleep(0.3)
check("SOS ignored while parked", not any(c == "alert" for c, _ in SENT), SENT)

# 5. POST-FIX: down + still after cancel - SOS must fire (det.down exemption to the parked guard).
cane, con = fresh_cane([(150, 0, 0, 1), (500, 1, 0, 0)], 6)
cane.on_button("OK_PRESS", time.time()); time.sleep(0.2)
SENT.clear()
cane.on_button("SOS_HOLD", time.time()); time.sleep(0.3)
check("SOS alerts while down+still (post-fix)", any(c == "alert" for c, _ in SENT), SENT)

# 6. upright held cane: SOS alerts immediately
cane, con = fresh_cane([("strike", 400, 1.1, 0.9)], 4)
cane.det.dyn_avg = 0.2  # held in hand
cane.on_button("SOS_HOLD", time.time()); time.sleep(0.3)
check("SOS alerts when upright/held", any("SOS" in t for c, t in SENT if c == "alert"), SENT)

# 7. pickup cancels an active flow
cane, con = fresh_cane([(150, 0, 0, 1), (250, 1, 0, 0), (200, 0, 0, 1)], 6)
types = [r[0] for r in con.execute("SELECT type FROM events ORDER BY ts")]
check("pickup cancels flow", "cane_down" in types and "flow_cancelled" in types, types)

# 8. graceful shutdown: close() stops every worker thread (no daemon left touching stderr at exit)
_stop_active()
C.SOURCE = "fake:" + os.path.join(TMP, "scenario_1.csv")
hw = hardware.open_cane()
workers = list(hw._threads)
hw.beep(3)                                   # one-shot tone path must also be tracked/stopped
t0 = time.time()
hw.close()
check("close() stops worker threads promptly",
      bool(workers) and not any(t.is_alive() for t in workers) and time.time() - t0 < 2.0,
      [t.name for t in workers if t.is_alive()])
check("close() is idempotent", hw.close() is None)

_stop_active()
shutil.rmtree(TMP, ignore_errors=True)
fails = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed" + (f" - FAILED: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
