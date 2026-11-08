# Progress log

Plan: `app/MASTER.md`. Branch: `dev/software-mvp`. Run tests: `python -m pytest -q`.

## Done
- `cane/common/schema.py` - minute/event record contract (MASTER 7.4, 13.2)
- `cane/canesense/features.py` - per-minute features (strikes, active seconds, tilt, rhythm CV)
- `cane/canesense/fsm.py` - potential-fall state machine, pure logic, no I/O (MASTER 10.1)
- `backend/app/analytics/stats.py` - baseline (median/MAD), robust z, rolling median, change flags
  (rolling-z + CUSUM), Theil-Sen trend, period comparison. Missing days stay NaN, never zero.
- `backend/sim/generate.py` - labelled simulated 8-week patient (`is_simulated=True`)
- 14 unit tests

## Findings
- MASTER's suggested sim decline (2%/wk active, 1.5%/wk bout) is too small for the detector to flag
  against ~10% daily noise. Sim defaults raised to 5%/4% per week with 7% noise. Real thresholds
  still need tuning on real data.
- Fixed in features: zero-padded moving average created a false strike at each minute edge.

## Next
1. Backend: FastAPI app, DB models, ingest endpoint with `(device_id, seq)` dedup, auth
2. Gemini report pipeline: input builder, validator, template fallback
3. Pi: sampler (needs hardware; accelerometer model unknown, MASTER U1), sync server
4. Mobile app (Expo): needs its own environment (Node is available)
