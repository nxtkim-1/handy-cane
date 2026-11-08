import { MockCaneTransport } from '../comm/MockCaneTransport';
import { MemoryStore } from '../db/MemoryStore';
import { runPullSync, META_LAST_SYNC } from '../sync/pullSync';

let n = 0;
const newId = () => `batch-${++n}`;

describe('pull sync (MASTER 7.4)', () => {
  test('pulls everything in pages, acks after write, records last sync', async () => {
    const cane = new MockCaneTransport({ minutes: 50 });
    const store = new MemoryStore();
    const res = await runPullSync({ transport: cane, store, pageLimit: 20, newId, now: () => 1000 });
    const total = cane.records.length;
    expect(res.inserted).toBe(total);
    expect(res.pages).toBe(Math.ceil(total / 20));
    expect(await store.getCursor(cane.deviceId)).toBe(cane.records[total - 1].seq);
    expect(cane.ackedUpTo).toBe(cane.records[total - 1].seq);
    expect(cane.timeSyncs).toEqual([1000]);
    expect(await store.getMeta(META_LAST_SYNC)).toBe('1000');
  });

  test('interrupted transfer resumes from last committed page with no loss or dupes', async () => {
    const cane = new MockCaneTransport({ minutes: 50, failPullOnCall: 3 });
    const store = new MemoryStore();
    await expect(runPullSync({ transport: cane, store, pageLimit: 10, newId })).rejects.toThrow('disconnected');
    const cursorAfterCrash = await store.getCursor(cane.deviceId);
    expect(cursorAfterCrash).toBe(20);
    expect(await store.countRecords(cane.deviceId)).toBe(20);

    const res = await runPullSync({ transport: cane, store, pageLimit: 10, newId });
    expect(res.inserted).toBe(cane.records.length - 20);
    expect(res.duplicates).toBe(0);
    expect(await store.countRecords(cane.deviceId)).toBe(cane.records.length);
  });

  test('duplicates (e.g. pages re-sent after a lost ack/cursor) are ignored', async () => {
    const cane = new MockCaneTransport({ minutes: 30 });
    const store = new MemoryStore();
    await runPullSync({ transport: cane, store, pageLimit: 100, newId });
    // Simulate lost cursor: a second phone state replaying from 0 into same store.
    const page = await cane.pull(0, 100);
    const r = await store.applyPage({
      deviceId: cane.deviceId, fwVersion: 'x', records: page.records, nextCursor: 0, batchId: 'replay',
    });
    expect(r.inserted).toBe(0);
    expect(r.duplicates).toBe(page.records.length);
    expect(await store.countRecords(cane.deviceId)).toBe(cane.records.length);
    // cursor never moves backwards
    expect(await store.getCursor(cane.deviceId)).toBe(cane.records[cane.records.length - 1].seq);
    // and no empty upload batch for an all-duplicate page
    expect((await store.queueStats()).records).toBe(cane.records.length);
  });

  test('ack failure after durable write loses nothing; next sync continues', async () => {
    const cane = new MockCaneTransport({ minutes: 20, failAckOnCall: 1 });
    const store = new MemoryStore();
    await expect(runPullSync({ transport: cane, store, pageLimit: 10, newId })).rejects.toThrow('ack');
    expect(cane.ackedUpTo).toBe(0);
    expect(await store.getCursor(cane.deviceId)).toBe(10);
    const res = await runPullSync({ transport: cane, store, pageLimit: 10, newId });
    expect(await store.countRecords(cane.deviceId)).toBe(cane.records.length);
    expect(res.duplicates).toBe(0);
    expect(cane.ackedUpTo).toBe(cane.records[cane.records.length - 1].seq);
  });

  test('page write is atomic: failed write advances neither cursor nor queue, and no ack is sent', async () => {
    const cane = new MockCaneTransport({ minutes: 20 });
    const store = new MemoryStore();
    store.failNextApply = true;
    await expect(runPullSync({ transport: cane, store, pageLimit: 10, newId })).rejects.toThrow('storage');
    expect(await store.getCursor(cane.deviceId)).toBe(0);
    expect(await store.countRecords(cane.deviceId)).toBe(0);
    expect((await store.queueStats()).batches).toBe(0);
    expect(cane.ackedUpTo).toBe(0);
  });

  test('each page produces one upload batch', async () => {
    const cane = new MockCaneTransport({ minutes: 25, fallAtMinute: 0 });
    const store = new MemoryStore();
    await runPullSync({ transport: cane, store, pageLimit: 10, newId });
    expect((await store.queueStats()).batches).toBe(3);
  });
});
