-- 001_init.sql: Smart Cane schema, copied from MASTER.md 12.2 (PostgreSQL + TimescaleDB).
-- Differences from the SQLAlchemy models (used for SQLite dev/tests): native enums, hypertables, continuous
-- aggregate and array types exist only here. NOT executed by the test-suite.
-- Additions beyond 12.2: ingest_batches.response_json, refresh_tokens.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS citext;

-- ---------- identity & access ----------
CREATE TYPE user_role AS ENUM ('patient', 'caregiver', 'clinician', 'admin');

CREATE TABLE users (
  user_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         citext UNIQUE NOT NULL,          -- requires CREATE EXTENSION citext
  password_hash text NOT NULL,                   -- argon2id
  display_name  text NOT NULL,
  role          user_role NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  disabled_at   timestamptz
);

CREATE TABLE patients (
  patient_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid UNIQUE REFERENCES users(user_id),  -- nullable: patient may not log in
  display_name  text NOT NULL,                          -- never sent to Gemini
  timezone      text NOT NULL DEFAULT 'America/Toronto',
  enrolled_at   timestamptz NOT NULL DEFAULT now(),
  report_anchor date NOT NULL DEFAULT current_date,     -- 14-day periods start here
  is_simulated  boolean NOT NULL DEFAULT false,
  consent_at    timestamptz,                            -- must be set before ingest is accepted
  consent_version text
);

CREATE TYPE care_relation AS ENUM ('self', 'caregiver', 'clinician');

CREATE TABLE care_team (
  patient_id  uuid NOT NULL REFERENCES patients(patient_id) ON DELETE CASCADE,
  user_id     uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  relation    care_relation NOT NULL,
  can_dismiss_events boolean NOT NULL DEFAULT false,
  granted_by  uuid REFERENCES users(user_id),
  granted_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at  timestamptz,
  PRIMARY KEY (patient_id, user_id)
);

-- ---------- devices ----------
CREATE TABLE devices (
  device_id     text PRIMARY KEY,                 -- e.g. 'cane-7f3a'
  hw_model      text NOT NULL DEFAULT 'rpi4b',
  sensor_model  text,                             -- 'ADXL345' | 'MMA7660'
  fw_version    text,
  secret_hash   text NOT NULL,                    -- device pairing secret (hashed)
  is_simulated  boolean NOT NULL DEFAULT false,
  last_seen_at  timestamptz,
  last_seq      bigint NOT NULL DEFAULT 0
);

CREATE TABLE device_assignments (
  device_id   text NOT NULL REFERENCES devices(device_id),
  patient_id  uuid NOT NULL REFERENCES patients(patient_id),
  valid_from  timestamptz NOT NULL,
  valid_to    timestamptz,                         -- NULL = current
  PRIMARY KEY (device_id, valid_from)
);

-- ---------- time series ----------
CREATE TYPE time_quality AS ENUM ('synced', 'corrected', 'unsynced');

CREATE TABLE minute_metrics (
  device_id      text NOT NULL,
  ts             timestamptz NOT NULL,             -- start of minute, UTC
  seq            bigint NOT NULL,
  boot_id        uuid NOT NULL,
  time_quality   time_quality NOT NULL,
  n_samples      smallint NOT NULL,
  mag_mean       real, mag_std real, mag_max real,
  dyn_mean       real,
  active_s       smallint NOT NULL,
  strike_count   smallint NOT NULL,
  strike_iv_mean real, strike_iv_cv real,          -- NULL if < 5 strikes
  upright_s      smallint NOT NULL,
  flat_s         smallint NOT NULL,
  max_impact_g   real,
  is_simulated   boolean NOT NULL DEFAULT false,
  ingested_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (device_id, ts)                      -- unique index must include time column
);
SELECT create_hypertable('minute_metrics', by_range('ts', INTERVAL '7 days'));
CREATE UNIQUE INDEX minute_metrics_seq_uq ON minute_metrics (device_id, seq, ts);

CREATE TYPE event_kind AS ENUM ('potential_fall', 'help_request', 'impact_only');
CREATE TYPE event_status AS ENUM ('open', 'acknowledged', 'dismissed');

CREATE TABLE device_events (
  event_id       uuid NOT NULL,                    -- generated on the Pi
  device_id      text NOT NULL,
  ts             timestamptz NOT NULL,
  seq            bigint NOT NULL,
  time_quality   time_quality NOT NULL,
  kind           event_kind NOT NULL,
  outcome        text NOT NULL,                    -- cancelled_by_user | escalated | acknowledged_on_cane
  confidence     real,                             -- FSM score 0..1, NOT a probability
  peak_g real, tilt_deg real, still_s real,
  raw_snippet    bytea,                            -- optional ±10 s int16 samples
  status         event_status NOT NULL DEFAULT 'open',
  status_reason  text,                             -- e.g. 'false_alarm_dropped_cane'
  status_by      uuid REFERENCES users(user_id),
  status_at      timestamptz,
  is_simulated   boolean NOT NULL DEFAULT false,
  PRIMARY KEY (event_id, ts)
);
SELECT create_hypertable('device_events', by_range('ts', INTERVAL '30 days'));
CREATE UNIQUE INDEX device_events_seq_uq ON device_events (device_id, seq, ts);
CREATE INDEX device_events_device_ts ON device_events (device_id, ts DESC);

-- ---------- rollups ----------
-- Fast per-day sums per device (UTC buckets); local-day logic is done in daily_metrics.
CREATE MATERIALIZED VIEW minute_metrics_hourly
WITH (timescaledb.continuous) AS
SELECT device_id,
       time_bucket(INTERVAL '1 hour', ts) AS bucket,
       count(*) FILTER (WHERE n_samples >= 2700 AND time_quality <> 'unsynced') AS covered_min,
       sum(active_s)     AS active_s,
       sum(strike_count) AS strikes,
       sum(upright_s)    AS upright_s,
       bool_or(is_simulated) AS any_simulated
FROM minute_metrics
GROUP BY device_id, bucket;
SELECT add_continuous_aggregate_policy('minute_metrics_hourly',
  start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '15 minutes');

CREATE TABLE daily_metrics (
  patient_id       uuid NOT NULL REFERENCES patients(patient_id),
  day              date NOT NULL,                  -- patient-local date
  valid            boolean NOT NULL,
  coverage_h       real NOT NULL,
  active_min       real, strikes integer,
  bouts integer, bout_median_s real, bout_longest_s real,
  rhythm_cv_median real,
  active_by_hour   smallint[24],
  events_potential_fall smallint NOT NULL DEFAULT 0,
  events_cancelled smallint NOT NULL DEFAULT 0,
  help_presses     smallint NOT NULL DEFAULT 0,
  is_simulated     boolean NOT NULL DEFAULT false,
  computed_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (patient_id, day)
);

CREATE TABLE baselines (
  baseline_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id   uuid NOT NULL REFERENCES patients(patient_id),
  start_day    date NOT NULL, end_day date NOT NULL,
  n_valid_days smallint NOT NULL,
  stats        jsonb NOT NULL,   -- {"active_min":{"median":..,"mad":..}, ...}
  is_active    boolean NOT NULL DEFAULT true,
  set_by       uuid REFERENCES users(user_id),  -- NULL = automatic initial baseline
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX one_active_baseline ON baselines (patient_id) WHERE is_active;

CREATE TABLE change_flags (
  patient_id uuid NOT NULL REFERENCES patients(patient_id),
  metric     text NOT NULL,
  day        date NOT NULL,
  direction  text NOT NULL CHECK (direction IN ('up','down')),
  method     text NOT NULL,             -- 'rolling_median_z' | 'cusum'
  value      real NOT NULL,             -- z or CUSUM statistic
  PRIMARY KEY (patient_id, metric, day, method)
);

CREATE TYPE report_status AS ENUM ('pending','generated','fallback','insufficient_data','failed');

CREATE TABLE reports (
  report_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id     uuid NOT NULL REFERENCES patients(patient_id),
  period_start   date NOT NULL, period_end date NOT NULL,
  status         report_status NOT NULL,
  input_json     jsonb NOT NULL,       -- exact numbers given to Gemini
  output_json    jsonb,                -- validated Gemini (or template) output
  model          text, prompt_version text NOT NULL,
  validation     jsonb,                -- {"passed":true,"checks":[...]}
  attempts       smallint NOT NULL DEFAULT 0,
  is_simulated   boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (patient_id, period_start)    -- idempotent generation
);

CREATE TABLE ingest_batches (
  batch_id     uuid PRIMARY KEY,       -- client-generated
  device_id    text NOT NULL,
  uploaded_by  uuid REFERENCES users(user_id),
  min_seq bigint, max_seq bigint,
  n_records int, n_inserted int,
  response_json jsonb,                 -- exact response, returned verbatim when batch_id is replayed
  received_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
  id          bigserial PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  user_id     uuid,
  action      text NOT NULL,           -- 'view_patient','dismiss_event','generate_report',...
  patient_id  uuid,
  detail      jsonb
);

-- Refresh-token rotation / revocation list (MASTER 16.1)
CREATE TABLE refresh_tokens (
  jti        text PRIMARY KEY,
  user_id    uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);
CREATE INDEX refresh_tokens_user ON refresh_tokens (user_id);
CREATE INDEX audit_log_patient_at ON audit_log (patient_id, at DESC);
