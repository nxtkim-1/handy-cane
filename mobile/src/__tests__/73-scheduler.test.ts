import { PULL_EVERY_MS, SyncScheduler, UPLOAD_EVERY_MS, syncStatusLines } from '../sync/scheduler';
import { fmtAgo } from '../ui/format';

beforeEach(() => { jest.useFakeTimers(); });
afterEach(() => { jest.useRealTimers(); });

function make(over: Partial<{ pull: () => Promise<void>; configured: boolean }> = {}) {
  const calls = { upload: 0, pull: 0, states: [] as string[] };
  const deps = {
    upload: async () => { calls.upload++; },
    pull: over.pull ?? (async () => { calls.pull++; }),
    caneConfigured: () => over.configured ?? true,
    onCaneState: (s: string) => { calls.states.push(s); },
  };
  return { s: new SyncScheduler(deps), calls };
}

test('uploads every 30 s and pulls every 60 s, with an upload right after each pull', async () => {
  const { s, calls } = make();
  s.start();
  await jest.advanceTimersByTimeAsync(UPLOAD_EVERY_MS);
  expect(calls).toMatchObject({ upload: 1, pull: 0 });
  await jest.advanceTimersByTimeAsync(UPLOAD_EVERY_MS); // t = 60 s: upload tick + pull tick (+ upload after pull)
  expect(calls.pull).toBe(1);
  expect(calls.upload).toBeGreaterThanOrEqual(3);
  s.stop();
});

test('stop() cancels both timers; start() twice does not double them', async () => {
  const { s, calls } = make();
  s.start();
  s.start();
  await jest.advanceTimersByTimeAsync(UPLOAD_EVERY_MS);
  expect(calls.upload).toBe(1);
  s.stop();
  expect(s.running).toBe(false);
  await jest.advanceTimersByTimeAsync(10 * PULL_EVERY_MS);
  expect(calls.upload).toBe(1);
  expect(calls.pull).toBe(0);
});

test('no cane address: never pulls automatically, still uploads', async () => {
  const { s, calls } = make({ configured: false });
  s.start();
  await jest.advanceTimersByTimeAsync(3 * PULL_EVERY_MS);
  expect(calls.pull).toBe(0);
  expect(calls.upload).toBeGreaterThanOrEqual(6);
  s.stop();
});

test('after a failed pull, automatic pulls pause and the cane shows as unreachable (no error spam)', async () => {
  let n = 0;
  const { s, calls } = make({ pull: async () => { n++; throw new Error('timeout'); } });
  s.start();
  await jest.advanceTimersByTimeAsync(5 * PULL_EVERY_MS);
  expect(n).toBe(1);
  expect(s.caneState).toBe('unreachable');
  expect(calls.states).toEqual(['unreachable']);
  s.stop();
});

test('Sync now after a failure works and re-enables automatic pulls', async () => {
  let fail = true;
  const { s, calls } = make({ pull: async () => { if (fail) throw new Error('down'); } });
  expect((await s.pullNow()).ok).toBe(false);
  fail = false;
  expect((await s.pullNow()).ok).toBe(true);
  expect(s.caneState).toBe('ok');
  expect(calls.states).toEqual(['unreachable', 'ok']);
  s.start();
  await jest.advanceTimersByTimeAsync(PULL_EVERY_MS);
  expect(s.caneState).toBe('ok');
  s.stop();
});

test('a slow upload is not started twice', async () => {
  let running = 0;
  let max = 0;
  let release: () => void = () => {};
  const s = new SyncScheduler({
    caneConfigured: () => false,
    pull: async () => {},
    upload: () => new Promise<void>((res) => {
      running++; max = Math.max(max, running);
      release = () => { running--; res(); };
    }),
  });
  const a = s.uploadNow();
  const b = s.uploadNow();
  release();
  await Promise.all([a, b]);
  expect(max).toBe(1);
});

test('an upload that throws does not stop the timer', async () => {
  let n = 0;
  const s = new SyncScheduler({
    caneConfigured: () => false, pull: async () => {},
    upload: async () => { n++; throw new Error('offline'); },
  });
  s.start();
  await jest.advanceTimersByTimeAsync(3 * UPLOAD_EVERY_MS);
  expect(n).toBe(3);
  s.stop();
});

describe('status lines', () => {
  const now = Date.UTC(2026, 10, 8, 12, 0, 0);
  test('last synced, waiting and unreachable', () => {
    expect(syncStatusLines({ lastSyncMs: now - 120_000, waitingToUpload: 0, caneState: 'ok', caneConfigured: true, now }, fmtAgo))
      .toEqual(['Last synced 2 min ago']);
    expect(syncStatusLines({ lastSyncMs: null, waitingToUpload: 12, caneState: 'unreachable', caneConfigured: true, now }, fmtAgo))
      .toEqual(['Not synced yet', 'Waiting to upload: 12 records', 'Cane not reachable']);
    expect(syncStatusLines({ lastSyncMs: now, waitingToUpload: 0, caneState: 'unreachable', caneConfigured: false, now }, fmtAgo))
      .toEqual(['Last synced just now']);
  });
});
