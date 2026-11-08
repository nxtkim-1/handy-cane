import type { CaneRecord } from '../types';
import type { ApplyPageResult, LocalStore, QueueItem } from './LocalStore';

/** In-memory LocalStore for tests and web preview. applyPage is atomic by construction. */
export class MemoryStore implements LocalStore {
  private records = new Map<string, CaneRecord>(); // key device_id:seq
  private cursors = new Map<string, number>();
  private queue = new Map<string, QueueItem>();
  private meta = new Map<string, string>();
  private caches = new Map<string, string>();
  /** Test hook: throw inside applyPage after staging, to prove atomicity. */
  failNextApply = false;

  async getCursor(deviceId: string): Promise<number> {
    return this.cursors.get(deviceId) ?? 0;
  }

  async applyPage(a: {
    deviceId: string; fwVersion: string; records: CaneRecord[]; nextCursor: number; batchId: string;
  }): Promise<ApplyPageResult> {
    // stage
    const staged = new Map<string, CaneRecord>();
    const fresh: CaneRecord[] = [];
    let duplicates = 0;
    for (const r of a.records) {
      const key = `${a.deviceId}:${r.seq}`;
      if (this.records.has(key) || staged.has(key)) {
        duplicates++;
      } else {
        staged.set(key, r);
        fresh.push(r);
      }
    }
    if (this.failNextApply) {
      this.failNextApply = false;
      throw new Error('simulated storage failure');
    }
    // commit
    staged.forEach((v, k) => this.records.set(k, v));
    this.cursors.set(a.deviceId, Math.max(this.cursors.get(a.deviceId) ?? 0, a.nextCursor));
    if (fresh.length > 0) {
      this.queue.set(a.batchId, {
        batch_id: a.batchId, device_id: a.deviceId, fw_version: a.fwVersion,
        payload: JSON.stringify(fresh), record_count: fresh.length, attempts: 0,
        next_attempt_ms: 0, status: 'pending', last_error: null,
      });
    }
    return { inserted: fresh.length, duplicates };
  }

  async listRecords(deviceId: string, sinceTs?: string): Promise<CaneRecord[]> {
    const out: CaneRecord[] = [];
    this.records.forEach((r, k) => {
      if (k.startsWith(deviceId + ':') && (!sinceTs || r.ts >= sinceTs)) out.push(r);
    });
    return out.sort((x, y) => x.seq - y.seq);
  }

  async countRecords(deviceId: string): Promise<number> {
    return (await this.listRecords(deviceId)).length;
  }

  async dueBatches(nowMs: number, limit: number): Promise<QueueItem[]> {
    return Array.from(this.queue.values())
      .filter((q) => q.status === 'pending' && q.next_attempt_ms <= nowMs)
      .sort((a, b) => firstSeq(a) - firstSeq(b))
      .slice(0, limit);
  }

  async queueStats() {
    let batches = 0, records = 0, dead = 0;
    this.queue.forEach((q) => {
      if (q.status === 'pending') { batches++; records += q.record_count; } else dead++;
    });
    return { batches, records, dead };
  }

  async completeBatch(batchId: string): Promise<void> {
    this.queue.delete(batchId);
  }

  async failBatch(batchId: string, nextAttemptMs: number, error: string, dead: boolean): Promise<void> {
    const q = this.queue.get(batchId);
    if (!q) return;
    q.attempts += 1;
    q.next_attempt_ms = nextAttemptMs;
    q.last_error = error;
    if (dead) q.status = 'dead';
  }

  async getMeta(key: string) { return this.meta.get(key) ?? null; }
  async setMeta(key: string, value: string) { this.meta.set(key, value); }
  async putCache(kind: 'reports' | 'events', key: string, json: string) {
    this.caches.set(`${kind}:${key}`, json);
  }
  async getCache(kind: 'reports' | 'events', key: string) {
    return this.caches.get(`${kind}:${key}`) ?? null;
  }
}

function firstSeq(q: QueueItem): number {
  try {
    return (JSON.parse(q.payload) as CaneRecord[])[0]?.seq ?? 0;
  } catch {
    return 0;
  }
}
