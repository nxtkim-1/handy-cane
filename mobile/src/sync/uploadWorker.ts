import type { LocalStore, QueueItem } from '../db/LocalStore';
import type { CaneRecord, IngestBatch, IngestResponse } from '../types';

export class IngestError extends Error {
  constructor(public status: number | null, message: string) {
    super(message);
  }
}

/** Uploader seam: ApiClient.postIngestBatch satisfies this. */
export interface IngestSink {
  postIngestBatch(batch: IngestBatch): Promise<IngestResponse>;
}

export const BACKOFF_BASE_MS = 5_000;
export const BACKOFF_MAX_MS = 15 * 60_000; // MASTER 17: max 15 min

const META_BACKOFF_UNTIL = 'upload_backoff_until_ms';
const META_FAILS = 'upload_consecutive_failures';

export function backoffMs(attempts: number): number {
  return Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempts));
}

/** 4xx other than auth/timeout/rate-limit means the payload itself is bad: do not retry forever. */
export function isPermanentFailure(status: number | null): boolean {
  if (status === null) return false;
  return status >= 400 && status < 500 && ![401, 403, 408, 429].includes(status);
}

export interface UploadResult {
  uploaded: number; // batches
  records: number;
  failed: boolean;
  error?: string;
  /** Records the server permanently rejected (HTTP 200 with rejected[]); dead-lettered, never retried. */
  rejected: { batch_id: string; seq: number; reason: string }[];
  remaining: { batches: number; records: number; dead: number };
}

/**
 * Drains due batches in seq order. On the first failure it records backoff on
 * that batch and stops (the backend is probably down; later batches would
 * fail too). The queue is persistent, so nothing is lost; the batch_id is
 * stable so a retry after a lost response is idempotent server-side.
 */
export async function runUploadWorker(opts: {
  store: LocalStore;
  sink: IngestSink;
  now?: () => number;
  maxBatches?: number;
}): Promise<UploadResult> {
  const now = opts.now ?? Date.now;
  // Queue-level backoff: after a failure nothing is retried until the wait is over.
  const until = Number((await opts.store.getMeta(META_BACKOFF_UNTIL)) ?? 0);
  if (now() < until) {
    return { uploaded: 0, records: 0, failed: false, rejected: [], remaining: await opts.store.queueStats() };
  }
  const due = await opts.store.dueBatches(now(), opts.maxBatches ?? 50);
  let uploaded = 0;
  let records = 0;
  let failed = false;
  let error: string | undefined;
  const rejected: UploadResult['rejected'] = [];

  for (const item of due) {
    try {
      const res = await opts.sink.postIngestBatch(toBatch(item));
      const rejects = res.rejected ?? [];
      if (rejects.length > 0) {
        // HTTP 200 but some/all records failed validation: permanent, keep them with reasons.
        await opts.store.deadLetterRecords(item.batch_id, rejects);
        rejects.forEach((r) => rejected.push({ batch_id: item.batch_id, seq: r.seq, reason: r.reason }));
      }
      // Accepted (inserted + duplicate) records are done; rejected ones are parked, so the batch leaves the queue.
      await opts.store.completeBatch(item.batch_id);
      const accepted = Math.max(0, item.record_count - rejects.length);
      if (accepted > 0) {
        uploaded++;
        records += accepted;
      }
    } catch (e) {
      const status = e instanceof IngestError ? e.status : null;
      error = e instanceof Error ? e.message : String(e);
      const permanent = isPermanentFailure(status);
      await opts.store.failBatch(item.batch_id, now() + backoffMs(item.attempts), error, permanent);
      failed = true;
      if (!permanent) {
        const fails = Number((await opts.store.getMeta(META_FAILS)) ?? 0);
        await opts.store.setMeta(META_FAILS, String(fails + 1));
        await opts.store.setMeta(META_BACKOFF_UNTIL, String(now() + backoffMs(fails)));
      }
      break;
    }
  }
  if (!failed && uploaded > 0) {
    await opts.store.setMeta(META_FAILS, '0');
    await opts.store.setMeta(META_BACKOFF_UNTIL, '0');
  }
  return { uploaded, records, failed, error, rejected, remaining: await opts.store.queueStats() };
}

function toBatch(item: QueueItem): IngestBatch {
  return {
    batch_id: item.batch_id,
    device_id: item.device_id,
    fw_version: item.fw_version,
    records: JSON.parse(item.payload) as CaneRecord[],
  };
}

/** User-readable status for server-rejected records (shown on the Cane screen). */
export function describeRejects(rejects: { seq: number; reason: string }[]): string | null {
  if (rejects.length === 0) return null;
  const n = rejects.length;
  const shown = rejects.slice(0, 3).map((r) => `seq ${r.seq}: ${r.reason}`).join('; ');
  return `${n} record${n === 1 ? ' was' : 's were'} permanently rejected by the server and will not be retried (${shown}${n > 3 ? `; and ${n - 3} more` : ''}). Please contact support.`;
}
