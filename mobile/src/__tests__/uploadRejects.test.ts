import { MemoryStore } from '../db/MemoryStore';
import type { LocalStore } from '../db/LocalStore';
import type { CaneRecord } from '../types';
import { describeRejects, IngestError, runUploadWorker } from '../sync/uploadWorker';

// Minimal expo-sqlite shim over node:sqlite so SqliteStore itself runs in jest (Node >= 22.5).
let nodeSqlite: any = null;
try { nodeSqlite = require('node:sqlite'); } catch { /* unavailable: SqliteStore tests skip */ }
jest.mock('expo-sqlite', () => ({
  openDatabaseAsync: async () => {
    const { DatabaseSync } = require('node:sqlite');
    const d = new DatabaseSync(':memory:');
    const api: any = {
      execAsync: async (sql: string) => { d.exec(sql); },
      runAsync: async (sql: string, p: any[] = []) => ({ changes: Number(d.prepare(sql).run(...p).changes) }),
      getFirstAsync: async (sql: string, p: any[] = []) => d.prepare(sql).get(...p) ?? null,
      getAllAsync: async (sql: string, p: any[] = []) => d.prepare(sql).all(...p),
      withExclusiveTransactionAsync: async (fn: any) => {
        d.exec('BEGIN');
        try { await fn(api); d.exec('COMMIT'); } catch (e) { d.exec('ROLLBACK'); throw e; }
      },
    };
    return api;
  },
}));

function rec(seq: number): CaneRecord {
  return {
    type: 'event', seq, event_id: `e${seq}`, boot_id: 'b', ts: '2026-01-01T00:00:00Z', time_quality: 'corrected',
    kind: 'potential_fall', outcome: 'escalated', cause: 'cane_down_impact', confidence: 1,
    peak_g: 4, tilt_deg: 80, still_s: 10, raw_snippet_b64: null,
  };
}

async function seed(store: LocalStore, seqs: number[], batchId: string) {
  await store.applyPage({ deviceId: 'cane-1', fwVersion: 'fw', records: seqs.map(rec), nextCursor: Math.max(...seqs), batchId });
}

const resp = (b: any, rejected: any[]) => ({
  batch_id: b.batch_id, received: b.records.length, inserted: b.records.length - rejected.length,
  duplicates: 0, rejected, server_max_seq: 9,
});

function suite(name: string, make: () => Promise<LocalStore>) {
  describe(`${name}: server rejects on HTTP 200`, () => {
    test('a) partial reject: accepted completed, rejected dead-lettered with reason, worker moves on', async () => {
      const store = await make();
      await seed(store, [1, 2, 3], 'aaaaaaaa-0000-4000-8000-000000000001');
      await seed(store, [4, 5], 'aaaaaaaa-0000-4000-8000-000000000002');
      const reason = "kind: Input should be 'potential_fall', 'help_request' or 'impact_only'";
      const calls: string[] = [];
      const sink = {
        postIngestBatch: async (b: any) => {
          calls.push(b.batch_id);
          return resp(b, b.records.length === 3 ? [{ index: 1, seq: 2, reason }] : []);
        },
      };
      const r = await runUploadWorker({ store, sink, now: () => 0 });
      expect(calls.length).toBe(2); // continued to the next batch
      expect(r.failed).toBe(false);
      expect(r.uploaded).toBe(2);
      expect(r.records).toBe(4); // 2 accepted + 2 in batch two
      expect(r.rejected).toEqual([{ batch_id: 'aaaaaaaa-0000-4000-8000-000000000001', seq: 2, reason }]);
      expect(r.remaining).toEqual({ batches: 0, records: 0, dead: 1 });
      const dl = await store.listDeadLetters();
      expect(dl.length).toBe(1);
      expect(dl[0]).toMatchObject({ seq: 2, reason, device_id: 'cane-1' });
      expect(JSON.parse(dl[0].record_json!).seq).toBe(2);
      // never retried
      const again = await runUploadWorker({ store, sink, now: () => 10 ** 9 });
      expect(again.uploaded).toBe(0);
      expect(calls.length).toBe(2);
      expect(describeRejects(r.rejected)).toContain('seq 2');
    });

    test('b) total reject: nothing completed, all dead-lettered, no retry or backoff', async () => {
      const store = await make();
      await seed(store, [1, 2, 3], 'aaaaaaaa-0000-4000-8000-000000000003');
      let n = 0;
      const sink = {
        postIngestBatch: async (b: any) => {
          n++;
          return resp(b, b.records.map((x: any, i: number) => ({ index: i, seq: x.seq, reason: `bad ${x.seq}` })));
        },
      };
      const r = await runUploadWorker({ store, sink, now: () => 0 });
      expect(r.uploaded).toBe(0);
      expect(r.records).toBe(0);
      expect(r.failed).toBe(false);
      expect(r.rejected.map((x) => x.seq)).toEqual([1, 2, 3]);
      expect(r.remaining).toEqual({ batches: 0, records: 0, dead: 3 });
      expect((await store.listDeadLetters()).map((d) => d.reason)).toEqual(['bad 1', 'bad 2', 'bad 3']);
      expect(await store.getMeta('upload_backoff_until_ms')).toBeNull();
      expect(await store.dueBatches(10 ** 12, 10)).toEqual([]);
      await runUploadWorker({ store, sink, now: () => 10 ** 12 });
      expect(n).toBe(1);
    });

    test('c) clean 200 with rejected empty completes the batch', async () => {
      const store = await make();
      await seed(store, [1, 2, 3], 'aaaaaaaa-0000-4000-8000-000000000004');
      const sink = { postIngestBatch: async (b: any) => resp(b, []) };
      const r = await runUploadWorker({ store, sink, now: () => 0 });
      expect(r).toMatchObject({ uploaded: 1, records: 3, failed: false, rejected: [] });
      expect(r.remaining).toEqual({ batches: 0, records: 0, dead: 0 });
      expect(await store.listDeadLetters()).toEqual([]);
    });

    test('transient failure still backs off and keeps the batch (no dead letters)', async () => {
      const store = await make();
      await seed(store, [1], 'aaaaaaaa-0000-4000-8000-000000000005');
      const sink = { postIngestBatch: async () => { throw new IngestError(503, 'down'); } };
      const r = await runUploadWorker({ store, sink, now: () => 0 });
      expect(r.failed).toBe(true);
      expect(r.remaining).toEqual({ batches: 1, records: 1, dead: 0 });
    });

    test('dead-lettering is idempotent (crash before completeBatch, then server re-reports)', async () => {
      const store = await make();
      await seed(store, [1, 2], 'aaaaaaaa-0000-4000-8000-000000000006');
      await store.deadLetterRecords('aaaaaaaa-0000-4000-8000-000000000006', [{ seq: 2, reason: 'x' }]);
      await store.deadLetterRecords('aaaaaaaa-0000-4000-8000-000000000006', [{ seq: 2, reason: 'x' }]);
      expect((await store.listDeadLetters()).length).toBe(1);
      expect((await store.queueStats()).dead).toBe(1);
    });
  });
}

suite('MemoryStore', async () => new MemoryStore());

const maybe = nodeSqlite ? describe : describe.skip;
maybe('SqliteStore (node:sqlite shim)', () => {
  suite('SqliteStore', async () => {
    const { SqliteStore } = require('../db/SqliteStore');
    return SqliteStore.open();
  });
});

describe('describeRejects', () => {
  test('null when empty; user-readable otherwise', () => {
    expect(describeRejects([])).toBeNull();
    expect(describeRejects([{ seq: 900, reason: 'kind invalid' }])).toMatch(/1 record was permanently rejected.*seq 900: kind invalid/);
  });
});
