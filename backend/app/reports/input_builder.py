"""Build the privacy-safe report_input dict (MASTER.md 14.4).

No names, no dates. `report_ref` is random. All numbers are computed here, never by Gemini.
"""
from __future__ import annotations

import secrets

import numpy as np

from backend.app.analytics import stats

PERIOD_DAYS = 14

METRIC_INFO = {
    "active_min": ("Cane-active minutes per day", "min/day"),
    "strikes": ("Cane steps per day", "count/day"),
    "bout_median_s": ("Typical walking-bout length", "seconds"),
    "bouts": ("Walking bouts per day", "count/day"),
    "bout_longest_s": ("Longest walking bout", "seconds"),
    "rhythm_cv_median": ("Cane rhythm variability", "ratio"),
}
DEFAULT_EVENTS = dict(potential_fall_escalated=0, potential_fall_cancelled=0, help_requests=0,
                      dismissed_as_false_alarm=0)


def _r(x, nd=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), nd)


def _sustained(full: np.ndarray, base) -> str:
    """Direction of the most recent flag raised inside the current period, else 'none'."""
    if base is None:
        return "none"
    cutoff = len(full) - PERIOD_DAYS
    recent = [f for f in stats.sustained_change(full, base) if f["day_index"] >= cutoff]
    return max(recent, key=lambda f: f["day_index"])["direction"] if recent else "none"


def build_report_input(series: dict, baselines: dict | None = None, *, coverage_h=None,
                       events: dict | None = None, activity_timing: dict | None = None,
                       is_simulated: bool = False, time_uncertain_minutes: int = 0,
                       report_ref: str | None = None) -> dict:
    """series: metric -> array (NaN = invalid day). The last 28 entries are previous (14) + current (14)
    period; earlier entries (if any) are only used to compute the baseline and change flags.
    baselines: optional metric -> stats.Baseline; default computed from the full series.
    coverage_h: optional daily coverage-hours array aligned with the series.
    A day counts as valid if at least one metric has a value that day."""
    if not series:
        raise ValueError("series is empty")
    arrs = {k: np.asarray(v, dtype=float) for k, v in series.items()}
    lengths = {len(a) for a in arrs.values()}
    if len(lengths) != 1 or lengths.pop() < 2 * PERIOD_DAYS:
        raise ValueError("all series must have the same length, at least 28 days")
    ref = report_ref or "r-" + secrets.token_hex(2)

    stack = np.vstack(list(arrs.values()))
    day_valid = ~np.all(np.isnan(stack), axis=0)
    cur_valid = int(day_valid[-PERIOD_DAYS:].sum())
    med_cov = None
    if coverage_h is not None:
        cov = np.asarray(coverage_h, float)[-PERIOD_DAYS:]
        cov = cov[day_valid[-PERIOD_DAYS:] & ~np.isnan(cov)]
        med_cov = _r(np.median(cov)) if len(cov) else None
    completeness = dict(valid_days=cur_valid, total_days=PERIOD_DAYS, median_coverage_h=med_cov,
                        time_uncertain_minutes=int(time_uncertain_minutes))
    out = dict(report_ref=ref, period_days=PERIOD_DAYS, data_completeness=completeness,
               insufficient_data=cur_valid < stats.CONFIG["min_valid_days_report"],
               metrics=[], events={**DEFAULT_EVENTS, **(events or {})},
               activity_timing=activity_timing or dict(most_active_hours_local=[], shift_vs_baseline="none"),
               is_simulated=bool(is_simulated))
    if out["insufficient_data"]:
        return out  # completeness only (MASTER 9.4)

    for key, full in arrs.items():
        cur, prev = full[-PERIOD_DAYS:], full[-2 * PERIOD_DAYS:-PERIOD_DAYS]
        base = (baselines or {}).get(key) or stats.compute_baseline(full)
        cmp = stats.compare_periods(cur, prev, base)
        ts = stats.theil_sen(cur)
        label, unit = METRIC_INFO.get(key, (key, ""))
        out["metrics"].append(dict(
            key=key, label=label, unit=unit,
            current_median=_r(cmp["current_median"]), previous_median=_r(cmp["previous_median"]),
            baseline_median=_r(cmp["baseline_median"]),
            change_vs_previous_pct=_r(cmp["change_vs_previous_pct"]),
            change_vs_baseline_pct=_r(cmp["change_vs_baseline_pct"]),
            trend_slope_per_week=_r(ts[0] * 7) if ts else None,
            trend_ci90=[_r(ts[1] * 7), _r(ts[2] * 7)] if ts else None,
            sustained_change=_sustained(full, base)))
    return out
