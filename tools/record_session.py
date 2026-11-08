"""Record a labelled session (docs/DATA_COLLECTION.md).

Hardware stays behind the tiny `SampleSource` interface, so the recorder is testable without a cane:
  sim     synthetic generators from tools/synth_sessions.py streamed through the same code path
  stream  text lines "ax,ay,az[,button]" in g from a file, stdin or any serial-like object with readline()
          (e.g. the Arduino/serial output, or a Pi script printing samples). Blank/header lines are skipped.
  i2c     STUB: direct ADXL345/LIS3DH reader, see I2CSource. Not implemented (needs hardware).

    python -m tools.record_session --source sim --plan walk:30,idle:10,drop_hand:0,fall_sim:0 --out data/s1.npz
    python -m tools.record_session --source stream --input samples.csv --rate 50 \\
           --plan walk:120,idle:60 --person p1 --out data/s2.npz
Plan items are LABEL:SECONDS. For sim, event labels (drop_hand, knock_over, fall_sim) have their own
duration and SECONDS is ignored.
"""
from __future__ import annotations

import argparse
import inspect
import sys
from typing import Callable, Iterable, Optional, Protocol

import numpy as np

from tools.session import LABELS, Session, save


class SampleSource(Protocol):
    def read(self) -> Optional[tuple[np.ndarray, bool]]:
        """Next sample as ((3,) acceleration in g, button_pressed), or None when the stream ended.
        Blocking is fine: a live source paces the recording at its own sample rate."""


class SimSource:
    """Streams an already-built synthetic Session sample by sample."""

    def __init__(self, session: Session):
        self.s, self.i = session, 0

    def read(self):
        if self.i >= self.s.n:
            return None
        a, b = self.s.acc[self.i], bool(self.s.button[self.i])
        self.i += 1
        return a, b


class StreamSource:
    """Parses 'ax,ay,az[,button]' lines from any iterable of str/bytes or object with readline()."""

    def __init__(self, stream):
        self.lines = iter(stream.readline, "") if hasattr(stream, "readline") else iter(stream)
        self.bad = 0

    def read(self):
        for line in self.lines:
            if isinstance(line, bytes):
                line = line.decode("ascii", "ignore")
            parts = line.strip().split(",")
            try:
                if len(parts) not in (3, 4):
                    raise ValueError
                acc = np.array([float(p) for p in parts[:3]])
                btn = bool(int(float(parts[3]))) if len(parts) == 4 else False
            except ValueError:
                self.bad += 1  # header / partial serial line
                continue
            return acc, btn
        return None


class I2CSource:
    """STUB for a direct accelerometer reader on the Pi (needs hardware; not exercised by tests).

    To implement: open smbus2 bus 1, detect ADXL345 (0x53, WHO_AM_I 0xE5, DATA_FORMAT=0x0B full-res +-16 g,
    BW_RATE for the wanted rate, POWER_CTL measure) or LIS3DH (0x19, WHO_AM_I 0x33), read 6 bytes from the data
    registers, scale to g (ADXL345 full-res 3.9 mg/LSB), read the GPIO button, and sleep to hold the rate.
    pi/hardware.py on origin/firmware-canelink already does all of this; the simplest path is to run the
    firmware's reader, print 'ax,ay,az,button' lines, and pipe them into `--source stream --input -`.
    """

    def __init__(self, *a, **k):
        raise NotImplementedError("I2CSource is a documented stub; pipe samples via --source stream instead")

    def read(self):  # pragma: no cover
        raise NotImplementedError


def parse_plan(text: str) -> list[tuple[str, float]]:
    plan = []
    for item in text.split(","):
        if not item.strip():
            continue
        label, _, secs = item.strip().partition(":")
        if label not in LABELS:
            raise ValueError(f"unknown label {label!r}; allowed: {', '.join(LABELS)}")
        plan.append((label, float(secs) if secs else 0.0))
    if not plan:
        raise ValueError("empty plan")
    return plan


def record(source: SampleSource, plan: list[tuple[str, float]], rate_hz: float,
           person: str = "", notes: str = "", on_segment: Optional[Callable[[str, float], None]] = None,
           meta: Optional[dict] = None) -> Session:
    """Read len(plan) segments from `source`. Each segment is secs*rate_hz samples (shorter if the stream
    ends; a segment with no samples is dropped). Returns a validated Session."""
    acc, btn, labels, n_done = [], [], [], 0
    for label, secs in plan:
        if on_segment:
            on_segment(label, secs)
        want = int(round(secs * rate_hz))
        got = 0
        while got < want:
            r = source.read()
            if r is None:
                break
            acc.append(r[0]); btn.append(r[1]); got += 1
        if got:
            labels.append(dict(t_start=n_done / rate_hz, t_end=(n_done + got) / rate_hz, label=label))
            n_done += got
        if got < want:
            break  # stream ended
    if not acc:
        raise RuntimeError("no samples read")
    m = dict(person=person, notes=notes, source=type(source).__name__)
    m.update(meta or {})
    return Session(rate_hz, np.array(acc), np.array(btn, bool), labels, m).validate()


def sim_session(plan: list[tuple[str, float]], seed: int = 0) -> Session:
    from tools.synth_sessions import GENERATORS, build_session
    items = []
    for label, secs in plan:
        kw = {"secs": secs} if secs > 0 and "secs" in inspect.signature(GENERATORS[label]).parameters else {}
        items.append((label, kw))
    return build_session(items, seed=seed)


def record_sim(plan: list[tuple[str, float]], seed: int = 0, person: str = "sim") -> Session:
    s = sim_session(plan, seed)
    durations = [(l["label"], l["t_end"] - l["t_start"]) for l in s.labels]
    return record(SimSource(s), durations, s.sample_rate_hz, person=person,
                  meta=dict(seed=seed, upright=s.meta["upright"]))


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", choices=["sim", "stream", "i2c"], required=True)
    ap.add_argument("--plan", required=True, help="LABEL:SECONDS,... e.g. walk:120,idle:60")
    ap.add_argument("--out", required=True, help=".npz or .csv")
    ap.add_argument("--input", default="-", help="stream source: file path or - for stdin")
    ap.add_argument("--rate", type=float, default=50.0, help="stream source sample rate in Hz")
    ap.add_argument("--person", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--prompt", action="store_true", help="wait for Enter before each segment (not with stdin input)")
    a = ap.parse_args(argv)
    plan = parse_plan(a.plan)
    if a.source == "sim":
        s = record_sim(plan, a.seed, a.person or "sim")
    elif a.source == "i2c":
        I2CSource()
        return
    else:
        f = sys.stdin if a.input == "-" else open(a.input)
        def announce(label, secs):
            print(f"-> {label} for {secs:g} s", file=sys.stderr)
            if a.prompt and a.input != "-":
                input("   press Enter to start this segment ")
        s = record(StreamSource(f), plan, a.rate, a.person, a.notes, announce)
    save(s, a.out)
    print(f"wrote {a.out}: {s.duration_s:.1f} s, segments: " + ", ".join(
        f"{l['label']}({l['t_end'] - l['t_start']:.0f}s)" for l in s.labels))


if __name__ == "__main__":
    main()
