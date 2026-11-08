"""Daily metrics job (MASTER 9.4, 9.5) and longitudinal analytics refresh (10.4).

Rules implemented here:
- A minute is "covered" iff n_samples >= 0.9 * 3000 and time_quality != 'unsynced'. Only covered minutes feed any metric.
- A day is valid iff covered minutes inside 07:00-22:00 local >= 10 h (CONFIG["min_coverage_h"]).
- Invalid days keep their coverage figure but every metric is NULL. Days with no rows at all get no daily row.
  Missing data is never stored or reported as zero.
- Days are patient-local (IANA timezone, DST-safe because each UTC minute is converted individually).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from backend.app.analytics import stats as st
from backend.app.models import (Baseline, ChangeFlag, DailyMetric, DeviceAssignment, DeviceEvent, MinuteMetric,
                                Patient)

MIN_SAMPLES = int(0.9 * 3000)
WINDOW_START_H, WINDOW_END_H = 7, 22
BOUT_MIN_STRIKES = 10
RHYTHM_MIN_STRIKES = 20
BOUT_MAX_GAP_MIN = 1  # merge across gaps of <= 1 minute
ANALYSED_METRICS = ("active_min", "strikes", "bout_median_s")


def is_covered(n_samples: int, time_quality: str) -> bool:
    return n_samples >= MIN_SAMPLES and time_quality != "unsynced"


def _bouts(covered: list[tuple[int, int]]) -> list[float]:
    """covered: (minute_index, strike_count). Returns bout durations in seconds."""
    idx = sorted(i for i, strikes in covered if strikes >= BOUT_MIN_STRIKES)
    out: list[float] = []
    start = prev = None
    for i in idx:
        if start is None:
            start = prev = i
        elif i - prev - 1 <= BOUT_MAX_GAP_MIN:
            prev = i
        else:
            out.append((prev - start + 1) * 60.0)
            start = prev = i
    if start is not None:
        out.append((prev - start + 1) * 60.0)
    return out


def compute_day(minutes: list[dict], events: list[dict], tz: ZoneInfo) -> dict:
    """Pure function. minutes: dicts with ts (aware UTC), n_samples, time_quality, active_s, strike_count,
    strike_iv_cv. events: dicts with kind, outcome. All belong to one local day."""
    cov = [m for m in minutes if is_covered(m["n_samples"], m["time_quality"])]
    coverage_h = len(cov) / 60.0
    in_window = sum(1 for m in cov if WINDOW_START_H <= m["ts"].astimezone(tz).hour < WINDOW_END_H)
    valid = in_window / 60.0 >= st.CONFIG["min_coverage_h"]
    res = dict(
        valid=valid, coverage_h=round(coverage_h, 3),
        active_min=None, strikes=None, bouts=None, bout_median_s=None, bout_longest_s=None,
        rhythm_cv_median=None, active_by_hour=None,
        events_potential_fall=sum(1 for e in events if e["kind"] == "potential_fall"),
        events_cancelled=sum(1 for e in events if e["outcome"] == "cancelled_by_user"),
        help_presses=sum(1 for e in events if e["kind"] == "help_request"),
    )
    if not valid:
        return res
    res["active_min"] = round(sum(m["active_s"] for m in cov) / 60.0, 3)
    res["strikes"] = int(sum(m["strike_count"] for m in cov))
    bouts = _bouts([(int(m["ts"].timestamp() // 60), m["strike_count"]) for m in cov])
    res["bouts"] = len(bouts)
    if bouts:
        res["bout_median_s"] = float(median(bouts))
        res["bout_longest_s"] = float(max(bouts))
    cvs = [m["strike_iv_cv"] for m in cov if m["strike_count"] >= RHYTHM_MIN_STRIKES and m["strike_iv_cv"] is not None]
    if cvs:
        res["rhythm_cv_median"] = float(median(cvs))
    hours = [0.0] * 24
    for m in cov:
        hours[m["ts"].astimezone(tz).hour] += m["active_s"] / 60.0
    res["active_by_hour"] = [int(round(h)) for h in hours]
    return res


def _assignments(db: Session, patient_id) -> list[DeviceAssignment]:
    return list(db.scalars(select(DeviceAssignment).where(DeviceAssignment.patient_id == patient_id)))


def _window_filter(col, a: DeviceAssignment):
    cond = [col >= a.valid_from]
    if a.valid_to is not None:
        cond.append(col < a.valid_to)
    return and_(*cond)


def recompute_daily(db: Session, patient_id, days: set[date] | None = None) -> list[date]:
    """Recompute daily_metrics for the patient (all days, or only `days`). Returns the days written."""
    patient = db.get(Patient, patient_id)
    tz = ZoneInfo(patient.timezone)
    assigns = _assignments(db, patient_id)
    if not assigns:
        return []
    lo = hi = None
    if days:
        lo = datetime.combine(min(days) - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        hi = datetime.combine(max(days) + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)

    mcols = (MinuteMetric.ts, MinuteMetric.n_samples, MinuteMetric.time_quality, MinuteMetric.active_s,
             MinuteMetric.strike_count, MinuteMetric.strike_iv_cv, MinuteMetric.is_simulated)
    by_day_m: dict[date, list[dict]] = defaultdict(list)
    by_day_e: dict[date, list[dict]] = defaultdict(list)
    simulated: dict[date, bool] = defaultdict(bool)
    for a in assigns:
        q = select(*mcols).where(MinuteMetric.device_id == a.device_id, _window_filter(MinuteMetric.ts, a))
        eq = select(DeviceEvent.ts, DeviceEvent.kind, DeviceEvent.outcome, DeviceEvent.is_simulated).where(
            DeviceEvent.device_id == a.device_id, _window_filter(DeviceEvent.ts, a))
        if lo:
            q = q.where(MinuteMetric.ts >= lo, MinuteMetric.ts < hi)
            eq = eq.where(DeviceEvent.ts >= lo, DeviceEvent.ts < hi)
        for r in db.execute(q):
            d = r.ts.astimezone(tz).date()
            by_day_m[d].append(dict(ts=r.ts, n_samples=r.n_samples, time_quality=r.time_quality,
                                    active_s=r.active_s, strike_count=r.strike_count, strike_iv_cv=r.strike_iv_cv))
            simulated[d] |= bool(r.is_simulated)
        for r in db.execute(eq):
            d = r.ts.astimezone(tz).date()
            by_day_e[d].append(dict(kind=r.kind, outcome=r.outcome))
            simulated[d] |= bool(r.is_simulated)

    written = []
    for d in sorted(set(by_day_m) | set(by_day_e)):
        if days is not None and d not in days:
            continue
        vals = compute_day(by_day_m.get(d, []), by_day_e.get(d, []), tz)
        row = db.get(DailyMetric, (patient_id, d)) or DailyMetric(patient_id=patient_id, day=d)
        for k, v in vals.items():
            setattr(row, k, v)
        row.is_simulated = simulated[d]
        row.computed_at = datetime.now(timezone.utc)
        db.add(row)
        written.append(d)
    db.flush()
    return written


# ---------------------------------------------------------------- analytics (10.4)

def metric_series(db: Session, patient_id, metrics=ANALYSED_METRICS):
    """Returns (first_day, {metric: np.ndarray}) with NaN for invalid and absent days."""
    rows = list(db.scalars(select(DailyMetric).where(DailyMetric.patient_id == patient_id).order_by(DailyMetric.day)))
    if not rows:
        return None, {}
    first, last = rows[0].day, rows[-1].day
    n = (last - first).days + 1
    out = {m: np.full(n, np.nan) for m in metrics}
    for r in rows:
        if not r.valid:
            continue
        for m in metrics:
            v = getattr(r, m)
            if v is not None:
                out[m][(r.day - first).days] = v
    return first, out


def baseline_stats(series: dict[str, np.ndarray]) -> dict:
    stats = {}
    for m, s in series.items():
        b = st.compute_baseline(s)
        if b is not None:
            stats[m] = {"median": b.median, "mad": b.mad, "n_days": b.n_days}
    return stats


def set_baseline(db: Session, patient_id, start: date, end: date, set_by=None) -> Baseline | None:
    """Create a new active baseline from valid days in [start, end]. Returns None if too few valid days."""
    first, series = metric_series(db, patient_id)
    if first is None:
        return None
    a, b = (start - first).days, (end - first).days + 1
    a = max(a, 0)
    sliced = {m: s[a:b] for m, s in series.items()}
    stats = baseline_stats(sliced)
    n_valid = int((~np.isnan(sliced["active_min"])).sum()) if len(sliced.get("active_min", [])) else 0
    if not stats:
        return None
    for old in db.scalars(select(Baseline).where(Baseline.patient_id == patient_id, Baseline.is_active.is_(True))):
        old.is_active = False
    db.flush()
    bl = Baseline(patient_id=patient_id, start_day=start, end_day=end, n_valid_days=n_valid, stats=stats,
                  is_active=True, set_by=set_by)
    db.add(bl)
    db.flush()
    return bl


def refresh_analytics(db: Session, patient_id) -> None:
    """Auto-create the initial baseline if none exists (never re-baselines), then refresh change flags."""
    first, series = metric_series(db, patient_id)
    if first is None:
        return
    bl = db.scalars(select(Baseline).where(Baseline.patient_id == patient_id, Baseline.is_active.is_(True))).first()
    if bl is None:
        stats = baseline_stats(series)
        if not stats:
            return
        valid_idx = np.where(~np.isnan(series["active_min"]))[0][: st.CONFIG["baseline_days"]]
        bl = Baseline(patient_id=patient_id, start_day=first + timedelta(days=int(valid_idx[0])),
                      end_day=first + timedelta(days=int(valid_idx[-1])), n_valid_days=len(valid_idx),
                      stats=stats, is_active=True, set_by=None)
        db.add(bl)
        db.flush()
    db.execute(delete(ChangeFlag).where(ChangeFlag.patient_id == patient_id))
    for m, s in series.items():
        ms = bl.stats.get(m)
        if not ms:
            continue
        b = st.Baseline(ms["median"], ms["mad"], ms["n_days"])
        for f in st.sustained_change(s, b):
            day = first + timedelta(days=f["day_index"])
            key = (patient_id, m, day, f["method"])
            if db.get(ChangeFlag, key) is None:
                db.add(ChangeFlag(patient_id=patient_id, metric=m, day=day, direction=f["direction"],
                                  method=f["method"], value=f["value"]))
    db.flush()


def run_daily_job(db: Session, patient_id, days: set[date] | None = None) -> list[date]:
    written = recompute_daily(db, patient_id, days)
    refresh_analytics(db, patient_id)
    db.commit()
    return written
