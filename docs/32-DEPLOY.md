# Running the backend

Run the FastAPI app with a **single worker**. The scheduler and the rate limiter are in-process, so more than
one worker would duplicate jobs and split rate-limit counters. Tables are created (and new tables added) at
startup by `init_db`; existing tables are never altered.

## Local, with Docker (API + TimescaleDB)
```
cp .env.example .env        # then edit: JWT_SECRET (32+ random chars), GEMINI_API_KEY (optional)
docker compose --profile local up --build   # API on http://localhost:8000 (docs at /docs), DB on localhost:5433
docker compose exec api python -m backend.app.seed     # demo accounts + 8 weeks of simulated data
```
Demo logins (password `demo-password-1`): `clinician@demo.example`, `patient@demo.example`,
`caregiver@demo.example`, `live@demo.example` (the live, non-simulated patient for the real cane).
Phones reach it at `http://<your-PC-IP>:8000` on the same Wi-Fi or hotspot.

## Tiger Cloud instead of the local DB
Set `DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:PORT/tsdb?sslmode=require` in `.env`
(note the `postgresql+psycopg://` prefix, not `postgres://`) and run only the API:
`docker compose up --build api`. On startup the app creates the tables and applies
`backend/migrations/002_timescale.sql` (hypertables, compression); it logs a warning and carries on
if the database is plain PostgreSQL.

## Without Docker (SQLite)
`pip install -r backend/requirements.txt && python -m backend.app.seed && uvicorn backend.app.main:app --host 0.0.0.0`

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./smartcane.db` | SQLAlchemy URL. PostgreSQL: `postgresql+psycopg://user:pw@host:5432/db` (needs `psycopg[binary]`). |
| `JWT_SECRET` | dev default | Random string, at least 32 characters. The API logs a loud warning at startup if it is the dev default or shorter than 32. |
| `GEMINI_API_KEY` | unset | Enables Gemini phrasing of reports; without it the deterministic template is used. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Model used for reports. |
| `ESCALATION_WEBHOOK_URL` | unset | Discord-compatible webhook. A new high-severity open event POSTs `{"content": "..."}` (5 s timeout, outside the request). If unset, one log line is written and the attempt is still recorded in `escalations`. |
| `ESCALATION_REPEAT_MINUTES` | `10` | Re-notify if the event is still open after this many minutes. |
| `ESCALATION_MAX_REPEATS` | `3` | Maximum notifications per event, including the first. Acknowledging or dismissing the event stops them. |
| `SCHEDULER_ENABLED` | `true` | Starts APScheduler from the app lifespan: escalation repeat check every minute, biweekly report generation daily 03:00 UTC, expired/revoked refresh-token cleanup daily 03:30 UTC. Set `false` for tests or extra workers. |

Never commit `.env`.

## Tests against PostgreSQL / TimescaleDB
```
docker run -d --name cane-pgtest -e POSTGRES_PASSWORD=t -e POSTGRES_DB=t -p 5434:5432 timescale/timescaledb:latest-pg16
pip install "psycopg[binary]"
TEST_DATABASE_URL=postgresql+psycopg://postgres:t@localhost:5434/t python -m pytest -q
docker rm -f cane-pgtest
```
Without `TEST_DATABASE_URL` the suite uses in-memory SQLite.

## Data protection endpoints
- `POST /v1/patients/{id}/consent/withdraw` (patient only): clears consent; ingest returns `403 consent_required`.
- `DELETE /v1/patients/{id}/data` with body `{"confirm": true}` (patient only): deletes daily metrics, baselines,
  change flags, reports, events and minute metrics of the devices currently assigned. Audit rows are kept.

## Demo day: one command
```
.\scripts\start-demo.ps1 -Simulated                    # laptop + simulated cane, then Expo (scan the QR code)
.\scripts\start-demo.ps1 -CaneUrl http://<pi-ip>:8765  # with the real cane (start its link server with --lan)
.\scripts\start-demo.ps1 -Simulated -Local             # no internet: local database instead of Tiger Cloud
.\scripts\stop-demo.ps1                                # stop everything
```
The script fills the backend and cane addresses into the app, so it opens in live mode with nothing to type.
Join the phone hotspot first, and allow the ports once in Windows Firewall (the script prints the command).
