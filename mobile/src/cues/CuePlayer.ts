import { CUE_KEYS } from './cueMap';

const MAX_QUEUE = 2;

export interface CueSession {
  baseUrl: string;
  /** Bearer session token from POST /pair (never a cookie). */
  token: string;
}

export interface CuePlaying {
  play(key: string, session: CueSession): void;
}

/**
 * Plays cane voice clips. Clips are fetched once from the cane over the local
 * network (with the bearer session token) and cached in the app's document directory.
 * They are never bundled with the app or committed to the repo.
 * expo modules are loaded lazily so this file is import-safe under jest.
 */
export class CuePlayer implements CuePlaying {
  private queue: Array<{ key: string; session: CueSession }> = [];
  private running = false;
  /** Web only: key -> object URL of the fetched clip (native uses the file cache). */
  private blobUrls = new Map<string, string>();

  play(key: string, session: CueSession): void {
    if (!(CUE_KEYS as readonly string[]).includes(key)) return;
    this.queue.push({ key, session });
    while (this.queue.length > MAX_QUEUE) this.queue.shift(); // drop oldest
    if (!this.running) void this.drain();
  }

  private async drain(): Promise<void> {
    this.running = true;
    try {
      let item;
      while ((item = this.queue.shift())) {
        try {
          const web = isWeb();
          const uri = web
            ? await this.ensureWebClip(item.key, item.session)
            : await this.ensureClip(item.key, item.session);
          await this.playFile(uri);
        } catch (e) {
          const stale = this.blobUrls.get(item.key);
          if (stale) { URL.revokeObjectURL(stale); this.blobUrls.delete(item.key); }
          console.warn(`[cues] could not play "${item.key}":`, e instanceof Error ? e.message : e);
        }
      }
    } finally {
      this.running = false;
    }
  }

  /** Web: documentDirectory is null, so fetch with the bearer header and play from an object URL. */
  private async ensureWebClip(key: string, s: CueSession): Promise<string> {
    const cached = this.blobUrls.get(key);
    if (cached) return cached;
    const res = await fetch(`${s.baseUrl.replace(/\/+$/, '')}/voice/${key}.mp3`, {
      headers: { Authorization: `Bearer ${s.token}` },
    });
    if (!res.ok) throw new Error(`clip download failed (HTTP ${res.status})`);
    const url = URL.createObjectURL(await res.blob());
    this.blobUrls.set(key, url);
    return url;
  }

  /** Web: revoke all cached object URLs (e.g. on sign-out). */
  disposeWebCache(): void {
    for (const url of this.blobUrls.values()) URL.revokeObjectURL(url);
    this.blobUrls.clear();
  }

  private async ensureClip(key: string, s: CueSession): Promise<string> {
    const FS = require('expo-file-system/legacy') as typeof import('expo-file-system/legacy');
    const dir = `${FS.documentDirectory}cues/`;
    const path = `${dir}${key}.mp3`;
    const info = await FS.getInfoAsync(path);
    if (info.exists) return path;
    await FS.makeDirectoryAsync(dir, { intermediates: true }).catch(() => {});
    const res = await FS.downloadAsync(`${s.baseUrl.replace(/\/+$/, '')}/voice/${key}.mp3`, path, {
      headers: { Authorization: `Bearer ${s.token}` },
    });
    if (res.status !== 200) {
      await FS.deleteAsync(path, { idempotent: true }).catch(() => {});
      throw new Error(`clip download failed (HTTP ${res.status})`);
    }
    return path;
  }

  private async playFile(uri: string): Promise<void> {
    const { createAudioPlayer } = require('expo-audio') as typeof import('expo-audio');
    const player = createAudioPlayer({ uri });
    await new Promise<void>((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        sub.remove();
        clearTimeout(timer);
        try { player.remove(); } catch { /* already released */ }
        resolve();
      };
      const sub = player.addListener('playbackStatusUpdate', (st: { didJustFinish?: boolean }) => {
        if (st.didJustFinish) finish();
      });
      const timer = setTimeout(finish, 15000); // safety: never wedge the queue
      player.play();
    });
  }
}

function isWeb(): boolean {
  return (require('react-native') as typeof import('react-native')).Platform.OS === 'web';
}

export const cuePlayer = new CuePlayer();
