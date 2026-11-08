import { ApiError } from '../api/ApiClient';
import { MockApiClient } from '../api/MockApiClient';
import {
  acceptConsent, canManageOwnData, deleteConfirmed, deleteMyData, pendingConsent, withdrawConsent,
} from '../state/consent';
import { canDismissFor, homeRouteFor } from '../state/routes';

async function signedIn(email: string) {
  const api = new MockApiClient();
  const { user } = await api.login(email, 'demo');
  return { api, user };
}

test('first sign-in of a patient with no consent shows the consent screen before anything else', async () => {
  const { user } = await signedIn('patient@demo');
  expect(pendingConsent(user)?.patient_id).toBe('p-demo');
  expect(homeRouteFor(user)).toBe('/consent');
});

test('accepting records consent, then the user goes home', async () => {
  const { api, user } = await signedIn('patient@demo');
  const updated = await acceptConsent(api, user.patient_ids[0]);
  expect(updated.patients[0].consent_at).toBeTruthy();
  expect(pendingConsent(updated)).toBeNull();
  expect(homeRouteFor(updated)).toBe('/home');
});

test('a caregiver acting for a patient without consent must see it too, and can accept', async () => {
  const { api, user } = await signedIn('caregiver@demo');
  expect(homeRouteFor(user)).toBe('/consent');
  const updated = await acceptConsent(api, 'p-demo');
  expect(homeRouteFor(updated)).toBe('/patients');
});

test('consent already given by the patient is not asked again of the caregiver', async () => {
  const api = new MockApiClient();
  await api.login('patient@demo', 'demo');
  await api.giveConsent('p-demo');
  const { user } = await api.login('caregiver@demo', 'demo');
  expect(pendingConsent(user)).toBeNull();
});

test('clinicians are never asked and cannot give consent', async () => {
  const { api, user } = await signedIn('clinician@demo');
  expect(pendingConsent(user)).toBeNull();
  expect(homeRouteFor(user)).toBe('/patients');
  await expect(api.giveConsent('p-demo')).rejects.toBeInstanceOf(ApiError);
});

test('routing: loading, signed out', () => {
  expect(homeRouteFor(null, false)).toBe('/splash');
  expect(homeRouteFor(null, true)).toBe('/sign-in');
});

test('withdrawing is for the patient only and brings the consent screen back', async () => {
  const { api, user } = await signedIn('patient@demo');
  await acceptConsent(api, 'p-demo');
  expect(canManageOwnData(user, 'p-demo')).toBe(true);
  await withdrawConsent(api, 'p-demo');
  expect(pendingConsent(await api.me())?.patient_id).toBe('p-demo');

  const cg = await signedIn('caregiver@demo');
  expect(canManageOwnData(cg.user, 'p-demo')).toBe(false);
  await expect(withdrawConsent(cg.api, 'p-demo')).rejects.toMatchObject({ status: 403 });
});

test('delete needs the exact word DELETE, then removes the data', async () => {
  expect(deleteConfirmed('delete')).toBe(false);
  expect(deleteConfirmed('DELET')).toBe(false);
  expect(deleteConfirmed(' DELETE ')).toBe(true);

  const { api } = await signedIn('patient@demo');
  await expect(deleteMyData(api, 'p-demo', 'nope')).rejects.toThrow('DELETE');
  expect((await api.events('p-demo')).length).toBeGreaterThan(0);
  await deleteMyData(api, 'p-demo', 'DELETE');
  expect(await api.events('p-demo')).toEqual([]);
  expect(await api.reports()).toEqual([]);
});

test('caregiver login works end to end in the mock and sees the right things', async () => {
  const { api, user } = await signedIn('caregiver@demo');
  expect(user.role).toBe('caregiver');
  await acceptConsent(api, 'p-demo');
  expect((await api.patients()).map((p) => p.patient_id)).toEqual(['p-demo']); // only their patient
  const events = await api.events('p-demo');
  expect(events.length).toBeGreaterThan(0);
  // allowed to acknowledge, not to dismiss (can_dismiss_events is false for this caregiver)
  expect((await api.patchEvent('e1', { status: 'acknowledged' })).status).toBe('acknowledged');
  await expect(api.patchEvent('e2', { status: 'dismissed', reason: 'i_am_fine' })).rejects.toMatchObject({ status: 403 });
  expect(canDismissFor(user, 'p-demo')).toBe(false);
});

test('dismiss rules: patient yes, clinician never, caregiver per can_dismiss_events', async () => {
  const p = (await signedIn('patient@demo')).user;
  const c = (await signedIn('clinician@demo')).user;
  expect(canDismissFor(p, 'p-demo')).toBe(true);
  expect(canDismissFor(c, 'p-demo')).toBe(false);
  const cg = (await signedIn('caregiver@demo')).user;
  const allowed = { ...cg, patients: cg.patients.map((x) => ({ ...x, can_dismiss_events: true })) };
  expect(canDismissFor(allowed, 'p-demo')).toBe(true);
  expect(canDismissFor(allowed, 'someone-else')).toBe(false);
});

test('escalation history from the mock', async () => {
  const { api } = await signedIn('clinician@demo');
  const rows = await api.escalations('p-demo');
  expect(rows[0]).toMatchObject({ event_id: 'e2', channel: 'sms', ok: true, attempt: 1 });
});
