# Running the backend

## Local, with Docker (API + TimescaleDB)
```
cp .env.example .env        # then edit: JWT_SECRET (32+ random chars), GEMINI_API_KEY (optional)
docker compose --profile local up --build   # API on http://localhost:8000 (docs at /docs), DB on localhost:5433
docker compose exec api python -m backend.app.seed     # demo accounts + 8 weeks of simulated data
```
Demo logins (password `demo-password-1`): `clinician@demo.example`, `patient@demo.example`, `caregiver@demo.example`.
Phones reach it at `http://<your-PC-IP>:8000` on the same Wi-Fi or hotspot.

## Tiger Cloud instead of the local DB
Set `DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:PORT/tsdb?sslmode=require` in `.env`
(note the `postgresql+psycopg://` prefix, not `postgres://`) and run only the API:
`docker compose up --build api`. On startup the app creates the tables and applies
`backend/migrations/002_timescale.sql` (hypertables, compression); it logs a warning and carries on
if the database is plain PostgreSQL.

## Without Docker (SQLite)
`pip install -r backend/requirements.txt && python -m backend.app.seed && uvicorn backend.app.main:app --host 0.0.0.0`

## Gemini reports
If `GEMINI_API_KEY` is set the report endpoint uses Gemini (`GEMINI_MODEL`, default `gemini-3.5-flash`);
otherwise it uses the deterministic template. Never commit `.env`.
