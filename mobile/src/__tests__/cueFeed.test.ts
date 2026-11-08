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

  describe('dedupe and reconnect', () => {
    test('SOS hold: cue:sos, cue:help, alert plays sos and help once each', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:sos' }, { seq: 2, ts: 2, type: 'cue:help' }, { seq: 3, ts: 3, type: 'alert' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['sos', 'help']);
    });
    test('all five cue orders play exactly once per incident', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([
        { seq: 1, ts: 1, type: 'cue:dropped' }, { seq: 2, ts: 2, type: 'cane_down' },
        { seq: 3, ts: 3, type: 'cue:ask_ok' },
        { seq: 4, ts: 4, type: 'cue:help' }, { seq: 5, ts: 5, type: 'alert' },
        { seq: 6, ts: 6, type: 'cue:cancelled' }, { seq: 7, ts: 7, type: 'flow_cancelled' },
        { seq: 8, ts: 8, type: 'cue:sos' }, { seq: 9, ts: 9, type: 'cue:help' }, { seq: 10, ts: 10, type: 'alert' },
      ]);
      await t.feed.poll();
      expect(t.played).toEqual(['dropped', 'ask_ok', 'help', 'cancelled', 'sos', 'help']);
    });
    test('same-key incidents both play, even within 5 seq and across polls', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([
        { seq: 1, ts: 1, type: 'cue:help' }, { seq: 2, ts: 2, type: 'alert' },
        { seq: 3, ts: 3, type: 'cue:help' }, { seq: 4, ts: 4, type: 'alert' },
      ]);
      await t.feed.poll();
      expect(t.played).toEqual(['help', 'help']);
      t.setEvents([
        { seq: 1, ts: 1, type: 'cue:help' }, { seq: 2, ts: 2, type: 'alert' },
        { seq: 3, ts: 3, type: 'cue:help' }, { seq: 4, ts: 4, type: 'alert' },
        { seq: 20, ts: 20, type: 'cue:help' }, { seq: 21, ts: 21, type: 'alert' },
      ]);
      await t.feed.poll();
      expect(t.played).toEqual(['help', 'help', 'help']);
    });
    test('a second legacy-only event after a consumed twin still plays', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:help' }, { seq: 2, ts: 2, type: 'alert' }, { seq: 3, ts: 3, type: 'alert' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['help', 'help']);
    });
    test('legacy event arriving before its cue twin plays once', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cane_down' }, { seq: 2, ts: 2, type: 'cue:dropped' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['dropped']);
    });
    test('twin split across polls is still suppressed, including across the baseline boundary', async () => {
      const t = setup();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:help' }]);
      await t.feed.poll(); // baseline sees the cue
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:help' }, { seq: 2, ts: 2, type: 'alert' }]);
      await t.feed.poll();
      expect(t.played).toEqual([]);
    });
    test('history larger than one page (200) is never replayed', async () => {
      const t = setup();
      const hist: Ev[] = Array.from({ length: 250 }, (_, i) => ({ seq: i + 1, ts: i, type: 'cue:help' }));
      t.setEvents(hist.slice(0, 200)); // Pi returns at most 200 rows per poll
      const page = (since: number) => hist.filter((e) => e.seq > since).slice(0, 200);
      (t as any).setEvents(page(0));
      await t.feed.poll();
      (t as any).setEvents(page(200));
      await t.feed.poll();
      expect(t.played).toEqual([]);
    });
    test('401 clears the session and re-pairs; cursor kept, no replay', async () => {
      const calls: string[] = [];
      let reject = false;
      const fetchImpl = (async (url: string) => {
        calls.push(url);
        if (url.endsWith('/pair')) return new Response('{}', { status: 200, headers: { 'set-cookie': 'cane_session=abc; Path=/' } });
        if (reject) { reject = false; return new Response('{}', { status: 401 }); }
        return new Response(JSON.stringify({ events: [{ seq: 1, ts: 1, type: 'cue:sos' }].filter((e) => e.seq > Number(new URL(url).searchParams.get('since'))) }), { status: 200 });
      }) as unknown as typeof fetch;
      const played: string[] = [];
      const feed = new CueFeed({ baseUrl: 'http://c', pairCode: '1', fetchImpl, player: { play: (k: string) => { played.push(k); } } });
      await feed.poll();
      reject = true;
      await feed.poll(); // 401
      await feed.poll(); // re-pair + poll
      expect(calls.filter((c) => c.endsWith('/pair'))).toHaveLength(2);
      expect(played).toEqual([]);
    });
  });
});
