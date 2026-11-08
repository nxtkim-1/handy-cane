import type { CaneEventRecord, CaneInfo, LiveSample, PullPage } from '../types';
import type { CaneTransport } from './CaneTransport';

export type FetchLike = (
  url: string,
  init?: any,
) => Promise<{ ok: boolean; status: number; json(): Promise<any> }>;

export class CaneHttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** HTTP to the Pi (routes defined in mobile/PROTOCOL.md). */
export class HttpCaneTransport implements CaneTransport {
  private baseUrl: string;

  constructor(
    baseUrl: string,
    private fetchImpl: FetchLike = (u, i) => fetch(u, i) as any,
    private timeoutMs = 8000,
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  private async req<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), this.timeoutMs) : undefined;
    try {
      const res = await this.fetchImpl(this.baseUrl + path, {
        method,
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl?.signal,
      });
      if (!res.ok) throw new CaneHttpError(res.status, `Cane returned HTTP ${res.status}`);
      return (await res.json()) as T;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  connect(): Promise<CaneInfo> {
    return this.req<CaneInfo>('GET', '/info');
  }

  async timeSync(phoneUtcMs: number): Promise<void> {
    await this.req('POST', '/time', { phone_utc_ms: phoneUtcMs });
  }

  async pull(afterSeq: number, limit: number): Promise<PullPage> {
    const r = await this.req<{ records: PullPage['records']; next_cursor: number; more: boolean }>(
      'GET',
      `/pull?after_seq=${afterSeq}&limit=${limit}`,
    );
    return { records: r.records, nextCursor: r.next_cursor, more: r.more };
  }

  async ack(upToSeq: number): Promise<void> {
    await this.req('POST', '/ack', { up_to_seq: upToSeq });
  }

  onAlert(_cb: (e: CaneEventRecord) => void): () => void {
    return () => {};
  }

  live(): Promise<LiveSample> {
    return this.req<LiveSample>('GET', '/live');
  }

  async disconnect(): Promise<void> {}
}
