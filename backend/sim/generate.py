"""Synthetic patient history (MASTER.md 19.2). Everything produced here is simulated.

Daily-level generator: used to test change detection and to seed the demo. Missing days are NaN.
"""
from __future__ import annotations

import numpy as np

SCENARIO = dict(
    days=56,
    baseline_active_min=66.0,
    baseline_bout_s=90.0,
    decline_start_day=28,           # days 29-56 decline
    active_decline_per_week=0.05,
    bout_decline_per_week=0.04,
    missing_days=(19, 41),          # device-off days (0-indexed)
    noise_frac=0.07,
)


def simulate(seed: int = 7, **overrides) -> dict:
    cfg = {**SCENARIO, **overrides}
    rng = np.random.default_rng(seed)
    n = cfg["days"]
    weeks_declining = np.clip((np.arange(n) - cfg["decline_start_day"]) / 7.0, 0, None)
    active = cfg["baseline_active_min"] * (1 - cfg["active_decline_per_week"]) ** weeks_declining
    bout = cfg["baseline_bout_s"] * (1 - cfg["bout_decline_per_week"]) ** weeks_declining
    weekend = np.array([1.0 if d % 7 not in (5, 6) else 0.85 for d in range(n)])
    active = active * weekend * (1 + rng.normal(0, cfg["noise_frac"], n))
    bout = bout * (1 + rng.normal(0, cfg["noise_frac"], n))
    for d in cfg["missing_days"]:
        if d < n:
            active[d] = bout[d] = np.nan
    return dict(active_min=active, bout_median_s=bout, is_simulated=True, config=cfg)
