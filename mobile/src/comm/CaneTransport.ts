import type { CaneEventRecord, CaneInfo, LiveSample, PullPage } from '../types';

/** Transport-agnostic cane link (MASTER 15.1). The phone always initiates. */
export interface CaneTransport {
  /** HELLO / INFO */
  connect(): Promise<CaneInfo>;
  /** TIME_SYNC */
  timeSync(phoneUtcMs: number): Promise<void>;
  /** PULL */
  pull(afterSeq: number, limit: number): Promise<PullPage>;
  /** ACK: only call after the page is durably stored. */
  ack(upToSeq: number): Promise<void>;
  /** Push alerts (BLE notify). HTTP transport cannot push and returns a no-op. */
  onAlert(cb: (e: CaneEventRecord) => void): () => void;
  /** Optional live view for demos. */
  live?(): Promise<LiveSample>;
  disconnect(): Promise<void>;
}
