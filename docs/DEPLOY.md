# Deploying the Smart Cane API

Run the FastAPI app with a single worker, e.g. `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`.
The scheduler and the rate limiter are in-process, so more than one worker would duplicate jobs and
split rate-limit counters. Tables are created (and new tables added) at startup by `init_db`; existing tables are
never altered.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./smartcane.db` | SQLAlchemy URL. PostgreSQL: `postgresql+psycopg://user:pw@host:5432/db` (needs `psycopg[binary]`). |
| `JWT_SECRET` | dev default | Random string, at least 32 characters. The API logs a loud warning at startup if it is the dev default or shorter than 32. |
| `GEMINI_API_KEY` | unset | Enables Gemini phrasing of reports; without it the deterministic template is used. |
| `ESCALATION_WEBHOOK_URL` | unset | Discord-compatible webhook. A new high-severity open event POSTs `{"content": "..."}` (5 s timeout, outside the request). If unset, one log line is written and the attempt is still recorded in `escalations`. |
| `ESCALATION_REPEAT_MINUTES` | `10` | Re-notify if the event is still open after this many minutes. |
| `ESCALATION_MAX_REPEATS` | `3` | Maximum notifications per event, including the first. Acknowledging or dismissing the event stops them. |
| `SCHEDULER_ENABLED` | `true` | Starts APScheduler from the app lifespan: escalation repeat check every minute, biweekly report generation daily 03:00 UTC, expired/revoked refresh-token cleanup daily 03:30 UTC. Set `false` for tests or extra workers. |

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
