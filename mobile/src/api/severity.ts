/**
 * Alert severity. This is a TypeScript port of the backend's table so the demo (mock) backend ranks
 * alerts exactly like the real one. When the real backend sends `severity` the app uses that value as-is.
 *
 *   help_request                              -> high
 *   potential_fall + escalated                -> high
 *   potential_fall + acknowledged_on_cane     -> medium
 *   potential_fall + cancelled_by_user        -> medium if peak_g >= 3.0, else low
 *   impact_only                               -> low
 *   anything else                             -> medium
 */
export type Severity = 'high' | 'medium' | 'low';

export const PEAK_G_MEDIUM = 3.0;

export interface SeverityInfo {
  severity: Severity;
  reason: string;
}

export function severityFor(kind: string, outcome: string, peakG: number | null | undefined): SeverityInfo {
  // The cane firmware says help_request; the app's older name was help_press. 'unanswered' is the old name for 'escalated'.
  if (kind === 'help_request' || kind === 'help_press') {
    return { severity: 'high', reason: 'The help button was pressed on the cane.' };
  }
  if (kind === 'potential_fall') {
    if (outcome === 'escalated' || outcome === 'unanswered') {
      return { severity: 'high', reason: 'A possible fall was detected and nobody answered on the cane.' };
    }
    if (outcome === 'acknowledged_on_cane') {
      return { severity: 'medium', reason: 'A possible fall was detected and the alarm was switched off on the cane.' };
    }
    if (outcome === 'cancelled_by_user') {
      return (peakG ?? 0) >= PEAK_G_MEDIUM
        ? { severity: 'medium', reason: 'A possible fall was cancelled on the cane, but the impact was strong.' }
        : { severity: 'low', reason: 'A possible fall was cancelled on the cane after a light impact.' };
    }
  }
  if (kind === 'impact_only') {
    return { severity: 'low', reason: 'The cane was bumped or dropped, with no sign of a fall.' };
  }
  return { severity: 'medium', reason: 'This event does not fit a known pattern, so it is worth a look.' };
}

const RANK: Record<Severity, number> = { high: 0, medium: 1, low: 2 };
export const severityRank = (s: Severity) => RANK[s];

/** Server order: open first, then severity, then newest. The mock backend uses this; the app never re-sorts server data. */
export function sortEvents<T extends { status: string; severity: Severity; ts: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const open = Number(b.status === 'open') - Number(a.status === 'open');
    if (open) return open;
    const sev = RANK[a.severity] - RANK[b.severity];
    if (sev) return sev;
    return new Date(b.ts).getTime() - new Date(a.ts).getTime();
  });
}

export const SEVERITY_LABEL: Record<Severity, string> = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };

export function countBySeverity(rows: { status: string; severity: Severity }[]): Record<Severity, number> {
  const out = { high: 0, medium: 0, low: 0 };
  rows.forEach((r) => { if (r.status === 'open') out[r.severity]++; });
  return out;
}

export function highAlertText(n: number): string {
  return n === 1 ? '1 high-priority alert needs a look' : `${n} high-priority alerts need a look`;
}
