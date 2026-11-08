import fx from './fixtures/live.json';
import {
  adaptEscalations, adaptEvent, adaptOverview, adaptPatientListItem, adaptUser, listHasSummary,
} from '../api/adapt';

test('events carry severity, reason and cause, in server order', () => {
  const rows = fx.events.map(adaptEvent);
  expect(rows.map((r) => r.severity)).toEqual(['high', 'medium', 'low']);
  rows.forEach((r) => {
    expect(r.severity_reason.length).toBeGreaterThan(5);
    expect(r.cause).toBeNull();
  });
});

test('the backend severity wins over the local table; cause passes through', () => {
  const e = adaptEvent({ ...fx.events[2], severity: 'high', severity_reason: 'Because.', cause: 'Dropped on stairs' });
  expect(e).toMatchObject({ severity: 'high', severity_reason: 'Because.', cause: 'Dropped on stairs' });
});

test('an older backend without severity is ranked with the same table', () => {
  const { severity, severity_reason, cause, ...old } = fx.events[0] as any;
  const e = adaptEvent(old);
  expect(e.severity).toBe(severity);
  expect(e.severity_reason).toBeTruthy();
});

test('overview exposes open_events_by_severity (and zeros when absent)', () => {
  expect(adaptOverview(fx.overview).open_events_by_severity).toEqual({ high: 1, medium: 1, low: 1 });
  const { open_events_by_severity, ...old } = fx.overview as any;
  expect(adaptOverview(old).open_events_by_severity).toEqual({ high: 0, medium: 0, low: 0 });
});

test('/me keeps consent_at, relation and can_dismiss_events', () => {
  const u = adaptUser(fx.me);
  expect(u.patients[0]).toMatchObject({ relation: 'self', can_dismiss_events: true });
  expect(u.patients[0].consent_at).toBeTruthy();
  const none = adaptUser({ ...fx.me, patients: [{ ...fx.me.patients[0], consent_at: null }] });
  expect(none.patients[0].consent_at).toBeNull();
});

test('patient list uses the list summary when present, the overview otherwise', () => {
  expect(listHasSummary(fx.patients[0])).toBe(true);
  const p = adaptPatientListItem(fx.patients[0]);
  expect(p).toMatchObject({ open_events: 3, open_high_events: 1, stale_sync: false });
  const {
    open_events, open_high_events, last_sync_at, sustained_change, stale_sync, ...old
  } = fx.patients[0] as any;
  expect(listHasSummary(old)).toBe(false);
  const q = adaptPatientListItem(old, fx.overview, new Date(fx.overview.device.last_seen_at).getTime());
  expect(q.open_events).toBe(3);
  expect(q.open_high_events).toBe(1);
});

test('escalations map to a typed list; junk becomes an empty list', () => {
  const rows = adaptEscalations(fx.escalations);
  expect(rows).toHaveLength(2);
  expect(rows[0]).toEqual({
    event_id: fx.escalations[0].event_id, sent_at: fx.escalations[0].sent_at, channel: 'sms', ok: true, attempt: 1,
  });
  expect(adaptEscalations(null)).toEqual([]);
  expect(adaptEscalations({ error: 'x' })).toEqual([]);
});
