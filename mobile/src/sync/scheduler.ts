/**
 * Foreground sync timers (MASTER 15.2: sync while the app is open, background sync is future scope).
 *  - the upload worker runs every 30 s (it applies its own backoff) and right after each successful pull;
 *  - a pull from the cane is tried every 60 s when a cane address is set, but only if the last pull
 *    succeeded or none has run yet. After a failure the cane is shown as "not reachable" and automatic
 *    pulls pause (no error spam) until the user taps Sync now, which resets the state.
 * No React Native imports: the timers and the work are injected, so this is tested with fake timers.
 */
export const UPLOAD_EVERY_MS = 30_000;
export const PULL_EVERY_MS = 60_000;

export type CaneState = 'unknown' | 'ok' | 'unreachable';

export interface SchedulerDeps {
  /** Run the upload worker once. Must not throw for ordinary failures (the worker keeps its own queue). */
  upload(): Promise<void>;
  /** Pull from the cane; rejects when the cane cannot be reached. */
  pull(): Promise<void>;
  caneConfigured(): boolean;
  onCaneState?(s: CaneState): void;
}

export class SyncScheduler {
  private uploadTimer: ReturnType<typeof setInterval> | null = null;
  private pullTimer: ReturnType<typeof setInterval> | null = null;
  private uploading = false;
  private pulling = false;
  caneState: CaneState = 'unknown';

  constructor(private deps: SchedulerDeps) {}

  get running(): boolean { return this.uploadTimer !== null; }

  start(): void {
    if (this.running) return;
    this.uploadTimer = setInterval(() => { void this.uploadNow(); }, UPLOAD_EVERY_MS);
    this.pullTimer = setInterval(() => { void this.autoPull(); }, PULL_EVERY_MS);
  }

  stop(): void {
    if (this.uploadTimer) clearInterval(this.uploadTimer);
    if (this.pullTimer) clearInterval(this.pullTimer);
    this.uploadTimer = null;
    this.pullTimer = null;
  }

  async uploadNow(): Promise<void> {
    if (this.uploading) return;
    this.uploading = true;
    try {
      await this.deps.upload();
    } catch { /* the queue is persistent; the next tick retries */ } finally {
      this.uploading = false;
    }
  }

  /** The timer path: skips when there is no cane address or the last pull failed. */
  private async autoPull(): Promise<void> {
    if (!this.deps.caneConfigured() || this.caneState === 'unreachable') return;
    await this.pullNow();
  }

  /** Pull once (also used by the Sync now button). Returns whether it worked. */
  async pullNow(): Promise<{ ok: boolean; error?: unknown }> {
    if (this.pulling) return { ok: this.caneState !== 'unreachable' };
    this.pulling = true;
    try {
      await this.deps.pull();
      this.setCane('ok');
    } catch (error) {
      this.setCane('unreachable');
      return { ok: false, error };
    } finally {
      this.pulling = false;
    }
    await this.uploadNow();
    return { ok: true };
  }

  private setCane(s: CaneState) {
    this.caneState = s;
    this.deps.onCaneState?.(s);
  }
}

/** The one status line shown on Home and Cane. */
export function syncStatusLines(s: {
  lastSyncMs: number | null;
  waitingToUpload: number;
  caneState: CaneState;
  caneConfigured: boolean;
  now?: number;
}, ago: (ms: number | null, now?: number) => string): string[] {
  const lines: string[] = [];
  lines.push(s.lastSyncMs === null ? 'Not synced yet' : `Last synced ${ago(s.lastSyncMs, s.now)}`);
  if (s.waitingToUpload > 0) lines.push(`Waiting to upload: ${s.waitingToUpload} records`);
  if (s.caneConfigured && s.caneState === 'unreachable') lines.push('Cane not reachable');
  return lines;
}
