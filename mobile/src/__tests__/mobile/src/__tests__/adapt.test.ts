import fx from './fixtures/live.json';
import {
  adaptBaseline, adaptDaily, adaptEvent, adaptOverview, adaptPatientListItem, adaptReport, adaptUser,
} from '../api/adapt';

test('/me becomes a User with patient_ids', () => {
  const u = adaptUser(fx.me);
  expect(u.patient_ids).toEqual([fx.me.patients[0].patient_id]);
  expect(u.role).toBe('patient');
});

test('overview exposes valid_days and never undefined lists', () => {
  const o = adaptOverview(fx.overview);
  expect(typeof o.last_7_valid_days.valid_days).toBe('number');
  expect(Array.isArray(o.change_flags)).toBe(true);
});

test('patient list item is built from the overview', () => {
  const seen = new Date(fx.overview.device.last_seen_at ?? Date.now()).getTime();
  const p = adaptPatientListItem(fx.patients[0], fx.overview, seen);
  expect(p.open_events).toBe(fx.overview.open_events);
  expect(p.sustained_change).toBe(fx.overview.change_flags.length > 0);
});

test('days without data are null, never zero', () => {
  const rows = adaptDaily(fx.daily);
  const bad = rows.filter((r) => !r.valid);
  expect(bad.length).toBeGreaterThan(0);
  bad.forEach((r) => {
    expect(r.active_min).toBeNull();
    expect(r.strikes).toBeNull();
  });
});

test('baseline comes from stats.active_min', () => {
  const b = adaptBaseline(fx.baseline)!;
  expect(b.median).toBe(fx.baseline.stats.active_min.median);
  expect(adaptBaseline(null)).toBeNull();
});

test('events map status_reason to dismiss_reason', () => {
  const e = adaptEvent({ ...fx.events[0], status: 'dismissed', status_reason: 'i_am_fine' });
  expect(e.dismiss_reason).toBe('i_am_fine');
  expect(adaptEvent(fx.events[0]).event_id).toBe(fx.events[0].event_id);
});

test('report output_json becomes a headline and readable sections', () => {
  const r = adaptReport(fx.reports[0]);
  expect(r.headline).toBe(fx.reports[0].output_json.patient_friendly_summary);
  expect(r.sections.length).toBeGreaterThanOrEqual(5);
  expect(r.sections.every((s) => s.title && s.body)).toBe(true);
  expect(adaptReport({ ...fx.reports[0], output_json: null }).sections).toEqual([]);
});
