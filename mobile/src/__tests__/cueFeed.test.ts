import { CueFeed } from '../cues/CueFeed';
import { CUE_KEYS, mapCue } from '../cues/cueMap';

describe('mapCue', () => {
  test('cue:<key> for the five approved keys', () => {
    for (const k of ['dropped', 'ask_ok', 'help', 'cancelled', 'sos']) expect(mapCue(`cue:${k}`)).toBe(k);
    expect([...CUE_KEYS]).toEqual(['dropped', 'ask_ok', 'help', 'cancelled', 'sos']);
  });
  test('legacy fallbacks', () => {
    expect(mapCue('cane_down')).toBe('dropped');
    expect(mapCue('alert')).toBe('help');
    expect(mapCue('flow_cancelled')).toBe('cancelled');
  });
  test('unknown and empty are null', () => {
    expect(mapCue('')).toBeNull();
    expect(mapCue('cue:nope')).toBeNull();
    expect(mapCue('cue:')).toBeNull();
    expect(mapCue('battery_low')).toBeNull();
    expect(mapCue('constructor')).toBeNull();
  });
});

type Ev = { seq: number; ts: number; type: string };

function setup() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  let events: Ev[] = [];
  let failNext = false;
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith('/pair')) {
      return new Response('{}', { status: 200, headers: { 'set-cookie': 'cane_session=abc123; Path=/; HttpOnly' } });
    }
    if (failNext) { failNext = false; throw new Error('network down'); }
    const since = Number(new URL(url).searchParams.get('since'));
    return new Response(
      JSON.stringify({ device: 'cane', time_quality: 'ok', events: events.filter((e) => e.seq > since) }),
      { status: 200 },
    );
  }) as unknown as typeof fetch;
  const played: string[] = [];
  const player = { play: (k: string) => { played.push(k); } };
  const feed = new CueFeed({ baseUrl: 'http://cane.local:8080/', pairCode: '123456', fetchImpl, player });
  return { feed, calls, played, setEvents: (e: Ev[]) => (events = e), failOnce: () => (failNext = true) };
}

describe('CueFeed', () => {
  let warn: jest.SpyInstance;
  beforeEach(() => { warn = jest.spyOn(console, 'warn').mockImplementation(() => {}); });
  afterEach(() => warn.mockRestore());

  test('first poll plays nothing; later poll plays new events in seq order, skipping unknown', async () => {
    const t = setup();
    t.setEvents([{ seq: 1, ts: 1, type: 'cane_down' }, { seq: 2, ts: 2, type: 'alert' }]);
    await t.feed.poll();
    expect(t.played).toEqual([]);
    t.setEvents([
      { seq: 1, ts: 1, type: 'cane_down' },
      { seq: 2, ts: 2, type: 'alert' },
      { seq: 5, ts: 5, type: 'cue:sos' },
      { seq: 3, ts: 3, type: 'cue:ask_ok' },
      { seq: 4, ts: 4, type: 'battery_low' },
      { seq: 6, ts: 6, type: 'flow_cancelled' },
    ]);
    await t.feed.poll();
    expect(t.played).toEqual(['ask_ok', 'sos', 'cancelled']);
    await t.feed.poll();
    expect(t.played).toEqual(['ask_ok', 'sos', 'cancelled']); // no replay
  });

  test('legacy twin of a cue event does not play twice; legacy-only event still plays', async () => {
    const t = setup();
    await t.feed.poll(); // baseline
    // new firmware: cue:dropped immediately followed by legacy cane_down
    t.setEvents([{ seq: 1, ts: 1, type: 'cue:dropped' }, { seq: 2, ts: 2, type: 'cane_down' }]);
    await t.feed.poll();
    expect(t.played).toEqual(['dropped']);
    // old firmware path: legacy event alone still plays
    t.setEvents([
      { seq: 1, ts: 1, type: 'cue:dropped' },
      { seq: 2, ts: 2, type: 'cane_down' },
      { seq: 9, ts: 9, type: 'cane_down' },
    ]);
    await t.feed.poll();
    expect(t.played).toEqual(['dropped', 'dropped']);
  });

  test('poll failure does not crash or advance the cursor', async () => {
    const t = setup();
    t.setEvents([{ seq: 1, ts: 1, type: 'alert' }]);
    await t.feed.poll(); // cursor -> 1
    t.setEvents([{ seq: 1, ts: 1, type: 'alert' }, { seq: 2, ts: 2, type: 'cue:help' }]);
    t.failOnce();
    await expect(t.feed.poll()).resolves.toBeUndefined();
    expect(warn).toHaveBeenCalledTimes(1);
    expect(t.played).toEqual([]);
    await t.feed.poll();
    expect(t.played).toEqual(['help']);
    expect(t.calls[t.calls.length - 1].url).toContain('since=1');
  });

  test('pair() posts the code once and the cookie is sent on polls', async () => {
    const t = setup();
    await t.feed.poll();
    await t.feed.poll();
    const pairs = t.calls.filter((c) => c.url.endsWith('/pair'));
    expect(pairs).toHaveLength(1);
    expect(pairs[0].url).toBe('http://cane.local:8080/pair');
    expect(pairs[0].init?.method).toBe('POST');
    expect(JSON.parse(pairs[0].init?.body as string)).toEqual({ code: '123456' });
    const polls = t.calls.filter((c) => c.url.includes('/events'));
    expect(polls).toHaveLength(2);
    for (const p of polls) expect((p.init?.headers as Record<string, string>).Cookie).toBe('cane_session=abc123');
  });
});
