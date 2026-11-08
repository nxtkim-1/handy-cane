"""Seeded synthetic labelled sessions for every label, so the evaluation pipeline can be tested
without hardware. The signals are physically motivated sketches (gravity vector at a given tilt, strike
pulses, impact spikes, free-fall dips, vibration), NOT a substitute for real data: real thresholds must
be tuned on volunteers (docs/DATA_COLLECTION.md).

    python -m tools.synth_sessions --out data/synth --seed 0
Every segment generator starts near upright and ends upright (cane picked up), so segments can be chained.
"""
from __future__ import annotations

import argparse
import os
from typing import Callable, Optional

import numpy as np

from tools.session import LABELS, Session, save

HZ = 50
Z = np.array([0.0, 0.0, 1.0])


# ------------------------------------------------------------------ building blocks
def gvec(tilt_deg, phi_deg=0.0) -> np.ndarray:
    """Gravity vector (n,3) for a cane tilted tilt_deg from upright towards azimuth phi_deg."""
    t = np.radians(np.atleast_1d(tilt_deg).astype(float))
    p = np.radians(np.atleast_1d(phi_deg).astype(float))
    t, p = np.broadcast_arrays(t, p)
    return np.stack([np.sin(t) * np.cos(p), np.sin(t) * np.sin(p), np.cos(t)], axis=1)


def smoothstep(n: int) -> np.ndarray:
    x = np.linspace(0.0, 1.0, max(n, 2))
    return x * x * (3 - 2 * x)


def hold(rng, secs, tilt, phi=0.0, noise=0.006) -> np.ndarray:
    n = max(int(round(secs * HZ)), 1)
    return gvec(np.full(n, tilt), np.full(n, phi)) + rng.normal(0, noise, (n, 3))


def move(rng, secs, t0, t1, phi=0.0, noise=0.12) -> np.ndarray:
    """Smooth tilt change t0 -> t1 with hand-handling noise."""
    n = max(int(round(secs * HZ)), 2)
    s = smoothstep(n)
    return gvec(t0 + (t1 - t0) * s, np.full(n, phi)) + rng.normal(0, noise, (n, 3))


def spike(acc: np.ndarray, i: int, amp: float, direction: Optional[np.ndarray] = None, ring: bool = True) -> None:
    """Add a short impact (and a decaying ring-down) to acc in place."""
    d = Z if direction is None else direction / np.linalg.norm(direction)
    shape = [1.0, 0.55, -0.35, 0.2, -0.1] if ring else [1.0]
    for k, w in enumerate(shape):
        if 0 <= i + k < len(acc):
            acc[i + k] += amp * w * d


# ------------------------------------------------------------------ segment generators: (acc, button)
def seg_idle(rng, secs=45.0):
    return hold(rng, secs, rng.uniform(1, 5), rng.uniform(0, 360)), None


def seg_walk(rng, secs=120.0, slow=False):
    n = int(secs * HZ)
    tt = np.arange(n) / HZ
    f_sway = rng.uniform(0.35, 0.55) if not slow else rng.uniform(0.2, 0.3)
    tilt = 15 + 8 * np.sin(2 * np.pi * f_sway * tt + rng.uniform(0, 6))
    acc = gvec(tilt, 90 * np.sin(2 * np.pi * f_sway * tt)) + rng.normal(0, 0.02, (n, 3))
    acc[:, 0] += 0.05 * np.sin(2 * np.pi * 2 * f_sway * tt)  # body sway acceleration
    mean_iv, cv, amp = (1.0, 0.05, (0.6, 1.0)) if not slow else (1.5, 0.15, (0.35, 0.6))
    t = rng.uniform(0.3, 1.0)
    while t < secs - 0.3:
        spike(acc, int(t * HZ), rng.uniform(*amp), np.array([0.15, 0.0, 1.0]), ring=False)
        spike(acc, int(t * HZ) + 1, 0.4 * rng.uniform(*amp), np.array([0.15, 0.0, 1.0]), ring=False)
        t += max(mean_iv * (1 + cv * rng.normal()), 0.5)
    return acc, None


def seg_sit(rng, secs=60.0):
    parts, left, tilt = [], secs, 18.0
    while left > 0:
        d = min(rng.uniform(8, 25), left)
        parts.append(hold(rng, d, tilt, 40.0))
        left -= d
        if left > 1:
            new = float(np.clip(tilt + rng.uniform(-8, 8), 8, 30))
            parts.append(move(rng, 0.6, tilt, new, 40.0, noise=0.08))
            tilt, left = new, left - 0.6
    return np.concatenate(parts), None


def seg_lean(rng, secs=60.0):
    tilt = rng.uniform(25, 35)
    a = np.concatenate([hold(rng, 1.0, 5), move(rng, 0.8, 5, tilt, 120.0),
                        hold(rng, max(secs - 3.8, 1.0), tilt, 120.0), move(rng, 1.0, tilt, 5, 120.0),
                        hold(rng, 1.0, 5)])
    spike(a, int(1.8 * HZ), rng.uniform(0.5, 0.9), ring=True)  # settles against the wall
    return a, None


def seg_car(rng, secs=120.0):
    """Cane laid flat on the seat while driving: sustained vibration, bumps, short stops."""
    n = int(secs * HZ)
    tt = np.arange(n) / HZ
    flat = gvec(np.full(n, rng.uniform(75, 85)), np.full(n, 200.0))
    stopped = np.zeros(n, bool)
    t = rng.uniform(15, 40)
    while t < secs - 10:
        d = rng.uniform(3, 6)
        stopped[int(t * HZ): int((t + d) * HZ)] = True
        t += d + rng.uniform(30, 70)
    vib = rng.normal(0, 1, n) * np.where(stopped, 0.02, 0.09)
    sway = 0.12 * np.sin(2 * np.pi * 0.3 * tt + rng.uniform(0, 6)) * (~stopped)
    acc = flat + np.stack([sway, 0.5 * sway, vib], axis=1) + rng.normal(0, 0.01, (n, 3))
    for _ in range(int(secs / 12)):
        i = int(rng.uniform(5, secs - 5) * HZ)
        if not stopped[i]:
            spike(acc, i, rng.uniform(0.4, 0.9), np.array([0, 0, 1.0]))
    head = np.concatenate([hold(rng, 1.0, 5), move(rng, 1.5, 5, 80, 200.0, noise=0.12)])
    tail = np.concatenate([move(rng, 1.2, 80, 6, 200.0, noise=0.12), hold(rng, 1.0, 5)])
    return np.concatenate([head, acc, tail]), None


def seg_floor_tap(rng, secs=18.0):
    a = hold(rng, secs, rng.uniform(5, 12), 0.0, noise=0.01)
    t = rng.uniform(1.5, 3.0)
    while t < secs - 2.5:
        spike(a, int(t * HZ), rng.uniform(3.4, 5.5), np.array([0.1, 0, 1.0]))
        t += rng.uniform(1.0, 4.0)
    return a, None


def _pickup(rng, hold_up=3.5):
    return np.concatenate([move(rng, 1.0, 85, 10, 0.0, noise=0.15), hold(rng, hold_up, 10, 0.0, noise=0.01)])


def seg_drop_hand(rng, lying_s=None):
    """Cane slips out of the hand and is picked up within ~1-2.5 s (the 'cane drop' hard negative)."""
    lying_s = rng.uniform(1.0, 2.5) if lying_s is None else lying_s
    phi = rng.uniform(0, 360)
    fall = rng.normal(0, 0.03, (int(0.25 * HZ), 3)) + gvec(np.linspace(8, 60, int(0.25 * HZ)), phi) * 0.15
    imp = hold(rng, lying_s + 0.4, rng.uniform(82, 90), phi)
    spike(imp, 0, rng.uniform(2.5, 5.0), gvec(80, phi)[0])
    spike(imp, int(0.15 * HZ), rng.uniform(1.0, 1.8), gvec(80, phi)[0])
    return np.concatenate([hold(rng, 2.0, 8, 0.0, noise=0.01), fall, imp, _pickup(rng)]), None


def seg_knock_over(rng, lying_s=None):
    """Leaned cane topples and is picked up some seconds later."""
    lying_s = rng.uniform(3.0, 7.0) if lying_s is None else lying_s
    phi = rng.uniform(0, 360)
    top = move(rng, 0.5, 30, 90, phi, noise=0.03) * np.linspace(1.0, 0.75, int(0.5 * HZ))[:, None]
    lie = hold(rng, lying_s, 88, phi)
    spike(lie, 0, rng.uniform(1.8, 3.5), gvec(80, phi)[0])
    return np.concatenate([hold(rng, 3.0, 30, phi), top, lie, _pickup(rng)]), None


def seg_fall_sim(rng, lying_s=None, soft=False, press_at_s=None):
    """Volunteer walks, falls onto a mat holding the cane, cane lies still, volunteer later gets up.
    press_at_s: seconds after impact when the volunteer presses the button briefly (None = no press)."""
    lying_s = rng.uniform(45.0, 70.0) if lying_s is None else lying_s
    phi = rng.uniform(0, 360)
    lead, _ = seg_walk(rng, 3.0)
    n_tumble = int(0.6 * HZ)
    tumble = move(rng, 0.6, 15, 90, phi, noise=0.4)
    amp = rng.uniform(2.2, 2.8) if soft else rng.uniform(3.5, 6.0)
    lie = hold(rng, lying_s, rng.uniform(80, 90), phi)
    spike(lie, 0, amp, gvec(80, phi)[0])
    spike(lie, int(0.3 * HZ), 0.5 * amp, gvec(80, phi)[0])
    pick = _pickup(rng, hold_up=5.0)
    acc = np.concatenate([lead, tumble, lie, pick])
    button = np.zeros(len(acc), bool)
    i0 = len(lead) + n_tumble
    if press_at_s is not None:
        button[i0 + int(press_at_s * HZ): i0 + int((press_at_s + 0.3) * HZ)] = True
    else:
        # nobody cancelled, so the FSM sits in ALERT until the volunteer long-presses on the cane
        j = i0 + len(lie) + int(1.2 * HZ)
        button[j: j + int(3.3 * HZ)] = True
    return acc, button


def seg_other(rng, secs=20.0):
    """Handling: carrying the cane horizontally, swinging it, setting it down and up again."""
    n = int(secs * HZ)
    walk = np.cumsum(rng.normal(0, 3.0, n))
    tilt = np.clip(45 + walk - walk.mean(), 0, 100)
    acc = gvec(tilt, rng.uniform(0, 360)) + rng.normal(0, 0.12, (n, 3))
    return np.concatenate([move(rng, 1.0, 5, tilt[0], 0.0), acc, move(rng, 1.0, tilt[-1], 5, 0.0), hold(rng, 1.0, 5)]), None


GENERATORS: dict[str, Callable] = {
    "walk": seg_walk, "idle": seg_idle, "sit": seg_sit, "lean": seg_lean, "drop_hand": seg_drop_hand,
    "knock_over": seg_knock_over, "floor_tap": seg_floor_tap, "fall_sim": seg_fall_sim, "car": seg_car,
    "other": seg_other,
}
assert set(GENERATORS) == set(LABELS)


# ------------------------------------------------------------------ session assembly
def _rotation_to(upright: np.ndarray) -> np.ndarray:
    """Rotation matrix taking +Z to `upright` (Rodrigues)."""
    u = upright / np.linalg.norm(upright)
    v = np.cross(Z, u)
    c = float(Z @ u)
    if np.linalg.norm(v) < 1e-12:
        return np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def build_session(plan: list[tuple[str, dict]], seed: int = 0, mount_deg: float = 0.0,
                  person: str = "synthetic") -> Session:
    """plan: [(label, kwargs for that generator), ...] -> one Session. mount_deg rotates the sensor
    frame (the evaluator must then use meta['upright'], not +Z)."""
    rng = np.random.default_rng(seed)
    accs, btns, labels, t = [], [], [], 0.0
    for label, kw in plan:
        a, b = GENERATORS[label](rng, **kw)
        accs.append(a)
        btns.append(np.zeros(len(a), bool) if b is None else b)
        labels.append(dict(t_start=t, t_end=t + len(a) / HZ, label=label))
        t += len(a) / HZ
    acc = np.concatenate(accs)
    upright = Z.copy()
    if mount_deg:
        th = np.radians(mount_deg)
        upright = np.array([np.sin(th) * 0.6, np.sin(th) * 0.8, np.cos(th)])
        acc = acc @ _rotation_to(upright).T
    return Session(HZ, acc, np.concatenate(btns), labels,
                   dict(source="synthetic", person=person, seed=seed, upright=upright.tolist()))


def make_dataset(seed: int = 0, scale: float = 1.0) -> list[Session]:
    """Two sessions: normal use (all non-positive labels) and simulated falls. scale<1 shrinks counts."""
    k = lambda n: max(int(round(n * scale)), 1)
    normal = [("walk", dict(secs=120.0)), ("walk", dict(secs=120.0, slow=True)), ("idle", dict(secs=60.0)),
              ("sit", dict(secs=60.0)), ("lean", dict(secs=60.0)), ("car", dict(secs=150.0))]
    normal += [("floor_tap", {})] * k(4) + [("drop_hand", {})] * k(10) + [("knock_over", {})] * k(6)
    normal += [("other", {})] * k(2) + [("walk", dict(secs=60.0))]
    falls = []
    for i in range(k(6)):
        falls.append(("fall_sim", dict(soft=(i % 3 == 2), press_at_s=(25.0 if i % 2 else None))))
        falls.append(("idle", dict(secs=5.0)))
    return [build_session(normal, seed, person="synth-a"), build_session(falls, seed + 1, person="synth-b")]


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data/synth")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--csv", action="store_true", help="write CSV+JSON instead of NPZ")
    a = ap.parse_args(argv)
    for i, s in enumerate(make_dataset(a.seed, a.scale)):
        p = os.path.join(a.out, f"synth_{a.seed}_{i}." + ("csv" if a.csv else "npz"))
        save(s, p)
        print(f"wrote {p}: {s.duration_s:.0f} s, {len(s.labels)} segments")


if __name__ == "__main__":
    main()
