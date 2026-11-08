import type { IngestBatch, IngestResponse } from '../types';
import type { ApiClient } from './ApiClient';
import { ApiError } from './ApiClient';
import type {
  Baseline, DailyMetric, EventItem, Overview, Patient, PatientListItem, Report, Tokens, User,
} from './types';
import { computeBaseline } from '../charts/trend';

const PATIENT: Patient = {
  patient_id: 'p-demo', display_name: 'Demo Patient', is_simulated: true, timezone: 'America/Toronto',
};
const PATIENT2: Patient = {
  patient_id: 'p-demo2', display_name: 'Second Demo Patient', is_simulated: true, timezone: 'America/Toronto',
};

export const DEMO_USERS: Record<string, User> = {
  'patient@demo': { user_id: 'u1', email: 'patient@demo', display_name: 'Demo Patient', role: 'patient', patient_ids: ['p-demo'] },
  'clinician@demo': { user_id: 'u2', email: 'clinician@demo', display_name: 'Dr. Demo', role: 'clinician', patient_ids: ['p-demo', 'p-demo2'] },
};

function isoDay(offsetFromToday: number, now: Date): string {
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - offsetFromToday));
  return d.toISOString().slice(0, 10);
}

/** 56 days: steady first weeks, gaps (invalid), then a gentle sustained decline. */
export function makeDailySeries(now: Date, seed = 1): DailyMetric[] {
  const out: DailyMetric[] = [];
  for (let i = 55; i >= 0; i--) {
    const idx = 55 - i;
    const invalid = idx % 11 === 6 || idx % 17 === 9;
    const wobble = Math.sin(idx * 1.7 + seed) * 6;
    const trend = idx > 40 ? -(idx - 40) * 1.6 : 0;
    const active = Math.round(64 + wobble + trend);
    out.push({
      day: isoDay(i, now),
      valid: !invalid,
      coverage_h: invalid ? 4.2 : 11.5,
      active_min: invalid ? null : active,
      strikes: invalid ? null : active * 38,
    });
  }
  return out;
}

export class MockApiClient implements ApiClient {
  private user: User | null = null;
  private eventList: EventItem[];
  private reportList: Report[];
  readonly ingested: IngestBatch[] = [];
  /** Test/demo hook: make ingest fail like a backend outage. */
  ingestDown = false;

  constructor(private now: () => Date = () => new Date()) {
    const t = now();
    this.eventList = [
      {
        event_id: 'e1', ts: new Date(t.getTime() - 3 * 3600_000).toISOString(), kind: 'potential_fall',
        outcome: 'cancelled_by_user', status: 'open', time_quality: 'corrected', dismiss_reason: null, note: null,
      },
      {
        event_id: 'e2', ts: new Date(t.getTime() - 5 * 86400_000).toISOString(), kind: 'potential_fall',
        outcome: 'escalated', status: 'open', time_quality: 'unsynced', dismiss_reason: null, note: null,
      },
      {
        event_id: 'e3', ts: new Date(t.getTime() - 9 * 86400_000).toISOString(), kind: 'help_request',
        outcome: 'escalated', status: 'dismissed', time_quality: 'synced',
        dismiss_reason: 'i_am_fine', note: 'Pressed by accident',
      },
    ];
    this.reportList = [
      {
        report_id: 'r1', period_start: isoDay(14, t), period_end: isoDay(1, t), status: 'generated',
        is_simulated: true,
        headline: 'Less cane-active time than your usual over the last two weeks.',
        sections: [
          { title: 'What we saw', body: 'Cane-active time was lower than your usual on most days since a week ago. Your usual is your median over your first 2 weeks.' },
          { title: 'Data completeness', body: 'Less data than usual: 3 days had too little cane data and are not counted. The cane may not have been used on those days.' },
          { title: 'Cane steps', body: 'Cane steps were about 15% lower than your usual. This may mean you walked without the cane.' },
        ],
      },
    ];
  }

  setTokens(_t: Tokens | null) {}

  async login(email: string, password: string) {
    const u = DEMO_USERS[email.trim().toLowerCase()];
    if (!u || password !== 'demo') throw new ApiError(401, 'invalid_credentials', 'Email or password is not right.');
    this.user = u;
    return { user: u, tokens: { access_token: 'mock', refresh_token: 'mock' } };
  }

  async me() {
    if (!this.user) throw new ApiError(401, 'unauthorized', 'Please sign in.');
    return this.user;
  }

  async patients(): Promise<PatientListItem[]> {
    return [
      { ...PATIENT, open_events: this.eventList.filter((e) => e.status === 'open').length, sustained_change: true, last_sync_at: new Date(this.now().getTime() - 3600_000).toISOString(), stale_sync: false },
      { ...PATIENT2, open_events: 0, sustained_change: false, last_sync_at: new Date(this.now().getTime() - 4 * 86400_000).toISOString(), stale_sync: true },
    ];
  }

  async overview(pid: string): Promise<Overview> {
    const p = pid === PATIENT2.patient_id ? PATIENT2 : PATIENT;
    const t = this.now();
    const days = makeDailySeries(t).filter((d) => d.valid).slice(-7);
    const vals = days.map((d) => d.active_min as number).sort((a, b) => a - b);
    return {
      patient: p,
      device: { device_id: 'cane-sim1', last_seen_at: new Date(t.getTime() - 3600_000).toISOString(), sensor_model: 'ADXL345 (simulated)', unsynced_hint: false },
      today: { day: isoDay(0, t), valid_so_far: false, coverage_h: 6.2, active_min: 38, strikes: 1210 },
      last_7_valid_days: { active_min_median: vals[Math.floor(vals.length / 2)] ?? null, valid_days: vals.length },
      open_events: this.eventList.filter((e) => e.status === 'open').length,
      latest_report: { report_id: 'r1', period_end: isoDay(1, t), status: 'generated' },
      change_flags: [{ metric: 'active_min', direction: 'down', since: isoDay(14, t) }],
    };
  }

  async daily(_pid: string, from: string, to: string) {
    return makeDailySeries(this.now()).filter((d) => d.day >= from && d.day <= to);
  }

  async baseline(_pid: string): Promise<Baseline | null> {
    return computeBaseline(makeDailySeries(this.now()));
  }

  async events(_pid: string, status?: string) {
    return this.eventList.filter((e) => !status || e.status === status);
  }

  async patchEvent(eventId: string, body: { status: 'acknowledged' | 'dismissed'; reason?: string; note?: string }) {
    const e = this.eventList.find((x) => x.event_id === eventId);
    if (!e) throw new ApiError(404, 'not_found', 'Alert not found.');
    if (body.status === 'dismissed' && !body.reason) {
      throw new ApiError(422, 'reason_required', 'Please choose a reason.');
    }
    e.status = body.status;
    if (body.status === 'dismissed') {
      e.dismiss_reason = body.reason ?? null;
      e.note = body.note ?? null;
    }
    return { ...e };
  }

  async reports() { return this.reportList; }

  async generateReport(_pid: string, periodEnd: string) {
    const r: Report = {
      report_id: `r${this.reportList.length + 1}`, period_start: periodEnd, period_end: periodEnd,
      status: 'fallback', is_simulated: true,
      headline: 'Template report (demo): numbers only.',
      sections: [{ title: 'Summary', body: 'The report writer was not available, so this is a plain summary of the numbers.' }],
    };
    this.reportList = [r, ...this.reportList];
    return r;
  }

  async postIngestBatch(batch: IngestBatch): Promise<IngestResponse> {
    if (this.ingestDown) throw new Error('Backend unreachable (mock)');
    const seen = this.ingested.some((b) => b.batch_id === batch.batch_id);
    if (!seen) this.ingested.push(batch);
    // Like the real backend, turn uploaded cane events into alerts (deduplicated by event_id).
    for (const r of batch.records) {
      if (r.type !== 'event' || this.eventList.some((e) => e.event_id === r.event_id)) continue;
      this.eventList.unshift({
        event_id: r.event_id, ts: r.ts, kind: r.kind as EventItem['kind'], outcome: r.outcome as EventItem['outcome'],
        status: 'open', time_quality: r.time_quality, dismiss_reason: null, note: null,
      });
    }
    const max = batch.records.reduce((m, r) => Math.max(m, r.seq), 0);
    return {
      batch_id: batch.batch_id, received: batch.records.length,
      inserted: seen ? 0 : batch.records.length, duplicates: seen ? batch.records.length : 0,
      rejected: [], server_max_seq: max,
    };
  }
}
