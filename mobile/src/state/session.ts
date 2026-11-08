/**
 * Session persistence, kept free of React Native imports so it can be unit tested.
 * The refresh token and the app settings (demo/live mode, backend and cane addresses) live in a small
 * key-value store (expo-secure-store on a phone; nothing on the web, where it degrades to "not signed in").
 */
import { ApiError, type ApiClient } from '../api/ApiClient';
import type { User } from '../api/types';

export interface KeyValueStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

export interface AppSettings {
  mock: boolean;
  apiUrl: string;
  caneUrl: string;
}

export const REFRESH_KEY = 'smartcane_refresh_token';
export const SETTINGS_KEY = 'smartcane_settings';

/** A store that stores nothing (web, or secure store unavailable). */
export const nullStore: KeyValueStore = {
  async get() { return null; },
  async set() {},
  async remove() {},
};

/** Never throws: a broken secure store must not stop the app from starting. */
export function safeStore(inner: KeyValueStore): KeyValueStore {
  return {
    async get(k) { try { return await inner.get(k); } catch { return null; } },
    async set(k, v) { try { await inner.set(k, v); } catch { /* not fatal */ } },
    async remove(k) { try { await inner.remove(k); } catch { /* not fatal */ } },
  };
}

export async function loadSettings(kv: KeyValueStore, defaults: AppSettings): Promise<AppSettings> {
  const raw = await kv.get(SETTINGS_KEY);
  if (!raw) return defaults;
  try {
    const j = JSON.parse(raw);
    return {
      mock: typeof j.mock === 'boolean' ? j.mock : defaults.mock,
      apiUrl: typeof j.apiUrl === 'string' && j.apiUrl ? j.apiUrl : defaults.apiUrl,
      caneUrl: typeof j.caneUrl === 'string' && j.caneUrl ? j.caneUrl : defaults.caneUrl,
    };
  } catch {
    return defaults;
  }
}

export async function saveSettings(kv: KeyValueStore, s: AppSettings): Promise<void> {
  await kv.set(SETTINGS_KEY, JSON.stringify(s));
}

export async function saveRefresh(kv: KeyValueStore, token: string | null): Promise<void> {
  if (token) await kv.set(REFRESH_KEY, token);
  else await kv.remove(REFRESH_KEY);
}

/** Sign-in succeeded: remember who, and how to reach the backend and cane. */
export async function persistSignIn(kv: KeyValueStore, refreshToken: string, s: AppSettings): Promise<void> {
  await saveRefresh(kv, refreshToken);
  await saveSettings(kv, s);
}

/** Sign out: nothing about the user or the session survives. */
export async function clearSession(kv: KeyValueStore): Promise<void> {
  await kv.remove(REFRESH_KEY);
  await kv.remove(SETTINGS_KEY);
}

export type RestoreResult =
  | { kind: 'signed_in'; user: User; refreshToken: string }
  | { kind: 'signed_out'; reason: 'no_token' | 'rejected' | 'unreachable' };

/**
 * Tries to sign in again from the stored refresh token. A rejected token (401/403) is deleted; a
 * network failure keeps it so the next launch can retry, but still lands on the sign-in screen.
 */
export async function restoreUser(kv: KeyValueStore, api: ApiClient): Promise<RestoreResult> {
  const token = await kv.get(REFRESH_KEY);
  if (!token) return { kind: 'signed_out', reason: 'no_token' };
  try {
    const r = await api.restore(token);
    if (r.tokens.refresh_token !== token) await saveRefresh(kv, r.tokens.refresh_token);
    return { kind: 'signed_in', user: r.user, refreshToken: r.tokens.refresh_token };
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 422)) {
      await kv.remove(REFRESH_KEY);
      return { kind: 'signed_out', reason: 'rejected' };
    }
    return { kind: 'signed_out', reason: 'unreachable' };
  }
}
