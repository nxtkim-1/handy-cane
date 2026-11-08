import type {
  CaneEventRecord, CaneInfo, CaneRecord, LiveSample, MinuteRecord, PullPage,
} from '../types';
import type { CaneTransport } from './CaneTransport';

export interface MockOptions {
  deviceId?: string;
  /** Number of minutes of walking history on the "cane". */
  minutes?: number;
  /** Wall-clock end of the history (ms). Default now. */
  endMs?: number;
  /** Minute index after which a potential-fall event is recorded; 0 for none. */
  fallAtMinute?: number;
  /** Make the n-th call to pull() throw (simulates a disconnect). */
  failPullOnCall?: number;
  /** Make the n-th call to ack() throw. */
  failAckOnCall?: number;
}

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** Simulated cane: walking minutes with a rhythm and one potential fall. */
export class MockCaneTransport implements CaneTransport {
  readonly deviceId: string;
  records: CaneRecord[] = [];
  ackedUpTo = 0;
  timeSyncs: number[] = [];
  private pullCalls = 0;
  private ackCalls = 0;
  private alertCbs: ((e: CaneEventRecord) => void)[] = [];
  private liveTick = 0;

  constructor(private opts: MockOptions = {}) {
    this.deviceId = opts.deviceId ?? 'cane-sim1';
    this.build();
  }

  private build() {
    const minutes = this.opts.minutes ?? 180;
    const end = this.opts.endMs ?? Date.now();
    const start = end - minutes * 60_000;
    const r = rng(42);
    const bootId = '00000000-0000-4000-8000-000000000001';
    let seq = 0;
    const fallAt = this.opts.fallAtMinute ?? Math.floor(minutes * 0.6);
    for (let i = 0; i < minutes; i++) {
      const ts = new Date(start + i * 60_000).toISOString().replace(/\.\d+Z$/, 'Z');
      const walking = Math.sin(i / 9) > -0.2 ? r() > 0.15 : r() > 0.9;
      const strikes = walking ? 30 + Math.floor(r() * 25) : Math.floor(r() * 3);
      const active = walking ? 35 + Math.floor(r() * 22) : Math.floor(r() * 4);
      const m: MinuteRecord = {
        type: 'minute', seq: ++seq, boot_id: bootId, ts, time_quality: 'corrected',
        n_samples: 2990 + Math.floor(r() * 10),
        mag_mean: 1.0 + r() * 0.03, mag_std: 0.02 + r() * 0.1, mag_max: 1.2 + r() * 0.8,
        dyn_mean: 0.01 + r() * 0.05, active_s: active, strike_count: strikes,
        strike_iv_mean: strikes >= 10 ? 1.0 + r() * 0.2 : null,
        strike_iv_cv: strikes >= 10 ? 0.08 + r() * 0.1 : null,
        upright_s: 60, flat_s: 0, max_impact_g: 1.2 + r() * 0.8,
      };
      this.records.push(m);
      if (fallAt > 0 && i === fallAt) {
        this.records.push({
          type: 'event', seq: ++seq, event_id: '0b5f7a1c-3c9e-4d2a-9f11-8e6d2b4c7a90',
          boot_id: bootId, ts, time_quality: 'corrected', kind: 'potential_fall',
          outcome: 'cancelled_by_user', confidence: 0.62, peak_g: 4.1, tilt_deg: 84,
          still_s: 11.5, raw_snippet_b64: null,
        });
      }
    }
  }

  async connect(): Promise<CaneInfo> {
    const last = this.records.length ? this.records[this.records.length - 1].seq : 0;
    return {
      device_id: this.deviceId, fw_version: 'mock-0.1', last_seq: last,
      unsynced_count: this.records.filter((r) => r.seq > this.ackedUpTo).length,
      sensor_model: 'ADXL345 (simulated)',
    };
  }

  async timeSync(phoneUtcMs: number): Promise<void> {
    this.timeSyncs.push(phoneUtcMs);
  }

  async pull(afterSeq: number, limit: number): Promise<PullPage> {
    this.pullCalls++;
    if (this.opts.failPullOnCall === this.pullCalls) throw new Error('Mock cane disconnected');
    const rows = this.records.filter((r) => r.seq > afterSeq).slice(0, limit);
    const nextCursor = rows.length ? rows[rows.length - 1].seq : afterSeq;
    const more = this.records.some((r) => r.seq > nextCursor);
    return { records: rows, nextCursor, more };
  }

  async ack(upToSeq: number): Promise<void> {
    this.ackCalls++;
    if (this.opts.failAckOnCall === this.ackCalls) throw new Error('Mock ack lost');
    this.ackedUpTo = Math.max(this.ackedUpTo, upToSeq);
  }

  onAlert(cb: (e: CaneEventRecord) => void): () => void {
    this.alertCbs.push(cb);
    return () => {
      this.alertCbs = this.alertCbs.filter((c) => c !== cb);
    };
  }

  /** Demo helper: raise a potential fall now. */
  triggerFall(): CaneEventRecord {
    const seq = (this.records[this.records.length - 1]?.seq ?? 0) + 1;
    const e: CaneEventRecord = {
      type: 'event', seq, event_id: `evt-${seq}`, boot_id: 'mock-boot', ts: new Date().toISOString(),
      time_quality: 'corrected', kind: 'potential_fall', outcome: 'unanswered', confidence: 0.7,
      peak_g: 4.4, tilt_deg: 80, still_s: 12, raw_snippet_b64: null,
    };
    this.records.push(e);
    this.alertCbs.forEach((c) => c(e));
    return e;
  }

  async live(): Promise<LiveSample> {
    this.liveTick++;
    const walking = Math.sin(this.liveTick / 8) > -0.3;
    const dyn = walking ? 0.3 * Math.abs(Math.sin(this.liveTick)) : 0.01;
    return {
      ts: new Date().toISOString(),
      mag: 1 + dyn,
      dyn,
      state: walking ? 'walking' : 'idle',
      strikes_last_10s: walking ? 9 : 0,
    };
  }

  async disconnect(): Promise<void> {}
}
