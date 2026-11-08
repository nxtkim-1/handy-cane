# Data collection and threshold tuning (MASTER 20.2)

Goal: ~45 minutes of labelled cane data to replace the guessed thresholds in `cane/canesense/fsm.py`
(`Config`) and `cane/canesense/features.py` (`T_ACTIVE`, `T_STRIKE`, ...). Everything runs offline with
stdlib + numpy: `python -m tools.<name>`.

## Safety rules (read before anyone moves)

- Healthy adult volunteers only, who gave informed consent. Never anyone with balance, bone or
  cardiovascular problems, and never the patient or any real cane user.
- Simulated falls only on crash mats (or a gym mat stack at least 10 cm), with a spotter beside the
  volunteer. Start from a kneeling or squatting position, then slow, controlled falls onto the mat; no
  falls from standing height in the first pass. The volunteer can stop at any time, no questions asked.
- Clear 2 m around the mat, no furniture, no stairs. Do the stairs/stumble items on the ground floor with a
  rail only, and skip them if anyone is unsure.
- Keep the sensor taped and strain-relieved; a cane tip or electronics under a falling person is the
  main injury risk. If a cable or the Pi is in the way, use a lightweight dummy shaft on the mat.
- Stop the session and keep the data if anyone reports pain. Fall items are optional: the
  drop/knock/tap negatives alone are still very valuable.
- Do not claim clinical validity from this data (MASTER 9.2): it tunes the alarm only.

## Before you start (10 min)

- [ ] Sensor firmly mounted below the handle, same position as the final cane. Note ADXL345 vs other (MASTER 6.2).
- [ ] Calibrate upright: hold the cane vertical and still for 3 s. Do this at the start of every session and
      keep the first labelled segment `idle` (the evaluator estimates the upright vector from it, or pass it as `meta.upright`).
- [ ] Mats down, spotter assigned, timer visible, an assistant to write the notes.
- [ ] Dry-run the tooling with no hardware: `python -m tools.synth_sessions --out data/synth` then
      `python -m tools.evaluate data/synth/*.npz --sweep none`.

## Protocol (about 45 min, one `person` at a time)

Record every row as its own labelled segment, in this order (negatives first, falls last).

| # | Label | Do this | Reps x duration | Time |
|---|---|---|---|---|
| 1 | idle | stand upright, cane held (also the calibration) | 1 x 30 s | 1 min |
| 2 | walk | normal walk, cane in the usual hand | 3 x 2 min (3 people x 2 total) | 6 min |
| 3 | walk | slow / shuffling walk | 2 x 2 min | 4 min |
| 4 | idle | standing talking, shifting weight | 2 x 1 min | 2 min |
| 5 | sit | seated, cane held / between the knees / hooked on the chair | 2 x 1 min each posture | 6 min |
| 6 | lean | cane leaned on a wall or table, then picked up | 2 x 1 min | 2 min |
| 7 | car | cane flat on a car seat or lap during a drive (or a chair + shaking) | 1 x 5 min | 5 min |
| 8 | floor_tap | hard taps of the tip on the floor | 10 taps in 3 bursts | 2 min |
| 9 | drop_hand | let go of the cane (forward, sideways), pick it up within a few seconds | 15 | 6 min |
| 10 | knock_over | knock a leaned cane over, pick it up | 10 | 4 min |
| 11 | other | carry horizontally, set down and lift, swing, stairs with rail | 2 x 1 min | 2 min |
| 12 | fall_sim | on the mats (optional, see safety): walk 3 steps, fall, lie still 45 s or more, then get up | 5-10 | 10 min |

Notes for fall_sim: half of them press the button (short press) about 25 s after landing, the other half
do not and finish by **long-pressing the button 3 s** after getting up (otherwise the FSM stays in ALERT and
the next recording is polluted). Write down which was which in the notes. Add a few "cane left lying 20 s"
drops separately as `drop_hand` with a note: they are expected to alert, and measure how much you care.

## Commands

Option A, firmware record.py (the Pi's own recorder, stop the cane service first):

```
cd pi && .venv/bin/python record.py walking          # Ctrl+C ends; writes data/raw/walking_HHMMSS.csv
# ... one run per row above; labels: walking still hanging dropped fall  (stumble stairs -> other)
cd .. && python -m tools.session import-firmware pi/data/raw/walking_*.csv pi/data/raw/still_*.csv \
    pi/data/raw/dropped_*.csv pi/data/raw/fall_*.csv --out data/p1.npz --person p1 --notes "ADXL345, right hand"
```

`record.py` has no `sit`, `knock_over`, `floor_tap`, `car`, `lean` (hanging is the closest) labels, so
name those files by passing labels explicitly: `--labels walking,sit,knock_over,...` in file order (any of
our ten labels is accepted).

Option B, the generic recorder (any source that prints `ax,ay,az[,button]` lines in g):

```
python -m tools.record_session --source stream --input - --rate 100 --person p1 \
    --plan idle:30,walk:120,drop_hand:60 --out data/p1.npz < samples.txt
```

Option C, simulator rehearsal: `python -m tools.record_session --source sim --plan walk:30,drop_hand:0,fall_sim:0 --out data/sim.npz`.

Check each file right away: `python -m tools.session info data/p1.npz` (labels, duration). Re-record any
segment where the label timing is wrong; labels must cover the whole event.

## Evaluate and pick thresholds

```
python -m tools.evaluate data/p*.npz --json results.json            # per-label report + one-at-a-time sweep
python -m tools.evaluate data/p*.npz --sweep full --jobs 4 --json results_full.json
```

Read, in this order:

1. **Per-label table**: `walk` strikes/min (expect ~40-70 for ~1 Hz strike rate) and `active_s` close to 60
   tell you if `T_STRIKE` / `T_ACTIVE` are right. If walking shows few strikes, lower `T_STRIKE`; if `idle`
   shows any, raise it. `flat_s` should be ~0 for walk/idle and large for car.
2. **False alarms per hour of normal use** and which labels alerted. Target 0 pre-alerts on walk/idle/sit/lean/car;
   a long lying drop or knock is the known unfixable class (it looks like a fall), count it separately.
3. **Sensitivity on fall_sim** (pre-alert) and the median trigger-to-pre-alert time (~13 s with defaults).
4. **Drop vs fall confusion**: want drops quiet and falls loud.
5. **Sweep table**: choose the row with sensitivity 1.0 (or best) and the fewest false pre-alerts per hour.
   `still_required_s` and `tilt_trigger_deg` trade sensitivity for false alarms; `t_impact_g` matters little
   when the tilt trigger also fires (check your sensor: a +-1.5 g part needs ~1.4); `pre_alert_s` only
   moves the escalation time, never raise it above what a person can reach the button in.
   Numbers from fewer than ~1 hour of normal use are indicative only; say so when reporting.

## Feeding results back

1. Edit the defaults in `cane/canesense/fsm.py` `Config` (`t_impact_g`, `tilt_trigger_deg`, `still_required_s`,
   `pre_alert_s`, `still_std_g`) and `cane/canesense/features.py` (`T_ACTIVE`, `T_STRIKE`, `MIN_STRIKE_GAP_S`,
   `UPRIGHT_DEG`, `FLAT_DEG`). Remove the "PROPOSED" comments only for values you validated.
2. Re-run `python -m tools.evaluate data/p*.npz --sweep none` and `python -m pytest cane tools -q`; fix tests that
   encoded the old guesses (`cane/tests/test_fsm.py`).
3. Hand the same numbers to the firmware team: their detector uses its own constants in `pi/config.py`
   (`IMPACT_G`, `DOWN_MIN_DEG`, `UPRIGHT_MAX_DEG`, `STILL_G`, `DOWN_CONFIRM_S`, ...). The mapping is not 1:1
   (their timeline is ask/alert, ours is pre_alert/alert), so re-run their regression tests after changing them.
4. Commit the result JSON (`results.json`) and a one-paragraph note (people, sensor, date, counts) next to the data.
   Keep raw data out of git unless the volunteers consented to sharing it.
