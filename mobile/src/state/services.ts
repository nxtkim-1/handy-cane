import { useEffect } from 'react';
import { AppState, Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';
import type { ApiClient } from '../api/ApiClient';
import { HttpApiClient } from '../api/ApiClient';
import { MockApiClient } from '../api/MockApiClient';
import type { Tokens, User } from '../api/types';
import type { CaneTransport } from '../comm/CaneTransport';
import { HttpCaneTransport } from '../comm/HttpCaneTransport';
import { MockCaneTransport } from '../comm/MockCaneTransport';
import type { LocalStore } from '../db/LocalStore';
import { MemoryStore } from '../db/MemoryStore';
import { META_LAST_SYNC, runPullSync } from '../sync/pullSync';
import { SyncScheduler, type CaneState } from '../sync/scheduler';
import { runUploadWorker } from '../sync/uploadWorker';
import { pendingConsent } from './consent';
import { queryClient } from './queryClient';
import {
  clearSession, loadSettings, nullStore, persistSignIn, restoreUser, safeStore, saveRefresh, saveSettings,
  type AppSettings, type KeyValueStore,
} from './session';

const ENV_API = process.env.EXPO_PUBLIC_API_URL;
const ENV_CANE = process.env.EXPO_PUBLIC_CANE_URL;

const DEFAULTS: AppSettings = {
  /** mock = no backend, no hardware (default unless EXPO_PUBLIC_API_URL is set). */
  mock: !ENV_API,
  apiUrl: ENV_API ?? 'http://10.0.2.2:8000',
  caneUrl: ENV_CANE ?? 'http://192.168.4.1:8080',
};

interface AppStore {
  mock: boolean;
  apiUrl: string;
  caneUrl: string;
  user: User | null;
  activePatientId: string | null;
  /** False while the saved session is being restored at launch (shows the splash). */
  ready: boolean;
  setConfig(c: Partial<Pick<AppStore, 'mock' | 'apiUrl' | 'caneUrl'>>): void;
  setUser(u: User | null): void;
}

export const useApp = create<AppStore>((set) => ({
  ...DEFAULTS,
  user: null,
  activePatientId: null,
  ready: false,
  setConfig: (c) => {
    api = null;
    transport = null;
    set(c);
  },
  setUser: (u) => set((s) => ({
    user: u,
    // keep the patient the user was looking at if they still have access to it
    activePatientId: u ? (u.patient_ids.includes(s.activePatientId ?? '') ? s.activePatientId : u.patient_ids[0] ?? null) : null,
  })),
}));

let api: ApiClient | null = null;
let transport: CaneTransport | null = null;
let storePromise: Promise<LocalStore> | null = null;
let mockCane: MockCaneTransport | null = null;
let mockApi: MockApiClient | null = null;

const settingsOf = (): AppSettings => {
  const { mock, apiUrl, caneUrl } = useApp.getState();
  return { mock, apiUrl, caneUrl };
};

export function getApi(): ApiClient {
  if (!api) {
    const s = useApp.getState();
    if (s.mock) {
      mockApi ??= new MockApiClient();
      api = mockApi;
    } else {
      api = new HttpApiClient(s.apiUrl);
    }
    // Store a rotated/refreshed token as soon as the client gets one.
    api.onTokens = (t: Tokens | null) => { void saveRefreshToken(t ? t.refresh_token : null); };
  }
  return api;
}

export function getTransport(): CaneTransport {
  if (!transport) {
    const s = useApp.getState();
    if (s.mock) {
      mockCane ??= new MockCaneTransport({ minutes: 240 });
      transport = mockCane;
    } else {
      transport = new HttpCaneTransport(s.caneUrl);
    }
  }
  return transport;
}

export function getMockCane(): MockCaneTransport | null {
  return useApp.getState().mock ? (getTransport() as MockCaneTransport) : null;
}

export function getStore(): Promise<LocalStore> {
  storePromise ??= (async () => {
    if (Platform.OS === 'web') return new MemoryStore();
    const { SqliteStore } = await import('../db/SqliteStore');
    return SqliteStore.open();
  })();
  return storePromise;
}

// ---- session persistence -------------------------------------------------------------------

const secureKv: KeyValueStore = Platform.OS === 'web'
  ? nullStore
  : safeStore({
    get: (k) => SecureStore.getItemAsync(k),
    set: (k, v) => SecureStore.setItemAsync(k, v),
    remove: (k) => SecureStore.deleteItemAsync(k),
  });

export async function saveRefreshToken(t: string | null) {
  await saveRefresh(secureKv, t);
}

/** Call once at launch: restores settings and, if possible, the signed-in user. Never throws. */
export async function bootstrap(): Promise<void> {
  try {
    const settings = await loadSettings(secureKv, DEFAULTS);
    useApp.getState().setConfig(settings);
    const r = await restoreUser(secureKv, getApi());
    if (r.kind === 'signed_in') useApp.getState().setUser(r.user);
  } catch { /* fall through to the sign-in screen */ } finally {
    useApp.setState({ ready: true });
  }
}

/** Sign-in succeeded: remember the session and the addresses. */
export async function completeSignIn(user: User, refreshToken: string) {
  await persistSignIn(secureKv, refreshToken, settingsOf());
  useApp.getState().setUser(user);
}

/** Persist address changes made while signed in (the sign-in screen saves them on success instead). */
export async function persistSettingsIfSignedIn() {
  if (useApp.getState().user) await saveSettings(secureKv, settingsOf());
}

/** Clears the session and every cached screen so the next user never sees the last one's data. */
export async function signOut() {
  scheduler?.stop();
  await clearSession(secureKv);
  queryClient.clear();
  try { await (await getStore()).clearCaches(); } catch { /* not fatal */ }
  useSync.setState({ lastSyncMs: null, message: null, error: null, caneState: 'unknown' });
  useApp.getState().setUser(null);
}

// ---- sync ----------------------------------------------------------------------------------

export interface SyncStatus {
  syncing: boolean;
  lastSyncMs: number | null;
  message: string | null;
  error: string | null;
  waitingToUpload: number;
  caneState: CaneState;
}

async function refreshSyncStatus() {
  const store = await getStore();
  const last = await store.getMeta(META_LAST_SYNC);
  const q = await store.queueStats();
  useSync.setState({ lastSyncMs: last ? Number(last) : null, waitingToUpload: q.records });
}

export const caneConfigured = () => {
  const s = useApp.getState();
  return s.mock || s.caneUrl.trim().length > 0;
};

let scheduler: SyncScheduler | null = null;
export function getScheduler(): SyncScheduler {
  scheduler ??= new SyncScheduler({
    caneConfigured,
    onCaneState: (caneState) => useSync.setState({ caneState }),
    async pull() {
      const store = await getStore();
      const pull = await runPullSync({ transport: getTransport(), store });
      useSync.setState({ message: `Received ${pull.inserted} new records from the cane.`, error: null });
      if (pull.inserted > 0) queryClient.invalidateQueries();
    },
    async upload() {
      const store = await getStore();
      const r = await runUploadWorker({ store, sink: getApi() });
      await refreshSyncStatus();
      if (r.uploaded > 0) queryClient.invalidateQueries();
    },
  });
  return scheduler;
}

export const useSync = create<SyncStatus & { run(): Promise<void>; refreshStatus(): Promise<void> }>((set) => ({
  syncing: false,
  lastSyncMs: null,
  message: null,
  error: null,
  waitingToUpload: 0,
  caneState: 'unknown',
  refreshStatus: refreshSyncStatus,
  /** The "Sync now" button: pull (this also re-enables automatic pulls), then upload. */
  async run() {
    set({ syncing: true, error: null, message: null });
    const sch = getScheduler();
    const r = await sch.pullNow();
    if (!r.ok) {
      const e = r.error;
      set({ error: `Could not reach the cane: ${e instanceof Error ? e.message : String(e)}. Nothing was lost; try again nearby.` });
      await sch.uploadNow();
    }
    await refreshSyncStatus();
    set({ syncing: false });
    queryClient.invalidateQueries();
  },
}));

/**
 * Runs the timers only while the app is in the foreground, signed in, and (for patients/caregivers)
 * past the consent screen: nothing is sent to the backend before consent.
 */
export function useForegroundSync() {
  const user = useApp((s) => s.user);
  const allowed = !!user && !pendingConsent(user);
  useEffect(() => {
    if (!allowed) { scheduler?.stop(); return; }
    const sch = getScheduler();
    const apply = (st: string) => {
      if (st === 'active') {
        sch.start();
        void sch.uploadNow();
        void refreshSyncStatus();
      } else {
        sch.stop();
      }
    };
    apply(AppState.currentState ?? 'active');
    const sub = AppState.addEventListener('change', apply);
    return () => { sub.remove(); sch.stop(); };
  }, [allowed]);
}
