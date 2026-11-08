import { CUE_KEYS } from './cueMap';

const MAX_QUEUE = 2;

export interface CueSession {
  baseUrl: string;
  cookie: string;
}

export interface CuePlaying {
  play(key: string, session: CueSession): void;
}

/**
 * Plays cane voice clips. Clips are fetched once from the cane over the local
 * network (with the session cookie) and cached in the app's document directory.
 * They are never bundled with the app or committed to the repo.
 * expo modules are loaded lazily so this file is import-safe under jest.
 */
export class CuePlayer implements CuePlaying {
  private queue: Array<{ key: string; session: CueSession }> = [];
  private running = false;

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
          const uri = await this.ensureClip(item.key, item.session);
          await this.playFile(uri);
        } catch (e) {
          console.warn(`[cues] could not play "${item.key}":`, e instanceof Error ? e.message : e);
        }
      }
    } finally {
      this.running = false;
    }
  }

  private async ensureClip(key: string, s: CueSession): Promise<string> {
    const FS = await import('expo-file-system/legacy');
    const dir = `${FS.documentDirectory}cues/`;
    const path = `${dir}${key}.mp3`;
    const info = await FS.getInfoAsync(path);
    if (info.exists) return path;
    await FS.makeDirectoryAsync(dir, { intermediates: true }).catch(() => {});
    const res = await FS.downloadAsync(`${s.baseUrl.replace(/\/+$/, '')}/voice/${key}.mp3`, path, {
      headers: { Cookie: s.cookie },
    });
    if (res.status !== 200) {
      await FS.deleteAsync(path, { idempotent: true }).catch(() => {});
      throw new Error(`clip download failed (HTTP ${res.status})`);
    }
    return path;
  }

  private async playFile(uri: string): Promise<void> {
    const { createAudioPlayer } = await import('expo-audio');
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

export const cuePlayer = new CuePlayer();
