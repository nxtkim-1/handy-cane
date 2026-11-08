/**
 * Maps the real backend's JSON (MASTER 13, backend/app/schemas.py) onto the app's own types.
 * Kept in one place and tested against captured live responses (__tests__/fixtures/live.json) so a
 * backend change shows up as a failing test instead of a crash on the phone.
 */
import type {
  Baseline, DailyMetric, EventItem, Overview, PatientListItem, Report, User,
} from './types';
import { USUAL_TEXT } from '../ui/format';

const STALE_AFTER_MS = 48 * 3600_000;

export function adaptUser(me: any): User {
  return {
    user_id: me.user_id, email: me.email, display_name: me.display_name, role: me.role,
    patient_ids: (me.patients ?? []).map((p: any) => p.patient_id),
  };
}

export function adaptOverview(o: any): Overview {
  const l7 = o.last_7_valid_days ?? {};
  return {
    ...o,
    last_7_valid_days: { active_min_median: l7.active_min_median ?? null, valid_days: l7.n_valid_days ?? l7.valid_days ?? 0 },
    latest_report: o.latest_report ?? null,
    change_flags: o.change_flags ?? [],
  };
}

export function adaptPatientListItem(p: any, o?: any, now = Date.now()): PatientListItem {
  const last = o?.device?.last_seen_at ?? null;
  return {
    patient_id: p.patient_id, display_name: p.display_name, is_simulated: !!p.is_simulated, timezone: p.timezone,
    open_events: o?.open_events ?? 0,
    sustained_change: (o?.change_flags ?? []).length > 0,
    last_sync_at: last,
    stale_sync: last === null || now - new Date(last).getTime() > STALE_AFTER_MS,
  };
}

export function adaptDaily(rows: any[]): DailyMetric[] {
  return rows.map((r) => {
    const ok = !!r.valid && !r.no_data;
    return {
      day: r.day, valid: ok, coverage_h: r.coverage_h ?? 0,
      active_min: ok ? r.active_min ?? null : null, // never 0 for a day without data (MASTER 9.4)
      strikes: ok ? r.strikes ?? null : null,
    };
  });
}

export function adaptBaseline(b: any): Baseline | null {
  const a = b?.stats?.active_min;
  if (!a) return null;
  return { metric: 'active_min', median: a.median, mad: a.mad, description: USUAL_TEXT };
}

export function adaptEvent(e: any): EventItem {
  return {
    event_id: e.event_id, ts: e.ts, kind: e.kind, outcome: e.outcome, status: e.status,
    time_quality: e.time_quality, dismiss_reason: e.status_reason ?? null, note: null,
  };
}

const bullets = (xs: any[] | undefined) =>
  (xs ?? []).map((x) => '• ' + (typeof x === 'string' ? x : x.statement)).join('\n');

export function adaptReport(r: any): Report {
  const o = r.output_json;
  const sections: Report['sections'] = [];
  if (o) {
    const add = (title: string, body: string | undefined) => {
      if (body && body.trim()) sections.push({ title, body });
    };
    add('Summary', o.overall_summary);
    add('Cane activity', o.activity_overview);
    add('Trends', bullets(o.mobility_trends));
    add('Compared with the previous period', bullets(o.changes_vs_previous));
    add('Safety notes', bullets(o.safety_concerns));
    add('Worth keeping an eye on', bullets(o.areas_to_monitor));
    add('How reliable is this data', o.data_reliability);
    add('Note', o.disclaimer_ack);
  }
  return {
    report_id: r.report_id, period_start: r.period_start, period_end: r.period_end,
    status: r.status, is_simulated: !!r.is_simulated,
    headline: o?.patient_friendly_summary ?? 'This report is being prepared.',
    sections,
  };
}
