"""Replay labelled sessions through FallFSM + minute_features and report how the thresholds behave.

    python -m tools.evaluate data/*.npz                  # per-label report + one-at-a-time sweep
    python -m tools.evaluate --synth --sweep full --jobs 4 --json out.json
    python -m tools.evaluate data/*.npz --sweep none

Definitions (all counted per labelled segment; an *episode* starts when the FSM leaves MONITORING for
IMPACT and is attributed to the label active at that moment):
  impact_only  episode that returned to MONITORING without beeping
  pre_alert    FSM reached PRE_ALERT (buzzer beeps, user can still cancel)  -> counted as "alert"
  escalated    FSM reached ALERT (event sent to the phone)
Sensitivity = fall_sim segments with a pre_alert / fall_sim segments.
False alarms per hour = pre_alerts (resp. escalations) in normal-use labels / hours of those labels.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass, replace
from multiprocessing import Pool
from typing import Iterable, Optional

import numpy as np

from cane.canesense.features import minute_features
from cane.canesense.fsm import Config, FallFSM, State
from tools.session import EVAL_RATE_HZ, LABELS, NORMAL_LABELS, Session, load

DROP_LABELS = ("drop_hand", "knock_over")
SWEEP_OAT = {"t_impact_g": [1.5, 2.0, 2.5, 3.0, 4.0, 5.0], "tilt_trigger_deg": [40, 50, 60, 70, 80],
             "still_required_s": [3, 5, 10, 15, 20], "pre_alert_s": [10, 20, 30, 45]}
SWEEP_FULL = {"t_impact_g": [2.0, 3.0, 4.0], "tilt_trigger_deg": [45, 60, 75],
              "still_required_s": [5, 10, 15], "pre_alert_s": [15, 30, 45]}
OUTCOME_RANK = {"none": 0, "impact_only": 1, "pre_alert": 2, "escalated": 3}


@dataclass
class Episode:
    t_trigger: float
    label: str
    seg: int                      # index into the session's label list, -1 if unlabelled
    peak_g: float = 0.0
    pre_alert_t: Optional[float] = None
    escalated_t: Optional[float] = None
    cancelled: bool = False
    end_t: Optional[float] = None

    @property
    def outcome(self) -> str:
        if self.escalated_t is not None:
            return "escalated"
        if self.pre_alert_t is not None:
            return "pre_alert"
        return "impact_only"


def _label_index(s: Session) -> np.ndarray:
    idx = np.full(s.n, -1, dtype=int)
    for k, l in enumerate(s.labels):
        idx[s.segment_slice(l)] = k
    return idx


def replay(s: Session, cfg: Optional[Config] = None) -> tuple[list[Episode], int]:
    """Run the FSM over a (50 Hz) session. Returns (episodes, help_request_count)."""
    s = s.resampled(EVAL_RATE_HZ)
    fsm = FallFSM(s.upright(), cfg or Config())
    lab = _label_index(s)
    names = [l["label"] for l in s.labels]
    eps: list[Episode] = []
    cur: Optional[Episode] = None
    helps = 0
    prev = fsm.state
    dt = 1.0 / s.sample_rate_hz
    for i in range(s.n):
        t = i * dt
        ev = fsm.update(t, s.acc[i], bool(s.button[i]))
        st = fsm.state
        if cur is None and prev is State.MONITORING and st is not State.MONITORING:
            k = int(lab[i])
            cur = Episode(t, names[k] if k >= 0 else "unlabelled", k)
            eps.append(cur)
        if cur is not None:
            cur.peak_g = max(cur.peak_g, float(np.linalg.norm(s.acc[i])))
            if st is State.PRE_ALERT and cur.pre_alert_t is None:
                cur.pre_alert_t = t
            if st is State.ALERT and cur.escalated_t is None:
                cur.escalated_t = t
        if ev is not None:
            if ev.kind == "help_request":
                helps += 1
            elif cur is not None and ev.outcome == "cancelled_by_user":
                cur.cancelled = True
        if cur is not None and st is State.MONITORING:
            cur.end_t = t
            cur = None
        prev = st
    return eps, helps


def segment_outcomes(s: Session, eps: list[Episode]) -> list[str]:
    """Worst outcome per label segment (episodes are attributed to the segment active at trigger)."""
    out = ["none"] * len(s.labels)
    for e in eps:
        if e.seg >= 0 and OUTCOME_RANK[e.outcome] > OUTCOME_RANK[out[e.seg]]:
            out[e.seg] = e.outcome
    return out


def label_features(s: Session) -> dict[str, dict]:
    """minute_features over <=60 s chunks of every segment, per-minute scaled, averaged per label."""
    s = s.resampled(EVAL_RATE_HZ)
    up = s.upright()
    acc: dict[str, list[dict]] = {}
    for l in s.labels:
        seg = s.acc[s.segment_slice(l)]
        for a in range(0, len(seg), 60 * EVAL_RATE_HZ):
            ch = seg[a: a + 60 * EVAL_RATE_HZ]
            if len(ch) < 10 * EVAL_RATE_HZ:
                continue
            f = minute_features(ch, up)
            k = 60.0 * EVAL_RATE_HZ / len(ch)
            acc.setdefault(l["label"], []).append(dict(
                strikes_per_min=f["strike_count"] * k, active_s_per_min=f["active_s"] * k,
                upright_s_per_min=f["upright_s"] * k, flat_s_per_min=f["flat_s"] * k,
                mag_max=f["max_impact_g"], dyn_mean=f["dyn_mean"]))
    return {k: {m: round(float(np.mean([r[m] for r in rows])), 3) for m in rows[0]} | {"chunks": len(rows)}
            for k, rows in acc.items()}


def evaluate(sessions: list[Session], cfg: Optional[Config] = None, with_features: bool = True) -> dict:
    cfg = cfg or Config()
    per: dict[str, dict] = {l: dict(segments=0, duration_s=0.0, episodes=0, impact_only=0, pre_alerts=0,
                                    escalations=0, cancelled=0, segments_with_pre_alert=0,
                                    segments_with_escalation=0) for l in LABELS}
    times_to_pre: list[float] = []
    missed_falls: list[dict] = []
    helps = 0
    feats: dict[str, list[dict]] = {}
    fs_total = fs_det = fs_esc = 0
    for si, s in enumerate(sessions):
        s = s.resampled(EVAL_RATE_HZ)
        eps, h = replay(s, cfg)
        helps += h
        outs = segment_outcomes(s, eps)
        for k, l in enumerate(s.labels):
            p = per[l["label"]]
            p["segments"] += 1
            p["duration_s"] += l["t_end"] - l["t_start"]
            p["segments_with_pre_alert"] += outs[k] in ("pre_alert", "escalated")
            p["segments_with_escalation"] += outs[k] == "escalated"
            if l["label"] == "fall_sim":
                fs_total += 1
                fs_det += outs[k] in ("pre_alert", "escalated")
                fs_esc += outs[k] == "escalated"
                if outs[k] == "none" or outs[k] == "impact_only":
                    missed_falls.append(dict(session=si, t_start=l["t_start"], outcome=outs[k]))
        for e in eps:
            if e.label in per:
                p = per[e.label]
                p["episodes"] += 1
                p["impact_only"] += e.outcome == "impact_only"
                p["pre_alerts"] += e.pre_alert_t is not None
                p["escalations"] += e.escalated_t is not None
                p["cancelled"] += e.cancelled
                if e.label == "fall_sim" and e.pre_alert_t is not None:
                    times_to_pre.append(e.pre_alert_t - e.t_trigger)
        if with_features:
            for lab, f in label_features(s).items():
                feats.setdefault(lab, []).append(f)
    for lab, fl in feats.items():
        keys = [k for k in fl[0] if k != "chunks"]
        w = np.array([f["chunks"] for f in fl], float)
        per[lab]["features_per_minute"] = {k: round(float(np.average([f[k] for f in fl], weights=w)), 3) for k in keys}
    for p in per.values():
        p["duration_s"] = round(p["duration_s"], 1)
    hours = sum(per[l]["duration_s"] for l in NORMAL_LABELS) / 3600.0
    n_pre = sum(per[l]["pre_alerts"] for l in NORMAL_LABELS)
    n_esc = sum(per[l]["escalations"] for l in NORMAL_LABELS)
    drop_alert = sum(per[l]["segments_with_pre_alert"] for l in DROP_LABELS)
    drop_total = sum(per[l]["segments"] for l in DROP_LABELS)
    return dict(
        config=asdict(cfg), n_sessions=len(sessions),
        total_hours=round(sum(p["duration_s"] for p in per.values()) / 3600.0, 4),
        per_label=per,
        fall_sim=dict(segments=fs_total, detected=fs_det, escalated=fs_esc,
                      sensitivity=(fs_det / fs_total) if fs_total else None,
                      median_s_trigger_to_pre_alert=round(float(np.median(times_to_pre)), 1) if times_to_pre else None,
                      missed=missed_falls),
        false_alarms=dict(
            normal_hours=round(hours, 4), pre_alerts=int(n_pre), escalations=int(n_esc),
            pre_alerts_per_hour=(n_pre / hours) if hours else None,
            escalations_per_hour=(n_esc / hours) if hours else None,
            labels_with_pre_alert={l: per[l]["pre_alerts"] for l in NORMAL_LABELS if per[l]["pre_alerts"]},
            labels_with_escalation={l: per[l]["escalations"] for l in NORMAL_LABELS if per[l]["escalations"]}),
        confusion_drop_vs_fall={
            "drop (drop_hand+knock_over)": dict(alert=int(drop_alert), no_alert=int(drop_total - drop_alert)),
            "fall (fall_sim)": dict(alert=int(fs_det), no_alert=int(fs_total - fs_det))},
        help_requests=helps,
    )


# ------------------------------------------------------------------ sweep
def _sweep_job(args):
    sessions, overrides = args
    r = evaluate(sessions, replace(Config(), **overrides), with_features=False)
    return dict(overrides, sensitivity=r["fall_sim"]["sensitivity"], detected=r["fall_sim"]["detected"],
                fall_segments=r["fall_sim"]["segments"], pre_alerts_per_hour=r["false_alarms"]["pre_alerts_per_hour"],
                escalations_per_hour=r["false_alarms"]["escalations_per_hour"],
                drop_alert_rate=_drop_rate(r))


def _drop_rate(r: dict) -> Optional[float]:
    c = r["confusion_drop_vs_fall"]["drop (drop_hand+knock_over)"]
    n = c["alert"] + c["no_alert"]
    return c["alert"] / n if n else None


def sweep(sessions: list[Session], mode: str = "oat", jobs: int = 1) -> list[dict]:
    sessions = [s.resampled(EVAL_RATE_HZ) for s in sessions]
    if mode == "oat":
        base = asdict(Config())
        combos = [{}] + [{k: v} for k, vals in SWEEP_OAT.items() for v in vals if v != base[k]]
    elif mode == "full":
        keys = list(SWEEP_FULL)
        combos = [dict(zip(keys, vals)) for vals in itertools.product(*SWEEP_FULL.values())]
    else:
        return []
    work = [(sessions, c) for c in combos]
    if jobs > 1:
        with Pool(jobs) as p:
            rows = p.map(_sweep_job, work)
    else:
        rows = [_sweep_job(w) for w in work]
    for r, c in zip(rows, combos):
        r["varied"] = sorted(c) if c else ["(defaults)"]
    return rows


def format_sweep(rows: list[dict]) -> str:
    cols = ["t_impact_g", "tilt_trigger_deg", "still_required_s", "pre_alert_s"]
    base = asdict(Config())
    head = f"{'t_impact_g':>10} {'tilt_deg':>8} {'still_s':>7} {'pre_s':>6} | {'sens':>5} {'det/n':>6} " \
           f"{'FApre/h':>8} {'FAesc/h':>8} {'dropAlert':>9}"
    out = [head, "-" * len(head)]
    f = lambda v, p=2: "  n/a" if v is None else f"{v:.{p}f}"
    for r in rows:
        vals = [r.get(c, base[c]) for c in cols]
        mark = " <- defaults" if r["varied"] == ["(defaults)"] else ""
        out.append(f"{vals[0]:>10g} {vals[1]:>8g} {vals[2]:>7g} {vals[3]:>6g} | {f(r['sensitivity']):>5} "
                   f"{r['detected']}/{r['fall_segments']:<4} {f(r['pre_alerts_per_hour']):>8} "
                   f"{f(r['escalations_per_hour']):>8} {f(r['drop_alert_rate']):>9}{mark}")
    return "\n".join(out)


def rank(rows: list[dict], top: int = 3) -> list[dict]:
    """Highest sensitivity first, then fewest false pre-alerts/hour, then fewest false escalations/hour."""
    key = lambda r: (-(r["sensitivity"] or 0), r["pre_alerts_per_hour"] or 0, r["escalations_per_hour"] or 0)
    return sorted(rows, key=key)[:top]


def format_report(r: dict) -> str:
    L = []
    L.append(f"sessions={r['n_sessions']}  recorded={r['total_hours'] * 60:.1f} min  config={r['config']}")
    L.append("\nPER LABEL")
    L.append(f"{'label':<11}{'segs':>5}{'sec':>8}{'episodes':>9}{'impact':>7}{'pre':>5}{'esc':>5}{'cancel':>7}"
             f"  strikes/min  active_s  upright_s  flat_s")
    for lab in LABELS:
        p = r["per_label"][lab]
        if not p["segments"]:
            continue
        f = p.get("features_per_minute", {})
        L.append(f"{lab:<11}{p['segments']:>5}{p['duration_s']:>8.0f}{p['episodes']:>9}{p['impact_only']:>7}"
                 f"{p['pre_alerts']:>5}{p['escalations']:>5}{p['cancelled']:>7}"
                 f"  {f.get('strikes_per_min', float('nan')):>11.1f}  {f.get('active_s_per_min', float('nan')):>8.1f}"
                 f"  {f.get('upright_s_per_min', float('nan')):>9.1f}  {f.get('flat_s_per_min', float('nan')):>6.1f}")
    fs = r["fall_sim"]
    L.append("\nSENSITIVITY (fall_sim)")
    if fs["segments"]:
        L.append(f"  detected (pre-alert) {fs['detected']}/{fs['segments']} = {fs['sensitivity']:.2f}; "
                 f"escalated unattended {fs['escalated']}; median trigger->pre-alert {fs['median_s_trigger_to_pre_alert']} s")
        for m in fs["missed"]:
            L.append(f"  MISSED: session {m['session']} segment at {m['t_start']:.1f}s ({m['outcome']})")
    else:
        L.append("  no fall_sim segments")
    fa = r["false_alarms"]
    L.append("\nFALSE ALARMS (normal use: " + ", ".join(NORMAL_LABELS) + ")")
    if fa["normal_hours"]:
        L.append(f"  {fa['normal_hours'] * 60:.1f} min of normal use: {fa['pre_alerts']} pre-alerts "
                 f"({fa['pre_alerts_per_hour']:.2f}/h), {fa['escalations']} escalations ({fa['escalations_per_hour']:.2f}/h)")
        L.append(f"  labels that produced pre-alerts: {fa['labels_with_pre_alert'] or 'none'}")
        L.append(f"  labels that produced escalations: {fa['labels_with_escalation'] or 'none'}")
        if fa["normal_hours"] < 1.0:
            L.append("  (under 1 h of normal use: per-hour rates are extrapolated, treat as indicative only)")
    c = r["confusion_drop_vs_fall"]
    L.append("\nCONFUSION drop vs fall (segment level)      alert  no_alert")
    for k, v in c.items():
        L.append(f"  {k:<40}{v['alert']:>6}{v['no_alert']:>10}")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help=".npz / .csv sessions")
    ap.add_argument("--synth", action="store_true", help="evaluate the built-in synthetic dataset")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sweep", choices=["oat", "full", "none"], default="oat")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--json", help="write machine-readable results here ('-' for stdout)")
    a = ap.parse_args(argv)
    sessions: list[Session] = [load(f) for f in a.files]
    if a.synth:
        from tools.synth_sessions import make_dataset
        sessions += make_dataset(a.seed)
    if not sessions:
        ap.error("give session files or --synth")
    result = evaluate(sessions)
    rows = sweep(sessions, a.sweep, a.jobs)
    result["sweep"] = dict(mode=a.sweep, rows=rows, top=rank(rows) if rows else [])
    if a.json == "-":
        json.dump(result, sys.stdout, indent=2, default=float)
        return 0
    print(format_report(result))
    if rows:
        print(f"\nTHRESHOLD SWEEP ({a.sweep}; sens = fall_sim with pre-alert, FA = false alarms per hour of normal use)")
        print(format_sweep(rows))
        print("\nSuggested starting points (sensitivity, then fewest false pre-alerts):")
        print(format_sweep(result["sweep"]["top"]))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(result, f, indent=2, default=float)
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
