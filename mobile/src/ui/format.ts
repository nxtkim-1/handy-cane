import type { EventItem } from '../api/types';

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export function fmtAgo(ms: number | null, now = Date.now()): string {
  if (ms === null) return 'never';
  const m = Math.round((now - ms) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

// MASTER 15.5 language rules
export function eventTitle(e: Pick<EventItem, 'kind'>): string {
  switch (e.kind) {
    case 'potential_fall': return 'Potential fall or cane drop';
    case 'help_request': return 'Help button pressed';
    case 'impact_only': return 'Bump or impact';
  }
}

export function outcomeText(o: EventItem['outcome']): string {
  switch (o) {
    case 'cancelled_by_user': return 'Cancelled on the cane';
    case 'escalated': return 'Not answered on the cane';
    case 'acknowledged_on_cane': return 'Alarm switched off on the cane';
  }
}

export const USUAL_TEXT = 'Your usual = your median over your first 2 weeks';
export const ACTIVE_LABEL = 'Cane-active time';
export const STEPS_LABEL = 'Cane steps';

/** Empty-data safe sentence for the 7-day median; never renders "null" or "no data min". */
export function last7Text(median: number | null): string {
  return median === null ? 'Not enough data yet.' : `Last 7 days with enough data: ${median} min per day (median).`;
}
