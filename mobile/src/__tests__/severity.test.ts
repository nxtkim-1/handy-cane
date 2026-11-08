import { countBySeverity, highAlertText, severityFor, sortEvents, type Severity } from '../api/severity';
import { MockApiClient } from '../api/MockApiClient';

// Same table as the backend.
const TABLE: [string, string, number, Severity][] = [
  ['help_request', 'acknowledged_on_cane', 1.0, 'high'],
  ['help_request', 'none', 0, 'high'],
  ['potential_fall', 'escalated', 1.0, 'high'],
  ['potential_fall', 'escalated', 6.0, 'high'],
  ['potential_fall', 'acknowledged_on_cane', 1.0, 'medium'],
  ['potential_fall', 'acknowledged_on_cane', 5.0, 'medium'],
  ['potential_fall', 'cancelled_by_user', 3.0, 'medium'],
  ['potential_fall', 'cancelled_by_user', 4.1, 'medium'],
  ['potential_fall', 'cancelled_by_user', 2.99, 'low'],
  ['potential_fall', 'cancelled_by_user', 0, 'low'],
  ['impact_only', 'none', 5.0, 'low'],
  ['impact_only', 'cancelled_by_user', 0.5, 'low'],
  ['sensor_fault', 'none', 0, 'medium'],
  ['something_new', 'whatever', 9, 'medium'],
];

test.each(TABLE)('%s + %s (peak %sg) -> %s', (kind, outcome, peak, expected) => {
  const r = severityFor(kind, outcome, peak);
  expect(r.severity).toBe(expected);
  expect(r.reason.length).toBeGreaterThan(10);
});

test('missing peak_g counts as a light impact', () => {
  expect(severityFor('potential_fall', 'cancelled_by_user', null).severity).toBe('low');
  expect(severityFor('potential_fall', 'cancelled_by_user', undefined).severity).toBe('low');
});

test('older app names map to the same severities', () => {
  expect(severityFor('help_press', 'help_requested', 1).severity).toBe('high');
  expect(severityFor('potential_fall', 'unanswered', 1).severity).toBe('high');
});

test('sortEvents: open first, then severity, then newest', () => {
  const rows = [
    { id: 'old-low-open', status: 'open', severity: 'low' as Severity, ts: '2026-01-01T00:00:00Z' },
    { id: 'dismissed-high', status: 'dismissed', severity: 'high' as Severity, ts: '2026-01-05T00:00:00Z' },
    { id: 'new-med-open', status: 'open', severity: 'medium' as Severity, ts: '2026-01-04T00:00:00Z' },
    { id: 'old-med-open', status: 'open', severity: 'medium' as Severity, ts: '2026-01-02T00:00:00Z' },
    { id: 'high-open', status: 'open', severity: 'high' as Severity, ts: '2026-01-03T00:00:00Z' },
  ];
  expect(sortEvents(rows).map((r) => r.id)).toEqual([
    'high-open', 'new-med-open', 'old-med-open', 'old-low-open', 'dismissed-high',
  ]);
});

test('countBySeverity counts open alerts only; banner text pluralises', () => {
  expect(countBySeverity([
    { status: 'open', severity: 'high' }, { status: 'dismissed', severity: 'high' }, { status: 'open', severity: 'low' },
  ])).toEqual({ high: 1, medium: 0, low: 1 });
  expect(highAlertText(1)).toBe('1 high-priority alert needs a look');
  expect(highAlertText(2)).toBe('2 high-priority alerts need a look');
});

test('mock backend ranks seeded and uploaded events with the table', async () => {
  const api = new MockApiClient(() => new Date('2026-11-08T12:00:00Z'));
  const rows = await api.events('p-demo');
  expect(rows.every((r) => r.severity_reason.length > 0)).toBe(true);
  expect(rows[0]).toMatchObject({ event_id: 'e2', severity: 'high', status: 'open' });
  expect(rows.find((r) => r.event_id === 'e1')?.severity).toBe('medium'); // cancelled, 3.6 g
  expect(rows.find((r) => r.event_id === 'e4')?.severity).toBe('low');
  expect(rows[rows.length - 1].status).toBe('dismissed');
  const ov = await api.overview('p-demo');
  expect(ov.open_events_by_severity).toEqual({ high: 1, medium: 1, low: 1 });
});
