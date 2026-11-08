// Shared types. Field names follow MASTER.md sections 7.4 and 13.2.

export type TimeQuality = 'synced' | 'unsynced' | 'corrected';

export interface CaneInfo {
  device_id: string;
  fw_version: string;
  last_seq: number;
  unsynced_count: number;
  sensor_model: string;
}

export interface MinuteRecord {
  type: 'minute';
  seq: number;
  boot_id: string;
  ts: string;
  time_quality: TimeQuality;
  n_samples: number;
  mag_mean: number;
  mag_std: number;
  mag_max: number;
  dyn_mean: number;
  active_s: number;
  strike_count: number;
  strike_iv_mean: number | null;
  strike_iv_cv: number | null;
  upright_s: number;
  flat_s: number;
  max_impact_g: number;
}

export type EventKind = 'potential_fall' | 'help_press' | 'sensor_fault';
export type EventOutcome = 'cancelled_by_user' | 'unanswered' | 'help_requested' | 'none';

export interface CaneEventRecord {
  type: 'event';
  seq: number;
  event_id: string;
  boot_id: string;
  ts: string;
  time_quality: TimeQuality;
  kind: EventKind;
  outcome: EventOutcome;
  confidence: number;
  peak_g: number;
  tilt_deg: number;
  still_s: number;
  raw_snippet_b64: string | null;
}

export type CaneRecord = MinuteRecord | CaneEventRecord;

export interface PullPage {
  records: CaneRecord[];
  nextCursor: number;
  more: boolean;
}

export interface LiveSample {
  ts: string;
  mag: number;
  dyn: number;
  state: 'idle' | 'walking' | 'flat' | 'impact';
  strikes_last_10s: number;
}

export interface IngestBatch {
  batch_id: string;
  device_id: string;
  fw_version: string;
  records: CaneRecord[];
}

export interface IngestResponse {
  batch_id: string;
  received: number;
  inserted: number;
  duplicates: number;
  rejected: { seq: number; reason: string }[];
  server_max_seq: number;
}
