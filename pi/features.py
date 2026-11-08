"""Window features shared by training (train_events.py) and the live reader."""
import numpy as np

FEATURES = ["mag_mean", "mag_std", "mag_max", "dyn_mean", "dyn_max", "jerk_max",
            "tilt_mean", "tilt_max", "tilt_change", "peaks"]

def tilt_deg(vec, up):
    v = vec / (np.linalg.norm(vec, axis=-1, keepdims=True) + 1e-9)
    return np.degrees(np.arccos(np.clip(v @ up, -1, 1)))

def window_features(acc_g, up, hz=100):
    """acc_g: (N, 3) accelerometer window in g. up: unit vector of 'cane upright'."""
    mag = np.linalg.norm(acc_g, axis=1)
    k = max(1, hz // 5)                                  # 0.2 s moving average = gravity estimate
    kernel = np.ones(k) / k
    grav = np.column_stack([np.convolve(acc_g[:, i], kernel, mode="same") for i in range(3)])
    dyn = np.linalg.norm(acc_g - grav, axis=1)
    jerk = np.abs(np.diff(mag)) * hz
    tilt = tilt_deg(grav, up)
    peaks = int(np.sum((dyn[1:-1] > 0.45) & (dyn[1:-1] >= dyn[:-2]) & (dyn[1:-1] >= dyn[2:])))
    return {
        "mag_mean": mag.mean(), "mag_std": mag.std(), "mag_max": mag.max(),
        "dyn_mean": dyn.mean(), "dyn_max": dyn.max(), "jerk_max": jerk.max() if len(jerk) else 0.0,
        "tilt_mean": tilt.mean(), "tilt_max": tilt.max(), "tilt_change": tilt[-k:].mean() - tilt[:k].mean(),
        "peaks": peaks,
    }
