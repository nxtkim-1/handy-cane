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
  private pendingTwin: Record<string, number> = {}; // cue key -> seq of a cue: event whose legacy twin has not arrived yet
  private pendingCue: Record<string, number> = {}; // cue key -> seq of a legacy event that played; its cue: twin may follow
  private cueSeen = false; // true once any cue: event has been observed (even in history): firmware is new, legacy events never play
  private baselining = true; // true until a poll returns less than a full page (history is never replayed)
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
      const first = this.baselining;
      let max = this.cursor ?? 0;
      for (const ev of events) {
        if (ev.seq <= (this.cursor ?? 0)) continue;
        if (ev.seq > max) max = ev.seq;
        const key = mapCue(ev.type);
        if (!key) continue;
        const isCue = ev.type.startsWith('cue:');
        let play = !first; // history: mark only (but still track twins across the boundary)
        if (isCue) {
          const lg = this.pendingCue[key];
          if (lg !== undefined && ev.seq - lg <= 2) { play = false; delete this.pendingCue[key]; } // legacy came first
          else this.pendingTwin[key] = ev.seq;
        } else if (this.cueSeen) {
          play = false; // new firmware: cue: twins cover legacy events; twinless ones (impact cane_down) are intentionally silent
        } else {
          const c = this.pendingTwin[key];
          if (c !== undefined && ev.seq - c < 5) { play = false; delete this.pendingTwin[key]; } // twin consumed once
          else if (play) this.pendingCue[key] = ev.seq; // only legacy events that actually played
        }
        if (isCue) this.cueSeen = true;
        if (play) this.player.play(key, { baseUrl: this.baseUrl, cookie: this.cookie as string });
      }
      this.cursor = max;
      if (first) this.baselining = events.length >= 200; // Pi pages at 200 rows; keep marking until caught up
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
