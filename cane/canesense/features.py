"""Per-minute feature extraction (MASTER.md 9.3). Thresholds are PROPOSED; tune on real data."""
from __future__ import annotations

import numpy as np

from cane.common.schema import SAMPLE_RATE_HZ

T_ACTIVE = 0.05   # g, 1-s rolling std of |a| above this = cane in motion
T_STRIKE = 0.35   # g, high-pass |a| peak height for a ground contact
MIN_STRIKE_GAP_S = 0.4
UPRIGHT_DEG = 30.0
FLAT_DEG = 70.0


def tilt_deg(acc: np.ndarray, upright: np.ndarray) -> np.ndarray:
    """Angle (deg) between each sample's gravity direction and the calibrated upright vector."""
    u = upright / np.linalg.norm(upright)
    norm = np.linalg.norm(acc, axis=1)
    norm = np.where(norm == 0, 1e-9, norm)
    cos = np.clip((acc @ u) / norm, -1.0, 1.0)
    return np.degrees(np.arccos(cos))


def _rolling_std_1s(mag: np.ndarray) -> np.ndarray:
    w = SAMPLE_RATE_HZ
    if len(mag) < w:
        return np.zeros(0)
    c1 = np.cumsum(np.insert(mag, 0, 0.0))
    c2 = np.cumsum(np.insert(mag**2, 0, 0.0))
    s1 = c1[w:] - c1[:-w]
    s2 = c2[w:] - c2[:-w]
    var = np.maximum(s2 / w - (s1 / w) ** 2, 0.0)
    return np.sqrt(var)


def detect_strikes(mag: np.ndarray) -> np.ndarray:
    """Indices of cane-tip ground contacts: peaks in high-passed |a|, >= 0.4 s apart."""
    if len(mag) < 3:
        return np.array([], dtype=int)
    half = SAMPLE_RATE_HZ // 2
    padded = np.pad(mag, half, mode="edge")  # edge padding: zero padding would fake peaks at the ends
    ma = np.convolve(padded, np.ones(SAMPLE_RATE_HZ + 1) / (SAMPLE_RATE_HZ + 1), mode="valid")
    hp = mag - ma
    min_gap = int(MIN_STRIKE_GAP_S * SAMPLE_RATE_HZ)
    cand = np.where((hp[1:-1] > T_STRIKE) & (hp[1:-1] >= hp[:-2]) & (hp[1:-1] >= hp[2:]))[0] + 1
    kept: list[int] = []
    for i in cand:
        if not kept or i - kept[-1] >= min_gap:
            kept.append(int(i))
        elif hp[i] > hp[kept[-1]]:
            kept[-1] = int(i)
    return np.array(kept, dtype=int)


def minute_features(acc: np.ndarray, upright: np.ndarray) -> dict:
    """acc: (N,3) in g for one minute. Returns the feature fields of a MinuteRecord."""
    n = len(acc)
    if n == 0:
        return dict(n_samples=0, mag_mean=0.0, mag_std=0.0, mag_max=0.0, dyn_mean=0.0, active_s=0,
                    strike_count=0, strike_iv_mean=None, strike_iv_cv=None,
                    upright_s=0, flat_s=0, max_impact_g=0.0)
    mag = np.linalg.norm(acc, axis=1)
    rstd = _rolling_std_1s(mag)
    active_s = int(round((rstd > T_ACTIVE).sum() / SAMPLE_RATE_HZ)) if len(rstd) else 0
    strikes = detect_strikes(mag)
    iv_mean = iv_cv = None
    if len(strikes) >= 5:
        iv = np.diff(strikes) / SAMPLE_RATE_HZ
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
        upright_s=int(round((tilt < UPRIGHT_DEG).sum() / SAMPLE_RATE_HZ)),
        flat_s=int(round(((tilt > FLAT_DEG) & still).sum() / SAMPLE_RATE_HZ)),
        max_impact_g=float(mag.max()),
    )
