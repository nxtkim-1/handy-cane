import { cuePlayer, type CuePlaying } from './CuePlayer';
import { mapCue } from './cueMap';

export interface CueFeedOptions {
  baseUrl: string;
  pairCode: string;
  fetchImpl?: typeof fetch;
  player?: CuePlaying;
}

interface FeedEvent { seq: number; ts?: number; type: string }

export class CueFeed {
  private readonly baseUrl: string;
  private readonly pairCode: string;
  private readonly fetchImpl: typeof fetch;
  private readonly player: CuePlaying;
  private cookie: string | null = null;
  private cursor: number | null = null; // null until first successful poll
  private recentCue: Record<string, number> = {}; // cue key -> last seq it played, for legacy dedupe
  private timer: ReturnType<typeof setInterval> | null = null;
  private polling = false;
  private warned = false;

  constructor(o: CueFeedOptions) {
    this.baseUrl = o.baseUrl.replace(/\/+$/, '');
    this.pairCode = o.pairCode;
    this.fetchImpl = o.fetchImpl ?? ((...a) => fetch(...a));
    this.player = o.player ?? cuePlayer;
  }

  /** POST /pair once; captures the cane_session cookie. Throws on failure. */
  async pair(): Promise<void> {
    if (this.cookie) return;
    const res = await this.fetchImpl(`${this.baseUrl}/pair`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: this.pairCode }),
    });
    if (!res.ok) throw new Error(`pair failed (HTTP ${res.status})`);
    const raw = res.headers.get('set-cookie') ?? '';
    const m = /(cane_session=[^;,\s]+)/.exec(raw);
    if (!m) throw new Error('pair response had no cane_session cookie');
    this.cookie = m[1];
  }

  start(intervalMs = 1000): void {
    if (this.timer) return;
    void this.poll();
    this.timer = setInterval(() => void this.poll(), intervalMs);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  /** One poll cycle; never throws. */
  async poll(): Promise<void> {
    if (this.polling) return;
    this.polling = true;
    try {
      await this.pair();
      const since = this.cursor ?? 0;
      const res = await this.fetchImpl(`${this.baseUrl}/events?since=${since}`, {
        headers: { Cookie: this.cookie as string },
      });
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) this.cookie = null; // re-pair next time
        throw new Error(`events failed (HTTP ${res.status})`);
      }
      const body = (await res.json()) as { events?: FeedEvent[] };
      const events = [...(body.events ?? [])].sort((a, b) => a.seq - b.seq);
      const first = this.cursor === null;
      let max = this.cursor ?? 0;
      for (const ev of events) {
        if (ev.seq <= (this.cursor ?? 0) && !first) continue;
        if (ev.seq > max) max = ev.seq;
        if (first) continue; // history: mark only
        let key = mapCue(ev.type);
        if (ev.type.startsWith('cue:')) {
          if (key) this.recentCue[key] = ev.seq; // remember: legacy twin is already covered
        } else if (key && this.recentCue[key] !== undefined && ev.seq - this.recentCue[key] < 5) {
          key = null; // firmware logs cue:<key> right before its legacy twin; never play twice
        }
        if (key) this.player.play(key, { baseUrl: this.baseUrl, cookie: this.cookie as string });
      }
      this.cursor = max;
      this.warned = false;
    } catch (e) {
      if (!this.warned) {
        this.warned = true;
        console.warn('[cues] feed poll failed, will retry:', e instanceof Error ? e.message : e);
      }
    } finally {
      this.polling = false;
    }
  }
}
