import fx from './fixtures/backend-live.json';
import { HttpApiClient } from '../api/ApiClient';

// Replays responses recorded from the real backend (see fixtures/backend-live.json) through HttpApiClient.
const PID = fx.me.patients[0].patient_id;

function client(extra: Record<string, [number, unknown]> = {}) {
  const routes: Record<string, [number, unknown]> = {
    'POST /v1/auth/login': [200, fx.login],
    'GET /v1/me': [200, fx.me],
    'GET /v1/patients': [200, fx.patients],
    [`GET /v1/patients/${PID}/overview`]: [200, fx.overview],
    [`GET /v1/patients/${PID}/daily`]: [200, fx.daily],
    [`GET /v1/patients/${PID}/baseline`]: [200, fx.baseline],
    [`GET /v1/patients/${PID}/events`]: [200, fx.events],
    [`GET /v1/patients/${PID}/reports`]: [200, fx.reports],
    [`POST /v1/patients/${PID}/reports/generate`]: [202, fx.generate],
    [`GET /v1/reports/${fx.report.report_id}`]: [200, fx.report],
    [`PATCH /v1/events/${fx.patch_event.event_id}`]: [200, fx.patch_event],
    'POST /v1/ingest/batches': [200, fx.ingest_response],
    ...extra,
  };
  const calls: string[] = [];
  const f = async (url: string, init: any) => {
    const key = `${init.method} ${url.replace('http://x', '').split('?')[0]}`;
    calls.push(key);
    const r = routes[key];
    if (!r) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: r[0] < 400, status: r[0], json: async () => r[1] };
  };
  return { api: new HttpApiClient('http://x', f as any), calls };
}

test('login + /me: patients[] becomes patient_ids', async () => {
  const { api } = client();
  const { user } = await api.login('clinician@demo.example', 'demo-password-1');
  expect(user.patient_ids).toEqual([PID]);
  expect(user.role).toBe('clinician');
});

test('patients(): list item built from overview (list has no open_events/sync info)', async () => {
  const { api, calls } = client();
  const [p] = await api.patients();
  expect(calls).toContain(`GET /v1/patients/${PID}/overview`);
  expect(p.open_events).toBe(fx.overview.open_events);
  expect(p.sustained_change).toBe(true);
  expect(p.last_sync_at).toBe(fx.overview.device.last_seen_at);
  expect(typeof p.stale_sync).toBe('boolean');
});

test('overview with today:null does not crash the screens (valid_days mapped, today filled)', async () => {
  const { api } = client();
  const o = await api.overview(PID);
  expect(fx.overview.today).toBeNull();
  expect(o.today.active_min).toBeNull();
  expect(o.last_7_valid_days.valid_days).toBe(fx.overview.last_7_valid_days.n_valid_days);
  expect(o.latest_report).toBeNull();
  expect(o.change_flags.length).toBe(3);
});

test('overview with a real today row passes through', async () => {
  const { api } = client({ [`GET /v1/patients/${PID}/overview`]: [200, fx.overview_after_ingest] });
  const o = await api.overview(PID);
  expect(o.today).toEqual(fx.overview_after_ingest.today);
  expect(o.latest_report?.period_end).toBe('2026-11-07');
});

test('overview tolerates a patient with no assigned cane', async () => {
  const { api } = client({ [`GET /v1/patients/${PID}/overview`]: [200, { ...fx.overview, device: null }] });
  const o = await api.overview(PID);
  expect(o.device.last_seen_at).toBeNull();
});

test('daily: no_data days are null, never 0', async () => {
  const { api } = client();
  const rows = await api.daily(PID, '2026-10-01', '2026-11-08');
  expect(rows.length).toBe(fx.daily.length);
  const bad = rows.filter((r) => !r.valid);
  expect(bad.length).toBeGreaterThan(0);
  bad.forEach((r) => { expect(r.active_min).toBeNull(); expect(r.strikes).toBeNull(); });
  expect(rows.find((r) => r.valid)!.active_min).toBeGreaterThan(0);
});

test('baseline: stats.active_min flattened; null baseline stays null', async () => {
  const { api } = client();
  const b = await api.baseline(PID);
  expect(b).toMatchObject({ metric: 'active_min', median: fx.baseline.stats.active_min.median, mad: fx.baseline.stats.active_min.mad });
  const { api: api2 } = client({ [`GET /v1/patients/${PID}/baseline`]: [200, null] });
  expect(await api2.baseline(PID)).toBeNull();
});

test('events + PATCH: status_reason becomes dismiss_reason', async () => {
  const { api } = client();
  const evs = await api.events(PID);
  expect(evs.length).toBe(fx.events.length);
  expect(evs[0]).toMatchObject({ event_id: fx.events[0].event_id, kind: 'potential_fall', status: 'open', dismiss_reason: null });
  const e = await api.patchEvent(fx.patch_event.event_id, { status: 'dismissed', reason: 'i_am_fine' });
  expect(e.status).toBe('dismissed');
  expect(e.dismiss_reason).toBe('i_am_fine');
});

test('reports list: output_json becomes headline + sections', async () => {
  const { api } = client();
  const [r] = await api.reports(PID);
  expect(r.headline).toBe(fx.report.output_json.patient_friendly_summary);
  expect(r.sections.length).toBeGreaterThanOrEqual(7);
  expect(r.sections.every((s) => s.title && s.body)).toBe(true);
  expect(r.status).toBe('fallback');
});

test('generateReport: 202 {report_id,status} is followed by GET /v1/reports/{id}', async () => {
  const { api, calls } = client();
  const r = await api.generateReport(PID, '2026-11-07');
  expect(calls).toEqual([`POST /v1/patients/${PID}/reports/generate`, `GET /v1/reports/${fx.report.report_id}`]);
  expect(r.report_id).toBe(fx.report.report_id);
  expect(r.headline).toBe(fx.report.output_json.patient_friendly_summary);
});

test('report with null output_json yields a placeholder, not a crash', async () => {
  const { api } = client({ [`GET /v1/patients/${PID}/reports`]: [200, [{ ...fx.report, output_json: null, status: 'pending' }]] });
  const [r] = await api.reports(PID);
  expect(r.sections).toEqual([]);
  expect(r.headline).toBeTruthy();
});

test('ingest: backend response (incl. per-record rejections) satisfies IngestResponse', async () => {
  const { api } = client();
  const res = await api.postIngestBatch(fx.ingest_request as any);
  expect(res).toMatchObject({ batch_id: fx.ingest_request.batch_id, received: 4, inserted: 3, duplicates: 0, server_max_seq: 3 });
  expect(res.rejected[0]).toMatchObject({ seq: 4 });
  expect(typeof res.rejected[0].reason).toBe('string');
});
