import numpy as np

from backend.app.analytics import stats
from backend.sim.generate import simulate


def test_baseline_ignores_missing_days_and_needs_enough_days():
    s = np.full(30, 60.0)
    s[3] = s[8] = np.nan
    b = stats.compute_baseline(s)
    assert b and b.n_days == 14 and b.median == 60.0
    assert stats.compute_baseline(np.array([60.0] * 5)) is None


def test_missing_days_are_not_zero():
    s = np.full(20, 50.0)
    s[10] = np.nan
    assert stats.rolling_median_valid(s)[10] == 50.0


def test_stable_series_has_few_false_flags():
    false = 0
    for seed in range(50):
        rng = np.random.default_rng(seed)
        s = 60 * (1 + rng.normal(0, 0.1, 100))
        b = stats.compute_baseline(s)
        false += len([f for f in stats.sustained_change(s, b) if f["day_index"] >= 14])
    per_100_days = false / 50
    assert per_100_days < 3, per_100_days


def test_injected_step_is_detected_with_short_delay():
    rng = np.random.default_rng(3)
    s = 60 * (1 + rng.normal(0, 0.1, 80))
    s[40:] *= 0.8
    b = stats.compute_baseline(s)
    down = [f for f in stats.sustained_change(s, b) if f["direction"] == "down" and f["day_index"] >= 40]
    assert down and down[0]["day_index"] - 40 <= 10


def test_simulated_decline_flagged_and_slope_negative():
    sim = simulate()
    a = sim["active_min"]
    b = stats.compute_baseline(a)
    flags = stats.sustained_change(a, b)
    assert any(f["direction"] == "down" and f["day_index"] > 28 for f in flags)
    slope, lo, hi = stats.theil_sen(a[28:])
    assert slope < 0 and lo <= slope <= hi
    assert sim["is_simulated"] is True
