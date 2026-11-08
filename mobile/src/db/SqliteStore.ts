import * as SQLite from 'expo-sqlite';
import type { CaneRecord } from '../types';
import type { ApplyPageResult, DeadLetter, LocalStore, QueueItem } from './LocalStore';

export const SCHEMA = `
CREATE TABLE IF NOT EXISTS cane_records (
  device_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  type TEXT NOT NULL,
  ts TEXT NOT NULL,
  json TEXT NOT NULL,
  PRIMARY KEY (device_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_cane_records_ts ON cane_records (device_id, ts);
CREATE TABLE IF NOT EXISTS upload_queue (
  batch_id TEXT PRIMARY KEY NOT NULL,
  device_id TEXT NOT NULL,
  fw_version TEXT NOT NULL,
  first_seq INTEGER NOT NULL,
  payload TEXT NOT NULL,
  record_count INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_ms INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  last_error TEXT
);
CREATE TABLE IF NOT EXISTS dead_letters (
  device_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  batch_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  record_json TEXT,
  created_ms INTEGER NOT NULL,
  PRIMARY KEY (device_id, seq)
);
CREATE TABLE IF NOT EXISTS sync_cursor (
  device_id TEXT PRIMARY KEY NOT NULL,
  cursor INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports_cache (key TEXT PRIMARY KEY NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events_cache (key TEXT PRIMARY KEY NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
`;

export class SqliteStore implements LocalStore {
  private constructor(private db: SQLite.SQLiteDatabase) {}

  static async open(name = 'smartcane.db'): Promise<SqliteStore> {
    const db = await SQLite.openDatabaseAsync(name);
    await db.execAsync('PRAGMA journal_mode = WAL;');
    await db.execAsync(SCHEMA);
    return new SqliteStore(db);
  }

  async getCursor(deviceId: string): Promise<number> {
    const row = await this.db.getFirstAsync<{ cursor: number }>(
      'SELECT cursor FROM sync_cursor WHERE device_id = ?', [deviceId]);
    return row?.cursor ?? 0;
  }

  async applyPage(a: {
    deviceId: string; fwVersion: string; records: CaneRecord[]; nextCursor: number; batchId: string;
  }): Promise<ApplyPageResult> {
    let inserted = 0;
    await this.db.withExclusiveTransactionAsync(async (tx) => {
      const fresh: CaneRecord[] = [];
      for (const r of a.records) {
        const res = await tx.runAsync(
          'INSERT OR IGNORE INTO cane_records (device_id, seq, type, ts, json) VALUES (?,?,?,?,?)',
          [a.deviceId, r.seq, r.type, r.ts, JSON.stringify(r)]);
        if (res.changes > 0) fresh.push(r);
      }
      await tx.runAsync(
        `INSERT INTO sync_cursor (device_id, cursor) VALUES (?, ?)
         ON CONFLICT(device_id) DO UPDATE SET cursor = MAX(cursor, excluded.cursor)`,
        [a.deviceId, a.nextCursor]);
      if (fresh.length > 0) {
        await tx.runAsync(
          `INSERT INTO upload_queue (batch_id, device_id, fw_version, first_seq, payload, record_count)
           VALUES (?,?,?,?,?,?)`,
          [a.batchId, a.deviceId, a.fwVersion, fresh[0].seq, JSON.stringify(fresh), fresh.length]);
      }
      inserted = fresh.length;
    });
    return { inserted, duplicates: a.records.length - inserted };
  }

  async listRecords(deviceId: string, sinceTs?: string): Promise<CaneRecord[]> {
    const rows = sinceTs
      ? await this.db.getAllAsync<{ json: string }>(
          'SELECT json FROM cane_records WHERE device_id=? AND ts>=? ORDER BY seq', [deviceId, sinceTs])
      : await this.db.getAllAsync<{ json: string }>(
          'SELECT json FROM cane_records WHERE device_id=? ORDER BY seq', [deviceId]);
    return rows.map((r) => JSON.parse(r.json) as CaneRecord);
  }

  async countRecords(deviceId: string): Promise<number> {
    const row = await this.db.getFirstAsync<{ n: number }>(
      'SELECT COUNT(*) AS n FROM cane_records WHERE device_id=?', [deviceId]);
    return row?.n ?? 0;
  }

  async dueBatches(nowMs: number, limit: number): Promise<QueueItem[]> {
    return this.db.getAllAsync<QueueItem>(
      `SELECT batch_id, device_id, fw_version, payload, record_count, attempts,
              next_attempt_ms, status, last_error
       FROM upload_queue WHERE status='pending' AND next_attempt_ms <= ?
       ORDER BY first_seq LIMIT ?`, [nowMs, limit]);
  }

  async queueStats() {
    const p = await this.db.getFirstAsync<{ b: number; r: number | null }>(
      `SELECT COUNT(*) AS b, SUM(record_count) AS r FROM upload_queue WHERE status='pending'`);
    const d = await this.db.getFirstAsync<{ n: number }>(
      `SELECT COUNT(*) AS n FROM upload_queue WHERE status='dead'`);
    const l = await this.db.getFirstAsync<{ n: number }>('SELECT COUNT(*) AS n FROM dead_letters');
    return { batches: p?.b ?? 0, records: p?.r ?? 0, dead: (d?.n ?? 0) + (l?.n ?? 0) };
  }

  async completeBatch(batchId: string): Promise<void> {
    await this.db.runAsync('DELETE FROM upload_queue WHERE batch_id=?', [batchId]);
  }

  async deadLetterRecords(batchId: string, rejects: { seq: number; reason: string; index?: number }[]): Promise<void> {
    const q = await this.db.getFirstAsync<{ device_id: string; payload: string }>(
      'SELECT device_id, payload FROM upload_queue WHERE batch_id=?', [batchId]);
    if (!q) return;
    const recs = JSON.parse(q.payload) as CaneRecord[];
    await this.db.withExclusiveTransactionAsync(async (tx) => {
      for (const rj of rejects) {
        const rec = recs.find((r) => r.seq === rj.seq) ?? (rj.index !== undefined ? recs[rj.index] : undefined);
        await tx.runAsync(
          `INSERT OR REPLACE INTO dead_letters (device_id, seq, batch_id, reason, record_json, created_ms)
           VALUES (?,?,?,?,?,?)`,
          [q.device_id, rec?.seq ?? rj.seq, batchId, rj.reason, rec ? JSON.stringify(rec) : null, Date.now()]);
      }
    });
  }

  async listDeadLetters(): Promise<DeadLetter[]> {
    return this.db.getAllAsync<DeadLetter>(
      'SELECT device_id, seq, batch_id, reason, record_json, created_ms FROM dead_letters ORDER BY seq');
  }

  async failBatch(batchId: string, nextAttemptMs: number, error: string, dead: boolean): Promise<void> {
    await this.db.runAsync(
      `UPDATE upload_queue SET attempts=attempts+1, next_attempt_ms=?, last_error=?,
       status=CASE WHEN ? THEN 'dead' ELSE status END WHERE batch_id=?`,
      [nextAttemptMs, error, dead ? 1 : 0, batchId]);
  }

  async getMeta(key: string): Promise<string | null> {
    const row = await this.db.getFirstAsync<{ value: string }>('SELECT value FROM meta WHERE key=?', [key]);
    return row?.value ?? null;
  }

  async setMeta(key: string, value: string): Promise<void> {
    await this.db.runAsync(
      'INSERT INTO meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
      [key, value]);
  }

  async putCache(kind: 'reports' | 'events', key: string, json: string): Promise<void> {
    const t = kind === 'reports' ? 'reports_cache' : 'events_cache';
    await this.db.runAsync(
      `INSERT INTO ${t} (key, json) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET json=excluded.json`,
      [key, json]);
  }

  async getCache(kind: 'reports' | 'events', key: string): Promise<string | null> {
    const t = kind === 'reports' ? 'reports_cache' : 'events_cache';
    const row = await this.db.getFirstAsync<{ json: string }>(`SELECT json FROM ${t} WHERE key=?`, [key]);
    return row?.json ?? null;
  }
}
