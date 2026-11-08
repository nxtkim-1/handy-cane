import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';
import type { ApiClient } from '../api/ApiClient';
import { HttpApiClient } from '../api/ApiClient';
import { MockApiClient } from '../api/MockApiClient';
import type { User } from '../api/types';
import type { CaneTransport } from '../comm/CaneTransport';
import { CueFeed } from '../cues/CueFeed';
import { HttpCaneTransport } from '../comm/HttpCaneTransport';
import { MockCaneTransport } from '../comm/MockCaneTransport';
import type { LocalStore } from '../db/LocalStore';
import { MemoryStore } from '../db/MemoryStore';
import { META_LAST_SYNC, runPullSync } from '../sync/pullSync';
import { runUploadWorker } from '../sync/uploadWorker';
import { queryClient } from './queryClient';

const ENV_API = process.env.EXPO_PUBLIC_API_URL;
const ENV_CANE = process.env.EXPO_PUBLIC_CANE_URL;
const ENV_FEED = process.env.EXPO_PUBLIC_CANE_FEED_URL;
const ENV_PAIR = process.env.EXPO_PUBLIC_CANE_PAIR_CODE;

interface AppState {
  /** mock = no backend, no hardware (default unless EXPO_PUBLIC_API_URL is set). */
  mock: boolean;
  apiUrl: string;
  caneUrl: string;
  feedUrl: string;
  pairCode: string;
  user: User | null;
  activePatientId: string | null;
  setConfig(c: Partial<Pick<AppState, 'mock' | 'apiUrl' | 'caneUrl' | 'feedUrl' | 'pairCode'>>): void;
  setUser(u: User | null): void;
}

export const useApp = create<AppState>((set) => ({
  mock: !ENV_API,
  apiUrl: ENV_API ?? 'http://10.0.2.2:8000',
  caneUrl: ENV_CANE ?? 'http://192.168.4.1:8080',
  feedUrl: ENV_FEED ?? '',
  pairCode: ENV_PAIR ?? '',
  user: null,
  activePatientId: null,
  setConfig: (c) => {
    api = null;
    transport = null;
    stopCueFeed();
    set(c);
  },
  setUser: (u) => set({ user: u, activePatientId: u?.patient_ids[0] ?? null }),
}));

let api: ApiClient | null = null;
let transport: CaneTransport | null = null;
let storePromise: Promise<LocalStore> | null = null;
let mockCane: MockCaneTransport | null = null;
let mockApi: MockApiClient | null = null;

export function getApi(): ApiClient {
  if (!api) {
    const s = useApp.getState();
    if (s.mock) {
      mockApi ??= new MockApiClient();
      api = mockApi;
    } else {
      api = new HttpApiClient(s.apiUrl);
    }
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

/** Spoken voice cues from the cane's event feed. Only runs when both feedUrl and pairCode are set. */
let cueFeed: CueFeed | null = null;
let cueStatus: string | null = null;
let cueStatusListener: ((s: string | null) => void) | null = null;

function emitCueStatus(s: string | null) {
  cueStatus = s;
  cueStatusListener?.(s);
}

export function setCueStatusListener(cb: ((s: string | null) => void) | null): void {
  cueStatusListener = cb;
}
export function getCueStatus(): string | null {
  return cueStatus;
}
export function isCueFeedRunning(): boolean {
  return cueFeed !== null;
}

export function stopCueFeed(): void {
  cueFeed?.stop();
  cueFeed = null;
  emitCueStatus(null);
}

export function getCueFeed(): CueFeed | null {
  const { feedUrl, pairCode } = useApp.getState();
  if (!cueFeed && feedUrl && pairCode) {
    cueFeed = new CueFeed({ baseUrl: feedUrl, pairCode, onStatus: emitCueStatus });
    cueFeed.start();
  }
  return cueFeed;
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

const REFRESH_KEY = 'smartcane_refresh_token';
export async function saveRefreshToken(t: string | null) {
  try {
    if (Platform.OS === 'web') return;
    if (t) await SecureStore.setItemAsync(REFRESH_KEY, t);
    else await SecureStore.deleteItemAsync(REFRESH_KEY);
  } catch { /* secure store unavailable: not fatal */ }
}

/** Clears the session and every cached screen so the next user never sees the last one's data. */
export async function signOut() {
  await saveRefreshToken(null);
  queryClient.clear();
  useApp.getState().setUser(null);
}

export interface SyncStatus {
  syncing: boolean;
  lastSyncMs: number | null;
  message: string | null;
  error: string | null;
  waitingToUpload: number;
}

export const useSync = create<SyncStatus & { run(): Promise<void>; refreshStatus(): Promise<void> }>((set) => ({
  syncing: false,
  lastSyncMs: null,
  message: null,
  error: null,
  waitingToUpload: 0,
  async refreshStatus() {
    const store = await getStore();
    const last = await store.getMeta(META_LAST_SYNC);
    const q = await store.queueStats();
    set({ lastSyncMs: last ? Number(last) : null, waitingToUpload: q.records });
  },
  async run() {
    set({ syncing: true, error: null, message: null });
    const store = await getStore();
    try {
      const pull = await runPullSync({ transport: getTransport(), store });
      set({ message: `Received ${pull.inserted} new records from the cane.` });
    } catch (e) {
      set({ error: `Could not reach the cane: ${e instanceof Error ? e.message : String(e)}. Nothing was lost; try again nearby.` });
    }
    try {
      await runUploadWorker({ store, sink: getApi() });
    } catch { /* queue retained */ }
    const last = await store.getMeta(META_LAST_SYNC);
    const q = await store.queueStats();
    set({ syncing: false, lastSyncMs: last ? Number(last) : null, waitingToUpload: q.records });
    // New alerts/records may have arrived: refresh every screen that shows them.
    queryClient.invalidateQueries();
  },
}));

// Start voice cues as soon as the app state module loads (no-op unless configured).
getCueFeed();
