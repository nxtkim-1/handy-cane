jest.mock('expo/virtual/env', () => ({ env: process.env }));
jest.mock('react-native', () => ({ Platform: { OS: 'ios' }, AppState: { currentState: 'active', addEventListener: jest.fn() } }));
jest.mock('expo-secure-store', () => {
  const data = new Map<string, string>();
  return {
    __data: data,
    getItemAsync: jest.fn(async (k: string) => data.get(k) ?? null),
    setItemAsync: jest.fn(async (k: string, v: string) => { data.set(k, v); }),
    deleteItemAsync: jest.fn(async (k: string) => { data.delete(k); }),
  };
});

const user = { id: 'u', email: 'c@x', role: 'caregiver', patient_ids: ['p'], patients: [] } as any;

test('bootstrap applies saved non-default settings without wiping the saved session', async () => {
  jest.resetModules();
  const kvData: Map<string, string> = require('expo-secure-store').__data;
  const { REFRESH_KEY, SETTINGS_KEY } = require('../state/session');
  const { HttpApiClient } = require('../api/ApiClient');
  const svc = require('../state/services');

  // Saved at an earlier sign-in against a live backend; differs from env defaults (mock demo).
  svc.useApp.setState({ mock: true });
  kvData.set(REFRESH_KEY, 'saved-refresh');
  kvData.set(SETTINGS_KEY, JSON.stringify({ mock: false, apiUrl: 'https://api.saved', caneUrl: 'http://cane.saved:8080' }));
  const staleApi = svc.getApi();
  const staleTransport = svc.getTransport();
  const restore = jest.spyOn(HttpApiClient.prototype, 'restore').mockResolvedValue({
    user, tokens: { access_token: 'a', refresh_token: 'saved-refresh' },
  } as any);

  await svc.bootstrap();

  expect(restore).toHaveBeenCalledWith('saved-refresh');
  expect(kvData.get(REFRESH_KEY)).toBe('saved-refresh');
  const s = svc.useApp.getState();
  expect(s.user).toEqual(user);
  expect(s.ready).toBe(true);
  expect(s.mock).toBe(false);
  expect(s.apiUrl).toBe('https://api.saved');
  expect(s.caneUrl).toBe('http://cane.saved:8080');
  // clients were rebuilt for the saved settings
  expect(svc.getApi()).not.toBe(staleApi);
  expect(svc.getApi()).toBeInstanceOf(HttpApiClient);
  expect(svc.getTransport()).not.toBe(staleTransport);
});
