import type { CaneRecord } from '../types';

export interface QueueItem {
  batch_id: string;
  device_id: string;
  fw_version: string;
  /** JSON array of CaneRecord */
  payload: string;
  record_count: number;
  attempts: number;
  next_attempt_ms: number;
  status: 'pending' | 'dead';
  last_error: string | null;
}

export interface ApplyPageResult {
  inserted: number;
  duplicates: number;
}

/**
 * Local persistence (MASTER 15.1). All methods are async so the expo-sqlite
 * implementation and the in-memory test implementation are interchangeable.
 */
export interface LocalStore {
  getCursor(deviceId: string): Promise<number>;

  /**
   * ONE atomic transaction: insert records (ignoring duplicates on
   * device_id+seq), advance the cursor, and enqueue the newly inserted
   * records as a single upload batch. Either everything is stored or nothing.
   */
  applyPage(args: {
    deviceId: string;
    fwVersion: string;
    records: CaneRecord[];
    nextCursor: number;
    batchId: string;
  }): Promise<ApplyPageResult>;

  listRecords(deviceId: string, sinceTs?: string): Promise<CaneRecord[]>;
  countRecords(deviceId: string): Promise<number>;

  // upload_queue
  dueBatches(nowMs: number, limit: number): Promise<QueueItem[]>;
  queueStats(): Promise<{ batches: number; records: number; dead: number }>;
  completeBatch(batchId: string): Promise<void>;
  failBatch(batchId: string, nextAttemptMs: number, error: string, dead: boolean): Promise<void>;

  // key/value (last sync, etc.)
  getMeta(key: string): Promise<string | null>;
  setMeta(key: string, value: string): Promise<void>;

  // caches for offline reading
  putCache(kind: 'reports' | 'events', key: string, json: string): Promise<void>;
  getCache(kind: 'reports' | 'events', key: string): Promise<string | null>;
}
