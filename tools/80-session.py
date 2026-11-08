"""Labelled-session container, file I/O (NPZ or CSV+JSON sidecar) and the firmware record.py importer.

Format spec: tools/session_format.md. CLI:
    python -m tools.session info  data/s1.npz
    python -m tools.session import-firmware data/raw/walking_*.csv fall_*.csv --out data/fw.npz
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

LABELS = ("walk", "idle", "sit", "lean", "drop_hand", "knock_over", "floor_tap", "fall_sim", "car", "other")
NORMAL_LABELS = ("walk", "idle", "sit", "lean", "car", "floor_tap", "knock_over", "drop_hand")  # false-alarm hours
EVAL_RATE_HZ = 50  # features.py / fsm.py assume this (cane.common.schema.SAMPLE_RATE_HZ)

# firmware pi/record.py labels -> ours. Unmapped firmware labels (stumble, stairs) become "other".
FIRMWARE_LABEL_MAP = {
    "walking": "walk", "walk": "walk", "still": "idle", "hanging": "lean", "dropped": "drop_hand",
    "fall": "fall_sim", "stumble": "other", "stairs": "other",
}


class SessionError(ValueError):
    pass


@dataclass
class Session:
    sample_rate_hz: float
    acc: np.ndarray                      # (N,3) g
    button: np.ndarray                   # (N,) bool
    labels: list[dict] = field(default_factory=list)   # {"t_start","t_end","label"} seconds
    meta: dict = field(default_factory=dict)           # person, notes, source, upright=[x,y,z], ...

    def __post_init__(self) -> None:
        self.acc = np.asarray(self.acc, dtype=float).reshape(-1, 3)
        self.button = np.asarray(self.button, dtype=bool).reshape(-1)
        self.labels = [dict(t_start=float(l["t_start"]), t_end=float(l["t_end"]), label=str(l["label"]))
                       for l in self.labels]

    @property
    def n(self) -> int:
        return len(self.acc)

    @property
    def duration_s(self) -> float:
        return self.n / self.sample_rate_hz

    def validate(self) -> "Session":
        if self.sample_rate_hz <= 0:
            raise SessionError("sample_rate_hz must be > 0")
        if len(self.button) != len(self.acc):
            raise SessionError("button and acc length differ")
        if not np.all(np.isfinite(self.acc)):
            raise SessionError("acc contains NaN/inf")
        for l in self.labels:
            if l["label"] not in LABELS:
                raise SessionError(f"unknown label {l['label']!r}; allowed: {LABELS}")
            if not (0 <= l["t_start"] < l["t_end"] <= self.duration_s + 1e-6):
                raise SessionError(f"bad label interval {l}")
        ordered = sorted(self.labels, key=lambda l: l["t_start"])
        for a, b in zip(ordered, ordered[1:]):
            if b["t_start"] < a["t_end"] - 1e-9:
                raise SessionError(f"overlapping labels {a} / {b}")
        return self

    def segment_slice(self, label: dict) -> slice:
        r = self.sample_rate_hz
        return slice(int(round(label["t_start"] * r)), min(int(round(label["t_end"] * r)), self.n))

    def upright(self) -> np.ndarray:
        """Calibrated upright gravity vector: meta['upright'] if present, else estimated from the first
        idle/walk segment (mean direction), else from the first 3 s."""
        u = self.meta.get("upright")
        if u is not None:
            return np.asarray(u, float) / np.linalg.norm(u)
        for want in ("idle", "walk"):
            for l in sorted(self.labels, key=lambda l: l["t_start"]):
                if l["label"] == want:
                    sl = self.segment_slice(l)
                    seg = self.acc[sl][: int(10 * self.sample_rate_hz)]
                    if len(seg):
                        return _unit(seg.mean(axis=0))
        return _unit(self.acc[: int(3 * self.sample_rate_hz)].mean(axis=0))

    def resampled(self, rate_hz: float = EVAL_RATE_HZ) -> "Session":
        """Linear-interpolation resample to rate_hz (button: nearest). Returns self if already there."""
        if abs(self.sample_rate_hz - rate_hz) < 1e-9 or self.n < 2:
            return self
        t = np.arange(self.n) / self.sample_rate_hz
        m = int(np.floor(t[-1] * rate_hz)) + 1
        tn = np.arange(m) / rate_hz
        acc = np.stack([np.interp(tn, t, self.acc[:, k]) for k in range(3)], axis=1)
        btn = self.button[np.minimum(np.round(tn * self.sample_rate_hz).astype(int), self.n - 1)]
        meta = dict(self.meta)
        meta.setdefault("upright", self.upright().tolist())
        return Session(rate_hz, acc, btn, self.labels, meta)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n == 0:
        raise SessionError("cannot derive an upright vector from zero acceleration")
    return v / n


# ---------------------------------------------------------------- file I/O
def save(s: Session, path: str) -> str:
    """.npz -> one file. .csv -> CSV (t,ax,ay,az,button) plus <stem>.json sidecar."""
    s.validate()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if path.lower().endswith(".npz"):
        np.savez_compressed(path, acc=s.acc.astype(np.float32), button=s.button.astype(bool),
                            sample_rate_hz=np.float64(s.sample_rate_hz),
                            labels_json=np.array(json.dumps(s.labels)), meta_json=np.array(json.dumps(s.meta)))
    elif path.lower().endswith(".csv"):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "ax", "ay", "az", "button"])
            for i in range(s.n):
                w.writerow([f"{i / s.sample_rate_hz:.4f}", f"{s.acc[i, 0]:.5f}", f"{s.acc[i, 1]:.5f}",
                            f"{s.acc[i, 2]:.5f}", int(s.button[i])])
        with open(os.path.splitext(path)[0] + ".json", "w") as f:
            json.dump(dict(sample_rate_hz=s.sample_rate_hz, labels=s.labels, meta=s.meta), f, indent=2)
    else:
        raise SessionError("path must end in .npz or .csv")
    return path


def load(path: str) -> Session:
    if path.lower().endswith(".npz"):
        with np.load(path, allow_pickle=False) as z:
            return Session(float(z["sample_rate_hz"]), z["acc"].astype(float), z["button"],
                           json.loads(str(z["labels_json"])), json.loads(str(z["meta_json"]))).validate()
    if path.lower().endswith(".csv"):
        side = os.path.splitext(path)[0] + ".json"
        with open(side) as f:
            sc = json.load(f)
        rows = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
        return Session(float(sc["sample_rate_hz"]), rows[:, 1:4], rows[:, 4] > 0.5,
                       sc.get("labels", []), sc.get("meta", {})).validate()
    raise SessionError("path must end in .npz or .csv")


# ---------------------------------------------------------------- firmware pi/record.py importer
def _label_from_filename(path: str) -> str:
    m = re.match(r"([A-Za-z_]+?)_\d{6}", os.path.basename(path))
    return m.group(1) if m else os.path.splitext(os.path.basename(path))[0]


def read_firmware_csv(path: str) -> tuple[np.ndarray, np.ndarray]:
    """pi/record.py output: header t,ax,ay,az; t = epoch seconds, a in g, ~100 Hz. Returns (t, acc)."""
    rows = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    if rows.shape[1] != 4:
        raise SessionError(f"{path}: expected 4 columns t,ax,ay,az")
    t = rows[:, 0]
    order = np.argsort(t, kind="stable")  # queue overflow handling can drop samples; never reorder
    return t[order], rows[order, 1:4]


def import_firmware(paths: Iterable[str], labels: Optional[Iterable[str]] = None,
                    target_hz: float = EVAL_RATE_HZ, person: str = "", notes: str = "") -> Session:
    """Concatenate one or more record.py CSVs into ONE session, one label segment per file.

    labels: our label per file (default: derived from the file name via FIRMWARE_LABEL_MAP; names already
    in LABELS pass through). Gaps inside a file longer than 0.5 s are kept as time (the resample bridges
    them linearly) but are reported in meta['gaps_s'] so you can discard the file if it matters.
    record.py does not log the button, so button is all False.
    """
    paths = list(paths)
    names = list(labels) if labels is not None else [_label_from_filename(p) for p in paths]
    if len(names) != len(paths):
        raise SessionError("labels and paths differ in length")
    accs, segs, gaps, t_cursor = [], [], [], 0.0
    src_rates = []
    for p, name in zip(paths, names):
        lab = FIRMWARE_LABEL_MAP.get(name, name)
        if lab not in LABELS:
            lab = "other"
        t, a = read_firmware_csv(p)
        if len(t) < 2:
            raise SessionError(f"{p}: fewer than 2 samples")
        dt = np.diff(t)
        rate = 1.0 / float(np.median(dt))
        src_rates.append(round(rate, 1))
        gaps += [round(float(g), 2) for g in dt[dt > 0.5]]
        grid = np.arange(0.0, t[-1] - t[0], 1.0 / target_hz)
        r = np.stack([np.interp(grid + t[0], t, a[:, k]) for k in range(3)], axis=1)
        accs.append(r)
        segs.append(dict(t_start=t_cursor, t_end=t_cursor + len(r) / target_hz, label=lab))
        t_cursor += len(r) / target_hz
    acc = np.concatenate(accs)
    meta = dict(source="firmware record.py", person=person, notes=notes, source_rates_hz=src_rates,
                files=[os.path.basename(p) for p in paths], gaps_s=gaps)
    return Session(target_hz, acc, np.zeros(len(acc), bool), segs, meta).validate()


# ---------------------------------------------------------------- CLI
def _info(s: Session) -> str:
    out = [f"{s.n} samples @ {s.sample_rate_hz:g} Hz = {s.duration_s:.1f} s, meta={s.meta}"]
    for l in sorted(s.labels, key=lambda l: l["t_start"]):
        out.append(f"  {l['t_start']:8.2f} - {l['t_end']:8.2f}  {l['label']}")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="tools.session")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("info"); pi.add_argument("path")
    pf = sub.add_parser("import-firmware", help="convert pi/record.py CSVs")
    pf.add_argument("files", nargs="+"); pf.add_argument("--out", required=True)
    pf.add_argument("--labels", help="comma list, one per file (overrides file-name labels)")
    pf.add_argument("--person", default=""); pf.add_argument("--notes", default="")
    a = ap.parse_args(argv)
    if a.cmd == "info":
        print(_info(load(a.path)))
    else:
        s = import_firmware(a.files, a.labels.split(",") if a.labels else None, person=a.person, notes=a.notes)
        save(s, a.out)
        print(f"wrote {a.out}\n{_info(s)}")


if __name__ == "__main__":
    main()
