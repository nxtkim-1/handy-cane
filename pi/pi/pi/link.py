"""Passive adapter: turns the cane's live stream and resolved events into canonical outbox records
for the phone app (see mobile/PROTOCOL.md). It only observes: it never changes detection, and any
failure disables it instead of raising into the reader loop."""
import uuid
import numpy as np

OUT_HZ = 50            # canonical schema / backend rate (n_samples <= 3300 per minute)
T_ACTIVE = 0.05        # g, 1-s rolling std of |a| above this = cane in motion
T_STRIKE = 0.35        # g, high-pass |a| peak height for a ground contact
MIN_STRIKE_GAP_S = 0.4
UPRIGHT_DEG = 30.0
FLAT_DEG = 70.0

# ---------- per-minute features (ported from the canonical features.py, rate as a parameter) ----------
def tilt_deg(acc, upright):
    u = np.asarray(upright, float)
    u = u / np.linalg.norm(u)
    norm = np.linalg.norm(acc, axis=1)
    norm = np.where(norm == 0, 1e-9, norm)
    return np.degrees(np.arccos(np.clip((acc @ u) / norm, -1.0, 1.0)))

def _rolling_std_1s(mag, rate):
    w = rate
    if len(mag) < w:
        return np.zeros(0)
    c1 = np.cumsum(np.insert(mag, 0, 0.0))
    c2 = np.cumsum(np.insert(mag ** 2, 0, 0.0))
    s1, s2 = c1[w:] - c1[:-w], c2[w:] - c2[:-w]
    return np.sqrt(np.maximum(s2 / w - (s1 / w) ** 2, 0.0))

def detect_strikes(mag, rate):
    """Indices of cane-tip ground contacts: peaks in high-passed |a|, >= 0.4 s apart."""
    if len(mag) < 3:
        return np.array([], dtype=int)
    half = rate // 2
    padded = np.pad(mag, half, mode="edge")      # edge padding: zeros would fake peaks at the ends
    ma = np.convolve(padded, np.ones(rate + 1) / (rate + 1), mode="valid")
    hp = mag - ma
    min_gap = int(MIN_STRIKE_GAP_S * rate)
    cand = np.where((hp[1:-1] > T_STRIKE) & (hp[1:-1] >= hp[:-2]) & (hp[1:-1] >= hp[2:]))[0] + 1
    kept = []
    for i in cand:
        if not kept or i - kept[-1] >= min_gap:
            kept.append(int(i))
        elif hp[i] > hp[kept[-1]]:
            kept[-1] = int(i)
    return np.array(kept, dtype=int)

def minute_features(acc, upright, rate=OUT_HZ):
    """acc: (N,3) in g for one minute at `rate` Hz. Returns the feature fields of a MinuteRecord."""
    n = len(acc)
    if n == 0:
        return dict(n_samples=0, mag_mean=0.0, mag_std=0.0, mag_max=0.0, dyn_mean=0.0, active_s=0,
                    strike_count=0, strike_iv_mean=None, strike_iv_cv=None,
                    upright_s=0, flat_s=0, max_impact_g=0.0)
    mag = np.linalg.norm(acc, axis=1)
    rstd = _rolling_std_1s(mag, rate)
    active_s = int(round((rstd > T_ACTIVE).sum() / rate)) if len(rstd) else 0
    strikes = detect_strikes(mag, rate)
    iv_mean = iv_cv = None
    if len(strikes) >= 5:
        iv = np.diff(strikes) / rate
        iv_mean = float(iv.mean())
        iv_cv = float(iv.std() / iv.mean()) if iv.mean() > 0 else None
    tilt = tilt_deg(acc, upright)
    still = np.zeros(n, dtype=bool)
    if len(rstd):
        still[: len(rstd)] = rstd < T_ACTIVE
        still[len(rstd):] = still[len(rstd) - 1]  # trailing partial window inherits the last state
    return dict(
        n_samples=int(n),
        mag_mean=float(mag.mean()), mag_std=float(mag.std()), mag_max=float(mag.max()),
        dyn_mean=float(np.maximum(mag - 1.0, 0.0).mean()),
        active_s=min(active_s, 60),
        strike_count=int(len(strikes)),
        strike_iv_mean=iv_mean, strike_iv_cv=iv_cv,
        upright_s=int(round((tilt < UPRIGHT_DEG).sum() / rate)),
        flat_s=int(round(((tilt > FLAT_DEG) & still).sum() / rate)),
        max_impact_g=float(mag.max()),
    )

class CaneLink:
    def __init__(self, store, upright_vec, rate_hz=100):
        self.store, self.up = store, np.asarray(upright_vec, float)
        self.step = max(1, round(rate_hz / OUT_HZ))   # keep every Nth sample
        self.disabled = False
        self.count = 0
        self.minute = None                            # wall-clock minute index of the buffer
        self.buf = []

    def _safe(self, fn, *a, **k):
        if self.disabled:
            return
        try:
            fn(*a, **k)
        except Exception as e:
            self.disabled = True
            print(f"[link] outbox disabled: {e!r}")

    # ---------- minute aggregation ----------
    def feed(self, t, ax, ay, az):
        self._safe(self._feed, t, ax, ay, az)

    def _feed(self, t, ax, ay, az):
        m = int(t // 60)
        if self.minute is None:
            self.minute = m
        elif m != self.minute:
            self._close_minute()
            self.minute = m
        self.count += 1
        if self.count % self.step == 0:
            self.buf.append((ax, ay, az))

    def _close_minute(self):
        if self.buf:
            feats = minute_features(np.array(self.buf, float), self.up, OUT_HZ)
            self.store.add("minute", self.minute * 60000, feats)
        self.buf = []

    def flush(self):
        """Close the partial minute (shutdown)."""
        self._safe(self._close_minute)

    # ---------- events: written only once the outcome is known ----------
    def _event(self, kind, outcome, ts_ms, cause, **measured):
        p = dict(event_id=str(uuid.uuid4()), kind=kind, outcome=outcome, source="cane_reader", cause=cause)
        p.update({k: float(v) for k, v in measured.items() if v is not None})   # measured values only
        self.store.add("event", int(ts_ms), p)

    def fall_resolved(self, outcome, *, ts_ms, peak_g, tilt_deg, still_s, impact):
        cause = "cane_down_impact" if impact else "cane_down_still"
        self._safe(self._event, "potential_fall", outcome, ts_ms, cause,
                   peak_g=peak_g, tilt_deg=tilt_deg, still_s=still_s)

    def help_request(self, *, ts_ms):
        self._safe(self._event, "help_request", "escalated", ts_ms, "sos_hold")
