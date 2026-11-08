"""Main program, runs on the Raspberry Pi on the cane: reads the sensors, detects events,
runs the drop/fall flow, drives the step light, speaks, alerts the family and logs for the dashboard.
Run:  .venv/bin/python cane_reader.py        (add --calibrate the first time)"""
import collections, datetime, json, os, queue, sys, time
import numpy as np
import config as C
import db, voice, alerts, hardware
from outbox import Store
from link import CaneLink
from detector import CaneDetector
from features import window_features, FEATURES

def is_evening():
    h = datetime.datetime.now().hour
    return h >= C.EVENING_START_H or h < C.EVENING_END_H

def load_up():
    if os.path.exists(C.CALIB_PATH):
        return json.load(open(C.CALIB_PATH))["up"]
    print("No calibration yet: run with --calibrate. Assuming the module's Z axis is up.")
    return [0, 0, 1]

def calibrate(hw):
    print("Hold the cane upright and still for 3 seconds...")
    samples, t_end = [], time.time() + 3
    while time.time() < t_end:
        try:
            _, ax, ay, az = hw.samples.get(timeout=1)
            samples.append([ax, ay, az])
        except queue.Empty:
            pass
    up = np.mean(samples, axis=0)
    up = (up / np.linalg.norm(up)).tolist()
    os.makedirs("data", exist_ok=True)
    json.dump({"up": up}, open(C.CALIB_PATH, "w"))
    print("Saved upright direction:", [round(v, 3) for v in up])

class Cane:
    def __init__(self, hw):
        self.hw, self.con = hw, db.connect()
        self.det = CaneDetector(load_up())
        self.flow = None              # active drop/fall sequence
        self.light_on, self.last_motion = False, 0.0
        self.window = collections.deque(maxlen=200)   # last 2 s at 100 Hz
        self.model = None
        if os.path.exists(C.EVENT_MODEL_PATH):
            import joblib
            self.model = joblib.load(C.EVENT_MODEL_PATH)
            print("Event model loaded:", list(self.model.classes_))
        self.stand_start, self.cook_stage = None, None
        self.last_sec, self.last_tick, self.last_ml = time.time(), 0.0, 0.0
        self.stumbles_today = 0
        self.secs = 0
        # passive phone-sync outbox: must never get in the way of detection
        try:
            os.makedirs(os.path.dirname(os.path.abspath(C.LINK_DB_PATH)), exist_ok=True)
            store = Store(C.LINK_DB_PATH, device_id=C.DEVICE_ID,
                          sensor_model=getattr(hw, "kind", "LIS3DH"), fw_version=C.FW_VERSION)
            store.register_boot()
            self.link = CaneLink(store, self.det.up)
        except Exception as e:
            print("[link] outbox unavailable:", repr(e))
            self.link = None

    # ---------- drop / fall flow ----------
    def start_flow(self, impact):
        self.flow = {"t0": time.time(), "impact": impact, "asked": False, "alerted": False, "last_help": 0,
                     "origin": "down", "down_t0": time.time(), "tilt_deg": self.det.tilt,
                     "peak_g": max((float(np.linalg.norm(s)) for s in self.window), default=None)}
        self.hw.beep(1)
        if not impact:
            voice.say("dropped")
            db.log_event(self.con, "cue:dropped")
        db.log_event(self.con, "cane_down", impact=impact)

    def cancel_flow(self, why):
        if not self.flow:
            return
        if self.link and self.flow["origin"] == "down" and not self.flow.get("fall_logged"):
            self.link_fall("cancelled_by_user")
        if self.flow["alerted"]:
            alerts.notify(f"Update: {C.PERSON} is okay ({why}).")
        self.flow = None
        self.hw.beep(0)
        voice.say("cancelled")
        db.log_event(self.con, "cue:cancelled")
        db.log_event(self.con, "flow_cancelled", why=why)

    def raise_alert(self, reason):
        if self.flow is None:
            self.flow = {"t0": time.time(), "impact": False, "asked": True, "alerted": False, "last_help": 0,
                         "origin": "sos"}
        if self.flow["alerted"]:
            return
        self.flow.update(alerted=True, last_help=time.time())
        self.hw.beep(2)
        voice.say("help")
        db.log_event(self.con, "cue:help")
        alerts.notify(f"{C.PERSON} may need help at {C.LOCATION_LABEL}: {reason}. "
                      f"He can cancel with a short press on his cane.")
        db.log_event(self.con, "alert", reason=reason)

    def link_fall(self, outcome):
        f, now = self.flow, time.time()
        f["fall_logged"] = True                       # one potential_fall record per flow
        self.link.fall_resolved(outcome, ts_ms=int(now * 1000), peak_g=f.get("peak_g"),
                                tilt_deg=f.get("tilt_deg"), still_s=now - f["down_t0"], impact=f["impact"])

    def tick_flow(self, now):
        f = self.flow
        if not f:
            return
        ask_at = C.ASK_AFTER_IMPACT_S if f["impact"] else C.ASK_AFTER_S
        alert_at = C.ALERT_AFTER_IMPACT_S if f["impact"] else C.ALERT_AFTER_S
        elapsed = now - f["t0"]
        if not f["asked"] and elapsed > ask_at:
            f["asked"] = True
            voice.say("ask_ok")
            db.log_event(self.con, "cue:ask_ok")
        if not f["alerted"] and elapsed > alert_at:
            self.raise_alert("his cane has been down with no response" +
                             (" after a hard impact" if f["impact"] else ""))
            if self.link and f["origin"] == "down":
                self.link_fall("escalated")
        if f["alerted"] and now - f["last_help"] > C.REPEAT_HELP_S:
            f["last_help"] = now
            voice.say("help")
            db.log_event(self.con, "cue:help")        # phone mirrors every spoken repeat (it may have missed the first)

    # ---------- button ----------
    def on_button(self, kind, now):
        if self.det.parked(now) and not self.flow and not self.det.down:
            return                                    # hung on a desk: ignore bumps
        if kind == "OK_PRESS":
            if self.flow:
                self.cancel_flow("he pressed I'm OK")
            else:
                db.log_event(self.con, "ok_press")
        elif kind == "SOS_HOLD":
            voice.say("sos")
            db.log_event(self.con, "cue:sos")
            self.raise_alert("he held the SOS button")
            if self.link:
                self.link.help_request(ts_ms=int(time.time() * 1000))

    # ---------- evening step light ----------
    def tick_light(self, now):
        if self.det.moving:
            self.last_motion = now
        want = self.det.evening and self.det.upright and now - self.last_motion < C.STEP_LIGHT_OFF_AFTER_S
        if want != self.light_on:
            self.light_on = want
            self.hw.led(C.STEP_LIGHT_LEVEL if want else 0)

    # ---------- Sunday cooking prompts ----------
    def tick_cooking(self, now):
        plan = db.get_status(self.con, "cooking_plan")
        if not plan or not plan.get("started_at"):
            self.cook_stage = None
            return
        elapsed_min, idx, acc = (now - plan["started_at"]) / 60, None, 0
        for i, s in enumerate(plan["stages"]):
            acc += s["minutes"] + s.get("rest_after_minutes", 0)
            if elapsed_min < acc:
                idx = i
                break
        if idx is not None and idx != self.cook_stage:
            self.cook_stage = idx
            s = plan["stages"][idx]
            who = "" if s["who"] == C.PERSON else f" {s['who']} can help with this one."
            voice.say(text=f"Next: {s['title']}. This step is {s['position']}.{who}")
        # standing timer
        if self.det.upright and not self.det.parked(now):
            self.stand_start = self.stand_start or now
            if now - self.stand_start > C.STAND_LIMIT_MIN * 60:
                voice.say("sit")
                self.stand_start = now
        elif self.det.parked(now):
            self.stand_start = None

    # ---------- optional ML confirmation ----------
    def ml_label(self):
        if not self.model or len(self.window) < self.window.maxlen:
            return None
        f = window_features(np.array(self.window), self.det.up)
        x = np.array([[f[k] for k in FEATURES]])
        probs = self.model.predict_proba(x)[0]
        i = int(np.argmax(probs))
        return self.model.classes_[i], float(probs[i])

    # ---------- main loop ----------
    def handle_events(self, events, now):
        for kind, info in events:
            if kind == "stride":
                db.log_stride(self.con, info["interval"])
            elif kind == "stumble":
                label = self.ml_label()
                if label and label[0] != "stumble" and label[1] > 0.7:
                    continue                          # model says it was something else
                self.stumbles_today += 1
                db.log_event(self.con, "stumble", **info)
            elif kind == "down":
                self.start_flow(info["impact"])
            elif kind == "pickup":
                self.cancel_flow("he picked up his cane")

    def run(self):
        print("Cane reader running. Ctrl+C to stop.")
        while True:
            try:
                t, ax, ay, az = self.hw.samples.get(timeout=0.1)
                self.window.append((ax, ay, az))
                self.det.evening = is_evening()
                events = self.det.update(t, ax, ay, az)
                if self.link:
                    self.link.feed(t, ax, ay, az)
                self.handle_events(events, t)
            except queue.Empty:
                pass
            now = time.time()
            while not self.hw.events.empty():
                self.on_button(self.hw.events.get_nowait(), now)

            if now - self.last_tick > 0.5:
                self.last_tick = now
                self.tick_flow(now)
                self.tick_light(now)
            if now - self.last_sec >= 1:
                dt, self.last_sec = now - self.last_sec, now
                db.add_activity(self.con, dt if self.det.moving else 0, dt if self.det.upright else 0)
                db.set_status(self.con, "live", {
                    "tilt": round(self.det.tilt, 1), "upright": self.det.upright,
                    "moving": self.det.moving, "parked": self.det.parked(now), "down": self.det.down,
                    "evening": self.det.evening, "light": self.light_on,
                    "flow": None if not self.flow else {k: self.flow[k] for k in ("t0", "impact", "asked", "alerted")},
                    "stumbles_today": self.stumbles_today})
                self.secs += 1
                if self.secs % 10 == 0:
                    self.tick_cooking(now)

if __name__ == "__main__":
    hw = hardware.open_cane()
    if "--calibrate" in sys.argv:
        calibrate(hw)
    cane = None
    try:
        cane = Cane(hw)
        cane.run()
    finally:
        if cane and cane.link:
            cane.link.flush()
        hw.led(0); hw.beep(0); hw.close()
