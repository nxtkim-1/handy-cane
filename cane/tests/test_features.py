import numpy as np

from cane.canesense.features import minute_features

UP = np.array([0.0, 0.0, 1.0])
HZ = 50


def walking_minute(rng, strikes_per_s=1.0, seconds=60):
    n = seconds * HZ
    acc = np.tile(UP, (n, 1)) + rng.normal(0, 0.01, (n, 3))
    for k in range(int(seconds * strikes_per_s)):
        i = int(k * HZ / strikes_per_s) + 10
        if i < n:
            acc[i, 2] += 0.9
    return acc


def test_idle_minute_has_no_activity():
    rng = np.random.default_rng(0)
    f = minute_features(np.tile(UP, (3000, 1)) + rng.normal(0, 0.005, (3000, 3)), UP)
    assert f["n_samples"] == 3000 and f["active_s"] == 0 and f["strike_count"] == 0
    assert f["upright_s"] == 60 and f["flat_s"] == 0


def test_walking_minute_counts_strikes_with_regular_rhythm():
    f = minute_features(walking_minute(np.random.default_rng(0)), UP)
    assert 50 <= f["strike_count"] <= 60
    assert f["strike_iv_mean"] and abs(f["strike_iv_mean"] - 1.0) < 0.1
    assert f["strike_iv_cv"] < 0.1 and f["active_s"] > 40


def test_cane_lying_flat_is_flat_not_upright():
    acc = np.tile([1.0, 0, 0.0], (3000, 1))
    f = minute_features(acc, UP)
    assert f["flat_s"] == 60 and f["upright_s"] == 0


def test_empty_minute_is_reported_as_zero_samples():
    assert minute_features(np.zeros((0, 3)), UP)["n_samples"] == 0
