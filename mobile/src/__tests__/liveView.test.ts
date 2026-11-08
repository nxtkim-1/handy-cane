import { CaneHttpError } from '../comm/HttpCaneTransport';
import type { CaneTransport } from '../comm/CaneTransport';
import { startLivePoller } from '../comm/liveView';
import { MockCaneTransport } from '../comm/MockCaneTransport';
import type { LiveSample } from '../types';

beforeEach(() => { jest.useFakeTimers(); });
afterEach(() => { jest.useRealTimers(); });

const sample: LiveSample = { ts: 't', mag: 1, dyn: 0.1, state: 'idle', strikes_last_10s: 0 };

function cb() {
  return { samples: [] as LiveSample[], errors: [] as string[], gone: 0 };
}
function handlers(c: ReturnType<typeof cb>) {
  return { onSample: (s: LiveSample) => c.samples.push(s), onError: (m: string) => c.errors.push(m), onUnavailable: () => { c.gone++; } };
}

test('a transport with no live() reports unavailable once and does not poll', async () => {
  const t = { } as CaneTransport;
  const c = cb();
  startLivePoller(t, handlers(c));
  await jest.advanceTimersByTimeAsync(10_000);
  expect(c.gone).toBe(1);
  expect(c.errors).toEqual([]);
});

test('HTTP 404 means unavailable: reported once, then polling stops', async () => {
  let calls = 0;
  const t = { live: async () => { calls++; throw new CaneHttpError(404, 'nope'); } } as unknown as CaneTransport;
  const c = cb();
  startLivePoller(t, handlers(c));
  await jest.advanceTimersByTimeAsync(10_000);
  expect(c.gone).toBe(1);
  expect(calls).toBe(1);
  expect(c.errors).toEqual([]);
});

test('other failures are errors and polling carries on; samples flow when it recovers', async () => {
  let n = 0;
  const t = {
    live: async () => { n++; if (n === 1) throw new Error('timeout'); return sample; },
  } as unknown as CaneTransport;
  const c = cb();
  const stop = startLivePoller(t, handlers(c));
  await jest.advanceTimersByTimeAsync(2500);
  expect(c.errors).toEqual(['timeout']);
  expect(c.samples.length).toBeGreaterThanOrEqual(2);
  expect(c.gone).toBe(0);
  stop();
  const before = n;
  await jest.advanceTimersByTimeAsync(5000);
  expect(n).toBe(before);
});

test('the mock cane has a live view', async () => {
  const c = cb();
  const stop = startLivePoller(new MockCaneTransport({ minutes: 5 }), handlers(c));
  await jest.advanceTimersByTimeAsync(1100);
  expect(c.samples.length).toBeGreaterThan(0);
  stop();
});
