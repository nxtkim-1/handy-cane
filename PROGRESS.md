# Progress log

Plan: `app/MASTER.md`. Branch: `dev/software-mvp`. Run tests: `python -m pytest -q`.

## Done
- `cane/common/schema.py` - minute/event record contract (MASTER 7.4, 13.2)
- `cane/canesense/features.py` - per-minute features (strikes, active seconds, tilt, rhythm CV)
- `cane/canesense/fsm.py` - potential-fall state machine, pure logic, no I/O (MASTER 10.1)
- `backend/app/analytics/stats.py` - baseline (median/MAD), robust z, rolling median, change flags
  (rolling-z + CUSUM), Theil-Sen trend, period comparison. Missing days stay NaN, never zero.
- `backend/sim/generate.py` - labelled simulated 8-week patient (`is_simulated=True`)
- `cane/canesense/store.py` SQLite WAL outbox: never-reused seq, boot_id, time_quality + phone time-sync correction
- `cane/canesense/runtime.py` sampling loop (hardware injected) and `sim_hw.py` simulated sensor/button/buzzer
- `cane/canelink/server.py` HTTP sync API: GET /info, POST /time, GET /pull, POST /ack (stdlib only)
- `python -m cane.run_sim` runs a scripted session (walk, cancelled drop, escalated drop) and serves the API
- 18 unit and end-to-end tests (`python -m pytest -q`)

## Merged from agents
- agent/backend: FastAPI API (auth, patients, ingest with dedup + replay, events, devices, audit), SQLite default,
  Postgres DDL in backend/migrations, seed script (`python -m backend.app.seed`), 22 API tests
- agent/reports: input builder, validator, Gemini client + fake, template fallback, pipeline, 79 tests combined
- Wired together: `POST /v1/patients/{pid}/reports/generate` builds the input from daily_metrics, uses Gemini only
  if GEMINI_API_KEY is set (else template), validates, stores. Tested end to end on the seeded patient.

## In progress
- agent/mobile: Expo app with mock cane transport (still running)

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
