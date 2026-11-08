jest.mock('expo/virtual/env', () => ({ env: process.env }));
jest.mock('react-native', () => ({ Platform: { OS: 'web' } }));
jest.mock('expo-secure-store', () => ({ setItemAsync: jest.fn(), deleteItemAsync: jest.fn() }));

const tokens = { access_token: 'a', refresh_token: 'r' } as any;

function load() {
  jest.resetModules();
  const svc = require('../state/services');
  const { HttpApiClient } = require('../api/ApiClient');
  svc.useApp.setState({ mock: false, apiUrl: 'http://api.test' });
  const client = svc.getApi();
  expect(client).toBeInstanceOf(HttpApiClient);
  client.setTokens(tokens);
  return { svc, client };
}

describe('setConfig session handling', () => {
  it('keeps the same client and tokens when only cane/feed/pair config changes', () => {
    const { svc, client } = load();
    svc.useApp.getState().setConfig({ caneUrl: 'http://x' });
    svc.useApp.getState().setConfig({ feedUrl: 'http://feed', pairCode: '123' });
    expect(svc.getApi()).toBe(client);
    expect((client as any).tokens).toEqual(tokens);
  });

  it('drops tokens and creates a fresh tokenless client when apiUrl changes', () => {
    const { svc, client } = load();
    svc.useApp.setState({ user: { id: 'u', patient_ids: ['p'] }, activePatientId: 'p' });
    svc.useApp.getState().setConfig({ apiUrl: 'http://other' });
    expect((client as any).tokens).toBeNull();
    const next = svc.getApi();
    expect(next).not.toBe(client);
    expect((next as any).tokens).toBeNull();
    expect(svc.useApp.getState().user).toBeNull();
  });

  it('drops the session when mock mode changes', () => {
    const { svc, client } = load();
    svc.useApp.getState().setConfig({ mock: true });
    expect((client as any).tokens).toBeNull();
    expect(svc.getApi()).not.toBe(client);
  });
});
