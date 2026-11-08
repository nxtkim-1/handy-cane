import type { CaneTransport } from '../comm/CaneTransport';
import type { LocalStore } from '../db/LocalStore';
import type { CaneInfo } from '../types';

export function uuid4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export interface PullSyncOptions {
  transport: CaneTransport;
  store: LocalStore;
  now?: () => number;
  pageLimit?: number;
  newId?: () => string;
  onProgress?: (p: { pulled: number; cursor: number }) => void;
}

export interface PullSyncResult {
  info: CaneInfo;
  pages: number;
  inserted: number;
  duplicates: number;
  cursor: number;
}

export const META_LAST_SYNC = 'last_sync_ms';

/**
 * Pull loop per MASTER 7.4: HELLO, TIME_SYNC, then PULL pages from the stored
 * cursor. Each page is written in ONE store transaction (records + cursor +
 * upload batch); ACK is sent only after that write succeeded. If anything
 * throws mid-way, the committed cursor stays where it was and the next call
 * resumes from it. Re-sent records are ignored by (device_id, seq).
 */
export async function runPullSync(opts: PullSyncOptions): Promise<PullSyncResult> {
  const { transport, store } = opts;
  const now = opts.now ?? Date.now;
  const limit = opts.pageLimit ?? 500;
  const newId = opts.newId ?? uuid4;

  const info = await transport.connect();
  await transport.timeSync(now());

  let cursor = await store.getCursor(info.device_id);
  let pages = 0;
  let inserted = 0;
  let duplicates = 0;

  for (;;) {
    const page = await transport.pull(cursor, limit);
    const res = await store.applyPage({
      deviceId: info.device_id,
      fwVersion: info.fw_version,
      records: page.records,
      nextCursor: Math.max(cursor, page.nextCursor),
      batchId: newId(),
    });
    pages++;
    inserted += res.inserted;
    duplicates += res.duplicates;
    const newCursor = Math.max(cursor, page.nextCursor);
    // durable now: safe to ack
    if (newCursor > 0) await transport.ack(newCursor);
    const advanced = newCursor > cursor;
    cursor = newCursor;
    opts.onProgress?.({ pulled: inserted + duplicates, cursor });
    if (!page.more) break;
    if (!advanced) throw new Error('Cane reported more data but the cursor did not advance');
  }

  await store.setMeta(META_LAST_SYNC, String(now()));
  return { info, pages, inserted, duplicates, cursor };
}
