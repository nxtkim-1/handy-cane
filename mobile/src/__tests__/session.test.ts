import { ApiError } from '../api/ApiClient';
import { MockApiClient } from '../api/MockApiClient';
import {
  REFRESH_KEY, SETTINGS_KEY, clearSession, loadSettings, persistSignIn, restoreUser, safeStore,
  type AppSettings, type KeyValueStore,
} from '../state/session';

function memoryKv(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    async get(k) { return data.get(k) ?? null; },
    async set(k, v) { data.set(k, v); },
    async remove(k) { data.delete(k); },
  };
}

const DEFAULTS: AppSettings = { mock: true, apiUrl: 'http://default:8000', caneUrl: 'http://cane:8080' };

test('settings round-trip and fall back to defaults', async () => {
  const kv = memoryKv();
  expect(await loadSettings(kv, DEFAULTS)).toEqual(DEFAULTS);
  const live = { mock: false, apiUrl: 'https://api.example', caneUrl: 'http://10.0.0.5:8080' };
  await persistSignIn(kv, 'tok', live);
  expect(await loadSettings(kv, DEFAULTS)).toEqual(live);
  kv.data.set(SETTINGS_KEY, '{not json');
  expect(await loadSettings(kv, DEFAULTS)).toEqual(DEFAULTS);
});

test('restores the signed-in user from the stored refresh token', async () => {
  const first = new MockApiClient();
  const { tokens } = await first.login('caregiver@demo', 'demo');
  const kv = memoryKv();
  await persistSignIn(kv, tokens.refresh_token, DEFAULTS);

  const relaunch = new MockApiClient(); // a new process: no in-memory session
  const r = await restoreUser(kv, relaunch);
  expect(r.kind).toBe('signed_in');
  if (r.kind === 'signed_in') expect(r.user.email).toBe('caregiver@demo');
  expect((await relaunch.me()).role).toBe('caregiver');
});

test('consent given before closing the app is remembered by the restored session', async () => {
  const first = new MockApiClient();
  const kv = memoryKv();
  first.onTokens = (t) => { if (t) void kv.set(REFRESH_KEY, t.refresh_token); };
  await first.login('patient@demo', 'demo');
  await first.giveConsent('p-demo');
  const r = await restoreUser(kv, new MockApiClient());
  expect(r.kind === 'signed_in' && r.user.patients[0].consent_at).toBeTruthy();
});

test('no stored token means signed out, without calling the backend', async () => {
  const api = new MockApiClient();
  const spy = jest.spyOn(api, 'restore');
  expect(await restoreUser(memoryKv(), api)).toEqual({ kind: 'signed_out', reason: 'no_token' });
  expect(spy).not.toHaveBeenCalled();
});

test('a rejected refresh token is deleted and lands on sign-in', async () => {
  const kv = memoryKv();
  kv.data.set(REFRESH_KEY, 'garbage');
  expect(await restoreUser(kv, new MockApiClient())).toEqual({ kind: 'signed_out', reason: 'rejected' });
  expect(kv.data.has(REFRESH_KEY)).toBe(false);
});

test('a network failure keeps the token for the next launch but still signs out for now', async () => {
  const kv = memoryKv();
  kv.data.set(REFRESH_KEY, 'tok');
  const api = new MockApiClient();
  jest.spyOn(api, 'restore').mockRejectedValue(new Error('Network request failed'));
  expect(await restoreUser(kv, api)).toEqual({ kind: 'signed_out', reason: 'unreachable' });
  expect(kv.data.get(REFRESH_KEY)).toBe('tok');
});

test('a rotated refresh token replaces the stored one', async () => {
  const kv = memoryKv();
  kv.data.set(REFRESH_KEY, 'old');
  const api = new MockApiClient();
  const { user } = await api.login('patient@demo', 'demo');
  jest.spyOn(api, 'restore').mockResolvedValue({ user, tokens: { access_token: 'a', refresh_token: 'new' } });
  await restoreUser(kv, api);
  expect(kv.data.get(REFRESH_KEY)).toBe('new');
});

test('sign out clears the token and the settings', async () => {
  const kv = memoryKv();
  await persistSignIn(kv, 'tok', DEFAULTS);
  await clearSession(kv);
  expect(kv.data.size).toBe(0);
});

test('a throwing secure store never breaks startup', async () => {
  const broken: KeyValueStore = {
    get: async () => { throw new Error('keystore unavailable'); },
    set: async () => { throw new Error('keystore unavailable'); },
    remove: async () => { throw new Error('keystore unavailable'); },
  };
  const kv = safeStore(broken);
  expect(await loadSettings(kv, DEFAULTS)).toEqual(DEFAULTS);
  expect((await restoreUser(kv, new MockApiClient())).kind).toBe('signed_out');
  await expect(persistSignIn(kv, 't', DEFAULTS)).resolves.toBeUndefined();
});

test('ApiError is the type restore rejects with', async () => {
  await expect(new MockApiClient().restore('nope')).rejects.toBeInstanceOf(ApiError);
});
