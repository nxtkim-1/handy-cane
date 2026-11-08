# Labelled session format

One session = one continuous recording of the cane accelerometer with time-interval labels.
Implemented in `tools/session.py` (`Session`, `save`, `load`).

## Fields

| Field | Type | Meaning |
|---|---|---|
| `sample_rate_hz` | float | Rate of the stored samples. The evaluator resamples to 50 Hz (what `fsm.py`/`features.py` assume), so 100 Hz firmware data is fine. |
| `acc` | (N,3) float, g | Raw acceleration including gravity, sensor axes as mounted. |
| `button` | (N,) bool | True while the cane button is held. All False if not logged (firmware `record.py` does not log it). |
| `labels` | list of `{t_start, t_end, label}` | Seconds from session start, `t_start < t_end`, non-overlapping. Samples outside any label are "unlabelled": still replayed, events there are reported as `unlabelled`. |
| `meta` | object | Free-form: `person`, `notes`, `source`, and optionally `upright: [x,y,z]` = gravity direction with the cane held vertical (the 3 s calibration of MASTER 6.3). If absent, the evaluator estimates it from the first idle (else walk) segment. |

## Labels

`walk, idle, sit, lean, drop_hand, knock_over, floor_tap, fall_sim, car, other`

| Label | What the segment contains | Expected FSM result |
|---|---|---|
| walk | walking with the cane, incl. slow/shuffling | nothing |
| idle | standing, cane held upright | nothing |
| sit | seated, cane held / between knees / hooked | nothing |
| lean | cane leaned on a wall or table (set down and picked up) | nothing |
| drop_hand | cane slips from the hand; include the drop and the pick-up | no alert if picked up in a few seconds |
| knock_over | leaning cane topples; include pick-up | no alert if picked up in a few seconds |
| floor_tap | hard taps of the tip on the floor | impact only |
| fall_sim | simulated fall on a mat holding the cane, then lying still; include getting up | pre-alert (the positive class) |
| car | cane carried flat in a car for a while | nothing |
| other | anything else (carrying, stairs, stumble) | not scored as normal use |

Include the **whole event** in its segment: start a few seconds before the drop/fall and end after the cane
is upright again. The evaluator attributes an alarm to the label active when the FSM left MONITORING.
After an unattended fall that escalated, the volunteer must long-press the button (3 s) to silence the
FSM, otherwise it stays in ALERT and misses everything after it.

## Files

- `name.npz` (preferred): arrays `acc` (float32), `button`, `sample_rate_hz`, plus JSON strings `labels_json`, `meta_json`.
- `name.csv` + `name.json`: CSV header `t,ax,ay,az,button` (t in seconds from start, button 0/1) and a sidecar
  `{"sample_rate_hz": 50, "labels": [...], "meta": {...}}` with the same stem.

## Importing firmware `pi/record.py` output

`record.py <label>` writes `data/raw/<label>_<HHMMSS>.csv` with header `t,ax,ay,az` (t = epoch seconds,
g, about 100 Hz, no button). Firmware labels map to ours: walking->walk, still->idle, hanging->lean,
dropped->drop_hand, fall->fall_sim, stumble/stairs->other. Anything else becomes `other`.

```
python -m tools.session import-firmware data/raw/walking_*.csv data/raw/dropped_*.csv --out data/fw.npz --person p1
python -m tools.session info data/fw.npz
```

Each file becomes one labelled segment, concatenated in the order given and resampled to 50 Hz (linear
interpolation). Gaps over 0.5 s inside a file are listed in `meta.gaps_s`. Files recorded with the
button/SOS events are not merged (record.py does not save them).
