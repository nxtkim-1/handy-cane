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
  let fw: string | undefined;
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith('/pair')) {
      return new Response('{"paired":true,"session":"tok123"}', { status: 200, headers: { 'set-cookie': 'cane_session=abc123; Path=/; HttpOnly' } });
    }
    if (failNext) { failNext = false; throw new Error('network down'); }
    const since = Number(new URL(url).searchParams.get('since'));
    return new Response(
      JSON.stringify({ device: 'cane', time_quality: 'ok', ...(fw !== undefined ? { fw } : {}), events: events.filter((e) => e.seq > since) }),
      { status: 200 },
    );
  }) as unknown as typeof fetch;
  const played: string[] = [];
  const player = { play: (k: string) => { played.push(k); } };
  const feed = new CueFeed({ baseUrl: 'http://cane.local:8080/', pairCode: '123456', fetchImpl, player });
  return { feed, calls, played, setEvents: (e: Ev[]) => (events = e), failOnce: () => (failNext = true), setFw: (v?: string) => (fw = v) };
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
    expect(t.played).toEqual(['ask_ok', 'sos']); // flow_cancelled is legacy and a cue: was seen: silent
    await t.feed.poll();
    expect(t.played).toEqual(['ask_ok', 'sos']); // no replay
  });

  test('legacy twin of a cue event does not play twice; legacy-only event is silent once a cue: was seen', async () => {
    const t = setup();
    await t.feed.poll(); // baseline
    // new firmware: cue:dropped immediately followed by legacy cane_down
    t.setEvents([{ seq: 1, ts: 1, type: 'cue:dropped' }, { seq: 2, ts: 2, type: 'cane_down' }]);
    await t.feed.poll();
    expect(t.played).toEqual(['dropped']);
    // new firmware: twinless legacy event (impact fall) stays silent
    t.setEvents([
      { seq: 1, ts: 1, type: 'cue:dropped' },
      { seq: 2, ts: 2, type: 'cane_down' },
      { seq: 9, ts: 9, type: 'cane_down' },
    ]);
    await t.feed.poll();
    expect(t.played).toEqual(['dropped']);
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

  test('pair() posts the code once and the bearer token is sent on polls', async () => {
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
    for (const p of polls) {
      const h = p.init?.headers as Record<string, string>;
      expect(h.Authorization).toBe('Bearer tok123');
      expect(h.Cookie).toBeUndefined();
    }
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
    test('a second legacy-only event after a cue: twin is silent (new firmware)', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:help' }, { seq: 2, ts: 2, type: 'alert' }, { seq: 3, ts: 3, type: 'alert' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['help']);
    });
    test('feed with "fw" never plays legacy cane_down even with zero cue: events', async () => {
      const t = setup();
      t.setFw('0.4.0');
      await t.feed.poll(); // empty baseline
      t.setEvents([{ seq: 1, ts: 1, type: 'cane_down' }, { seq: 2, ts: 2, type: 'alert' }, { seq: 3, ts: 3, type: 'flow_cancelled' }]);
      await t.feed.poll();
      expect(t.played).toEqual([]);
    });
    test('feed with "fw": legacy-only history then new impact cane_down stays silent', async () => {
      const t = setup();
      t.setFw('0.4.0');
      t.setEvents([{ seq: 1, ts: 1, type: 'cane_down' }]);
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cane_down' }, { seq: 9, ts: 9, type: 'cane_down' }]);
      await t.feed.poll();
      expect(t.played).toEqual([]);
    });
    test('feed with "fw" still plays cue: events', async () => {
      const t = setup();
      t.setFw('0.4.0');
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:help' }, { seq: 2, ts: 2, type: 'alert' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['help']);
    });
    test('empty "fw" is ignored: legacy behavior kept', async () => {
      const t = setup();
      t.setFw('');
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cane_down' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['dropped']);
    });
    test('old firmware (no cue: ever seen): impact cane_down plays dropped', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cane_down' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['dropped']);
    });
    test('new firmware: impact cane_down after any cue: event plays nothing', async () => {
      const t = setup();
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:ask_ok' }, { seq: 20, ts: 20, type: 'cane_down' }]);
      await t.feed.poll();
      expect(t.played).toEqual(['ask_ok']);
    });
    test('a cue: event seen only in baseline history still switches to new-firmware mode', async () => {
      const t = setup();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:help' }]);
      await t.feed.poll();
      t.setEvents([{ seq: 1, ts: 1, type: 'cue:help' }, { seq: 30, ts: 30, type: 'cane_down' }]);
      await t.feed.poll();
      expect(t.played).toEqual([]);
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
        if (url.endsWith('/pair')) return new Response('{"paired":true,"session":"tokabc"}', { status: 200 });
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

  describe('onStatus copy', () => {
    const mk = (fetchImpl: any, statuses: Array<string | null>) =>
      new CueFeed({ baseUrl: 'http://c', pairCode: '1', fetchImpl, player: { play: () => {} }, onStatus: (s: string | null) => { statuses.push(s); } } as any);
    beforeEach(() => { jest.spyOn(console, 'warn').mockImplementation(() => {}); });
    afterEach(() => { jest.restoreAllMocks(); });

    test('pair HTTP failure -> friendly pair copy', async () => {
      const st: Array<string | null> = [];
      await mk((async () => new Response('{}', { status: 403 })) as unknown as typeof fetch, st).poll();
      expect(st).toEqual(['Could not pair. Check the address and pairing code.']);
    });
    test('pair response without session token (cookie only) -> friendly pair copy', async () => {
      const st: Array<string | null> = [];
      await mk((async () => new Response('{}', { status: 200 })) as unknown as typeof fetch, st).poll();
      expect(st).toEqual(['Could not pair. Check the address and pairing code.']);
    });
    test('poll failure after pairing -> retry copy, then null on recovery', async () => {
      const st: Array<string | null> = [];
      let bad = true;
      const f = (async (url: string) => {
        if (url.endsWith('/pair')) return new Response('{"paired":true,"session":"tokabc"}', { status: 200 });
        return bad ? new Response('{}', { status: 500 }) : new Response('{"events":[]}', { status: 200 });
      }) as unknown as typeof fetch;
      const feed = mk(f, st);
      await feed.poll();
      bad = false;
      await feed.poll();
      expect(st).toEqual(['paired', 'Lost the cane feed. Retrying.', null]);
    });
    test('wrong/no token 401 -> one re-pair, then pair copy if re-pair fails', async () => {
      const st: Array<string | null> = [];
      const calls: string[] = [];
      let pairs = 0;
      const f = (async (url: string) => {
        calls.push(url);
        if (url.endsWith('/pair')) {
          pairs++;
          return pairs === 1 ? new Response('{"paired":true,"session":"t"}', { status: 200 }) : new Response('{}', { status: 403 });
        }
        return new Response('{}', { status: 401 });
      }) as unknown as typeof fetch;
      const feed = mk(f, st);
      await feed.poll(); // pair ok, events 401 -> token cleared
      await feed.poll(); // one re-pair, fails
      await feed.poll(); // still failing: no duplicate copy
      expect(calls.filter((c) => c.endsWith('/pair'))).toHaveLength(3);
      expect(st).toEqual(['paired', 'Lost the cane feed. Retrying.', 'Could not pair. Check the address and pairing code.']);
    });
    test('401 then successful re-pair uses the new token', async () => {
      const auth: string[] = [];
      let n = 0;
      const f = (async (url: string, init?: RequestInit) => {
        if (url.endsWith('/pair')) return new Response(`{"paired":true,"session":"t${++n}"}`, { status: 200 });
        auth.push((init?.headers as Record<string, string>).Authorization);
        return auth.length === 1 ? new Response('{}', { status: 401 }) : new Response('{"events":[]}', { status: 200 });
      }) as unknown as typeof fetch;
      const feed = mk(f, []);
      await feed.poll(); await feed.poll();
      expect(auth).toEqual(['Bearer t1', 'Bearer t2']);
    });
  });
});
