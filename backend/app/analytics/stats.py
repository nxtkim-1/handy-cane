"""Longitudinal analysis with robust statistics, no ML (MASTER.md 9.4, 10.4).

Invalid days are passed as NaN and are excluded everywhere; they are never treated as zero.
All parameters are PROPOSED and live in CONFIG.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CONFIG = dict(
    min_coverage_h=10.0,       # valid-day rule: coverage hours between 07:00-22:00 local
    min_valid_days_report=8,   # of 14
    baseline_days=14,
    baseline_min_days=10,
    z_threshold=1.5,
    z_days_required=5,         # of the last 7 valid days
    rolling_days=7,
    cusum_k=0.5,
    cusum_h=4.0,
    mad_floor_frac=0.05,       # MAD floor as a fraction of |median|, avoids divide-by-small
)


def is_valid_day(coverage_h: float) -> bool:
    return coverage_h >= CONFIG["min_coverage_h"]


@dataclass
class Baseline:
    median: float
    mad: float
    n_days: int


def compute_baseline(series: np.ndarray) -> Baseline | None:
    """Median/MAD over the first `baseline_days` VALID days. None if fewer than baseline_min_days."""
    valid = series[~np.isnan(series)][: CONFIG["baseline_days"]]
    if len(valid) < CONFIG["baseline_min_days"]:
        return None
    med = float(np.median(valid))
    mad = float(np.median(np.abs(valid - med)))
    return Baseline(med, mad, len(valid))


def robust_z(x: np.ndarray, b: Baseline) -> np.ndarray:
    scale = 1.4826 * max(b.mad, CONFIG["mad_floor_frac"] * abs(b.median), 1e-9)
    return (x - b.median) / scale


def rolling_median_valid(series: np.ndarray, window: int | None = None) -> np.ndarray:
    """Rolling median over the last `window` VALID days (NaN where there is no valid day yet)."""
    window = window or CONFIG["rolling_days"]
    out = np.full(len(series), np.nan)
    for i in range(len(series)):
        v = series[: i + 1]
        v = v[~np.isnan(v)][-window:]
        if len(v):
            out[i] = np.median(v)
    return out


def sustained_change(series: np.ndarray, b: Baseline) -> list[dict]:
    """Flag days where the rolling-median z is beyond +-z_threshold on >= z_days_required of the
    last 7 valid days, plus one-sided CUSUM alarms. Returns flags {day_index, direction, method, value}."""
    flags: list[dict] = []
    z = robust_z(series, b)
    rm_z = robust_z(rolling_median_valid(series), b)
    thr, need, w = CONFIG["z_threshold"], CONFIG["z_days_required"], CONFIG["rolling_days"]
    for i in range(len(series)):
        if np.isnan(series[i]):
            continue
        hist = rm_z[: i + 1]
        hist = hist[~np.isnan(series[: i + 1])][-w:]
        if len(hist) < w:
            continue
        for direction, count in (("down", (hist < -thr).sum()), ("up", (hist > thr).sum())):
            if count >= need:
                flags.append(dict(day_index=i, direction=direction, method="rolling_median_z", value=float(hist[-1])))
    k, h = CONFIG["cusum_k"], CONFIG["cusum_h"]
    pos = neg = 0.0
    for i, zi in enumerate(z):
        if np.isnan(zi):
            continue
        pos = max(0.0, pos + zi - k)
        neg = max(0.0, neg - zi - k)
        if pos > h:
            flags.append(dict(day_index=i, direction="up", method="cusum", value=float(pos)))
            pos = 0.0
        if neg > h:
            flags.append(dict(day_index=i, direction="down", method="cusum", value=float(neg)))
            neg = 0.0
    return flags


def theil_sen(y: np.ndarray, x: np.ndarray | None = None, conf: float = 0.90):
    """Theil-Sen slope with a bootstrap-free pairwise-slope percentile interval.

    Returns (slope, lo, hi) over valid (non-NaN) points, or None if fewer than 4 points. The interval
    is the central `conf` range of pairwise slopes - descriptive, narrower than a formal CI.
    """
    x = np.arange(len(y), dtype=float) if x is None else np.asarray(x, float)
    m = ~np.isnan(y)
    x, y = x[m], y[m]
    if len(y) < 4:
        return None
    i, j = np.triu_indices(len(y), k=1)
    dx = x[j] - x[i]
    ok = dx != 0
    slopes = (y[j] - y[i])[ok] / dx[ok]
    a = (1 - conf) / 2 * 100
    return float(np.median(slopes)), float(np.percentile(slopes, a)), float(np.percentile(slopes, 100 - a))


def compare_periods(current: np.ndarray, previous: np.ndarray, baseline: Baseline | None) -> dict:
    """Median of the valid days in each period and percentage changes (descriptive)."""
    def med(v):
        v = v[~np.isnan(v)]
        return float(np.median(v)) if len(v) else None

    cur, prev = med(current), med(previous)
    pct = lambda a, b: None if a is None or b in (None, 0) else round(100 * (a - b) / b, 1)
    return dict(
        current_median=cur, previous_median=prev,
        baseline_median=None if baseline is None else baseline.median,
        change_vs_previous_pct=pct(cur, prev),
        change_vs_baseline_pct=pct(cur, None if baseline is None else baseline.median),
    )
