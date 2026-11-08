export type Role = 'patient' | 'caregiver' | 'clinician';

export interface User {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
  patient_ids: string[];
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
}

export interface Patient {
  patient_id: string;
  display_name: string;
  is_simulated: boolean;
  timezone: string;
}

export interface PatientListItem extends Patient {
  open_events: number;
  sustained_change: boolean;
  last_sync_at: string | null;
  stale_sync: boolean;
}

export interface DailyMetric {
  day: string; // YYYY-MM-DD in the patient's timezone
  valid: boolean;
  coverage_h: number;
  /** null when the day is not valid: NEVER 0 (MASTER 9.4). */
  active_min: number | null;
  strikes: number | null;
}

export interface Baseline {
  metric: 'active_min';
  median: number;
  mad: number;
  /** Plain-language definition of "usual". */
  description: string;
}

export interface Overview {
  patient: Patient;
  device: { device_id: string; last_seen_at: string | null; sensor_model: string; unsynced_hint: boolean };
  today: { day: string; valid_so_far: boolean; coverage_h: number; active_min: number | null; strikes: number | null };
  last_7_valid_days: { active_min_median: number | null; valid_days: number };
  open_events: number;
  latest_report: { report_id: string; period_end: string; status: string } | null;
  change_flags: { metric: string; direction: 'up' | 'down'; since: string }[];
}

export type EventStatus = 'open' | 'acknowledged' | 'dismissed';

export interface EventItem {
  event_id: string;
  ts: string;
  kind: 'potential_fall' | 'help_request' | 'impact_only';
  outcome: 'cancelled_by_user' | 'escalated' | 'acknowledged_on_cane';
  status: EventStatus;
  time_quality: 'synced' | 'unsynced' | 'corrected';
  dismiss_reason: string | null;
  note: string | null;
}

export const DISMISS_REASONS: { code: string; label: string }[] = [
  { code: 'false_alarm_dropped_cane', label: 'I dropped the cane' },
  { code: 'false_alarm_sat_down', label: 'I sat down quickly' },
  { code: 'i_am_fine', label: 'I am fine, no fall' },
  { code: 'other', label: 'Other reason' },
];

export interface ReportSection {
  title: string;
  body: string;
}

export interface Report {
  report_id: string;
  period_start: string;
  period_end: string;
  status: 'generated' | 'fallback' | 'insufficient_data' | 'pending';
  is_simulated: boolean;
  headline: string;
  sections: ReportSection[];
}
