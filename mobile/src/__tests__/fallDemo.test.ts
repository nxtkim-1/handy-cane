import { MockApiClient } from '../api/MockApiClient';
import { MockCaneTransport } from '../comm/MockCaneTransport';
import { MemoryStore } from '../db/MemoryStore';
import { runPullSync } from '../sync/pullSync';
import { runUploadWorker } from '../sync/uploadWorker';
import { outcomeText } from '../ui/format';

async function sync(cane: MockCaneTransport, store: MemoryStore, api: MockApiClient) {
  await runPullSync({ transport: cane, store });
  await runUploadWorker({ store, sink: api });
}

test('a simulated fall on the cane shows up as an open alert after sync', async () => {
  const cane = new MockCaneTransport({ minutes: 30 });
  const store = new MemoryStore();
  const api = new MockApiClient();
  await sync(cane, store, api);
  const before = (await api.events('p1')).filter((e) => e.status === 'open').length;

  const fall = cane.triggerFall();
  await sync(cane, store, api);

  const events = await api.events('p1');
  const mine = events.find((e) => e.event_id === fall.event_id);
  expect(mine).toBeDefined();
  expect(mine!.status).toBe('open');
  expect(events.filter((e) => e.status === 'open').length).toBe(before + 1);
});

test('syncing twice does not duplicate the alert', async () => {
  const cane = new MockCaneTransport({ minutes: 10 });
  const store = new MemoryStore();
  const api = new MockApiClient();
  const fall = cane.triggerFall();
  await sync(cane, store, api);
  await sync(cane, store, api);
  expect((await api.events('p1')).filter((e) => e.event_id === fall.event_id)).toHaveLength(1);
});

test('outcomes sent by the real cane have readable text', () => {
  expect(outcomeText('escalated')).toBe('Not answered on the cane');
  expect(outcomeText('acknowledged_on_cane')).toBe('Alarm switched off on the cane');
});
