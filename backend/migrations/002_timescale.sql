-- 002_timescale.sql: run AFTER the ORM has created the tables (init_db / create_all) on a
-- PostgreSQL + TimescaleDB database (local Docker image or Tiger Cloud). Idempotent.
-- Turns the two high-volume tables into hypertables. TimescaleDB requires every unique index to
-- include the time column, so the (device_id, seq) uniqueness becomes (device_id, seq, ts);
-- the ingest code still de-duplicates on (device_id, seq) before inserting (MASTER 12.2, 13.2).

CREATE EXTENSION IF NOT EXISTS timescaledb;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'device_events_seq_uq') THEN
    ALTER TABLE device_events DROP CONSTRAINT device_events_seq_uq;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'minute_metrics_seq_uq') THEN
    ALTER TABLE minute_metrics DROP CONSTRAINT minute_metrics_seq_uq;
  END IF;
END $$;
DROP INDEX IF EXISTS minute_metrics_seq_uq;

CREATE UNIQUE INDEX IF NOT EXISTS minute_metrics_seq_uq ON minute_metrics (device_id, seq, ts);
CREATE UNIQUE INDEX IF NOT EXISTS device_events_seq_uq ON device_events (device_id, seq, ts);

SELECT create_hypertable('minute_metrics', by_range('ts', INTERVAL '7 days'),
                         if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('device_events', by_range('ts', INTERVAL '30 days'),
                         if_not_exists => TRUE, migrate_data => TRUE);

-- Compress minute data older than 30 days (MASTER 12.3). If your plan lacks compression, delete this block.
ALTER TABLE minute_metrics SET (timescaledb.compress, timescaledb.compress_segmentby = 'device_id',
                                timescaledb.compress_orderby = 'ts DESC');
SELECT add_compression_policy('minute_metrics', INTERVAL '30 days', if_not_exists => TRUE);
