import type { IngestBatch, IngestResponse } from '../types';
import { IngestError } from '../sync/uploadWorker';
import {
  adaptBaseline, adaptDaily, adaptEvent, adaptOverview, adaptPatientListItem, adaptReport, adaptUser,
} from './adapt';
import type {
  Baseline, DailyMetric, EventItem, Overview, Patient, PatientListItem, Report, Tokens, User,
} from './types';

export interface ApiClient {
  login(email: string, password: string): Promise<{ user: User; tokens: Tokens }>;
  me(): Promise<User>;
  patients(): Promise<PatientListItem[]>;
  overview(pid: string): Promise<Overview>;
  daily(pid: string, from: string, to: string): Promise<DailyMetric[]>;
  baseline(pid: string): Promise<Baseline | null>;
  events(pid: string, status?: string): Promise<EventItem[]>;
  patchEvent(
    eventId: string,
    body: { status: 'acknowledged' | 'dismissed'; reason?: string; note?: string },
  ): Promise<EventItem>;
  reports(pid: string): Promise<Report[]>;
  generateReport(pid: string, periodEnd: string): Promise<Report>;
  postIngestBatch(batch: IngestBatch): Promise<IngestResponse>;
  setTokens(t: Tokens | null): void;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

type FetchFn = (url: string, init?: any) => Promise<{ ok: boolean; status: number; json(): Promise<any> }>;

/** Real backend client (MASTER 13). Access token in memory, one refresh retry on 401. */
export class HttpApiClient implements ApiClient {
  private tokens: Tokens | null = null;
  onTokens?: (t: Tokens | null) => void;

  constructor(private baseUrl: string, private fetchImpl: FetchFn = (u, i) => fetch(u, i) as any) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  setTokens(t: Tokens | null) { this.tokens = t; }

  private async raw(method: string, path: string, body?: unknown, auth = true): Promise<any> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (auth && this.tokens) headers.Authorization = `Bearer ${this.tokens.access_token}`;
    const res = await this.fetchImpl(this.baseUrl + path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
    return res;
  }

  private async call<T>(method: string, path: string, body?: unknown, auth = true): Promise<T> {
    let res = await this.raw(method, path, body, auth);
    if (res.status === 401 && auth && this.tokens?.refresh_token) {
      const r = await this.raw('POST', '/v1/auth/refresh', { refresh_token: this.tokens.refresh_token }, false);
      if (r.ok) {
        const j = await r.json();
        this.tokens = { ...this.tokens, access_token: j.access_token };
        this.onTokens?.(this.tokens);
        res = await this.raw(method, path, body, auth);
      }
    }
    if (!res.ok) {
      let code = 'http_error', message = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        code = j?.error?.code ?? code;
        message = j?.error?.message ?? message;
      } catch { /* ignore */ }
      throw new ApiError(res.status, code, message);
    }
    return (await res.json()) as T;
  }

  async login(email: string, password: string) {
    const t = await this.call<Tokens>('POST', '/v1/auth/login', { email, password }, false);
    this.tokens = t;
    const user = await this.me();
    return { user, tokens: t };
  }
  // The backend's JSON differs from the app's types; adapt.ts maps it (tested on recorded responses).
  async me(): Promise<User> { return adaptUser(await this.call<any>('GET', '/v1/me')); }
  async patients(): Promise<PatientListItem[]> {
    const rows = await this.call<any[]>('GET', '/v1/patients');
    return Promise.all(rows.map(async (p) => {
      try {
        return adaptPatientListItem(p, await this.call<any>('GET', `/v1/patients/${p.patient_id}/overview`));
      } catch {
        return adaptPatientListItem(p);
      }
    }));
  }
  async overview(pid: string): Promise<Overview> {
    return adaptOverview(await this.call<any>('GET', `/v1/patients/${pid}/overview`));
  }
  async daily(pid: string, from: string, to: string): Promise<DailyMetric[]> {
    return adaptDaily(await this.call<any[]>('GET', `/v1/patients/${pid}/daily?from=${from}&to=${to}`));
  }
  async baseline(pid: string): Promise<Baseline | null> {
    return adaptBaseline(await this.call<any>('GET', `/v1/patients/${pid}/baseline`));
  }
  async events(pid: string, status?: string): Promise<EventItem[]> {
    const rows = await this.call<any[]>('GET', `/v1/patients/${pid}/events${status ? `?status=${status}` : ''}`);
    return rows.map(adaptEvent);
  }
  async patchEvent(eventId: string, body: { status: 'acknowledged' | 'dismissed'; reason?: string; note?: string }): Promise<EventItem> {
    return adaptEvent(await this.call<any>('PATCH', `/v1/events/${eventId}`, body));
  }
  async reports(pid: string): Promise<Report[]> {
    return (await this.call<any[]>('GET', `/v1/patients/${pid}/reports`)).map(adaptReport);
  }
  async generateReport(pid: string, periodEnd: string): Promise<Report> {
    // POST returns 202 {report_id, status}; the report body comes from GET /v1/reports/{id}.
    const g = await this.call<{ report_id: string }>('POST', `/v1/patients/${pid}/reports/generate`, { period_end: periodEnd });
    return adaptReport(await this.call<any>('GET', `/v1/reports/${g.report_id}`));
  }
  async postIngestBatch(batch: IngestBatch): Promise<IngestResponse> {
    try {
      return await this.call<IngestResponse>('POST', '/v1/ingest/batches', batch);
    } catch (e) {
      if (e instanceof ApiError) throw new IngestError(e.status, e.message);
      throw new IngestError(null, e instanceof Error ? e.message : 'network error');
    }
  }
}

export type { Patient };
