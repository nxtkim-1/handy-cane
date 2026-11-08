import { MockApiClient } from '../api/MockApiClient';
import { MockCaneTransport } from '../comm/MockCaneTransport';
import { MemoryStore } from '../db/MemoryStore';
import { runPullSync } from '../sync/pullSync';
import { backoffMs, BACKOFF_MAX_MS, IngestError, runUploadWorker } from '../sync/uploadWorker';

let n = 0;
const newId = () => `b-${++n}`;

async function seeded() {
  const cane = new MockCaneTransport({ minutes: 30, fallAtMinute: 0 });
  const store = new MemoryStore();
  await runPullSync({ transport: cane, store, pageLimit: 10, newId });
  return { cane, store };
}

describe('upload worker', () => {
  test('uploads queued batches and empties the queue', async () => {
    const { store } = await seeded();
    const api = new MockApiClient();
    const r = await runUploadWorker({ store, sink: api, now: () => 0 });
    expect(r.uploaded).toBe(3);
    expect(r.failed).toBe(false);
    expect(r.remaining.batches).toBe(0);
    expect(api.ingested.map((b) => b.records.length)).toEqual([10, 10, 10]);
  });

  test('backend down keeps the queue; retries wait for backoff; then drains', async () => {
    const { store } = await seeded();
    const api = new MockApiClient();
    api.ingestDown = true;

    let t = 1_000_000;
    const r1 = await runUploadWorker({ store, sink: api, now: () => t });
    expect(r1.failed).toBe(true);
    expect(r1.remaining).toEqual({ batches: 3, records: 30, dead: 0 });

    // too soon: nothing due, queue intact
    const r2 = await runUploadWorker({ store, sink: api, now: () => t + 1000 });
    expect(r2.uploaded).toBe(0);
    expect(r2.failed).toBe(false);
    expect(r2.remaining.records).toBe(30);

    // after backoff, still down: backoff grows
    t += 6_000;
    await runUploadWorker({ store, sink: api, now: () => t });
    const due = await store.dueBatches(t + 9_000, 10);
    expect(due.length).toBe(2); // first batch now waits 10s, others still due
    expect((await store.dueBatches(t + 11_000, 10)).length).toBe(3);

    // backend recovers
    api.ingestDown = false;
    t += 20_000;
    const r3 = await runUploadWorker({ store, sink: api, now: () => t });
    expect(r3.uploaded).toBe(3);
    expect(r3.remaining.batches).toBe(0);
  });

  test('backoff doubles and caps at 15 minutes', () => {
    expect(backoffMs(0)).toBe(5_000);
    expect(backoffMs(1)).toBe(10_000);
    expect(backoffMs(2)).toBe(20_000);
    expect(backoffMs(20)).toBe(BACKOFF_MAX_MS);
  });

  test('resending a batch (lost response) is idempotent server-side', async () => {
    const { store } = await seeded();
    const api = new MockApiClient();
    const [first] = await store.dueBatches(0, 1);
    const batch = { batch_id: first.batch_id, device_id: first.device_id, fw_version: 'x', records: JSON.parse(first.payload) };
    await api.postIngestBatch(batch);
    const again = await api.postIngestBatch(batch);
    expect(again.inserted).toBe(0);
    expect(again.duplicates).toBe(10);
    expect(api.ingested.length).toBe(1);
  });

  test('a permanent 4xx rejection parks the batch instead of blocking the queue forever', async () => {
    const { store } = await seeded();
    let call = 0;
    const sink = {
      postIngestBatch: async (b: any) => {
        call++;
        if (call === 1) throw new IngestError(422, 'bad range');
        return { batch_id: b.batch_id, received: 1, inserted: 1, duplicates: 0, rejected: [], server_max_seq: 0 };
      },
    };
    const r1 = await runUploadWorker({ store, sink, now: () => 0 });
    expect(r1.failed).toBe(true);
    expect(r1.remaining.dead).toBe(1);
    const r2 = await runUploadWorker({ store, sink, now: () => 0 });
    expect(r2.uploaded).toBe(2);
    expect(r2.remaining).toEqual({ batches: 0, records: 0, dead: 1 });
  });
});
