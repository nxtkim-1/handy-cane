import type { Baseline, DailyMetric } from '../api/types';

export interface TrendPoint {
  day: string;
  /** null = no data (grey), never zero. */
  value: number | null;
  noData: boolean;
}

export interface Band {
  low: number;
  high: number;
  median: number;
}

/** Valid days become values; invalid days (or null values) become explicit no-data points. */
export function toTrendPoints(days: DailyMetric[]): TrendPoint[] {
  return [...days]
    .sort((a, b) => a.day.localeCompare(b.day))
    .map((d) => {
      const has = d.valid && d.active_min !== null && d.active_min !== undefined;
      return { day: d.day, value: has ? (d.active_min as number) : null, noData: !has };
    });
}

/** Contiguous runs of real values. A no-data day BREAKS the line; it is never drawn as zero. */
export function lineSegments(points: TrendPoint[]): TrendPoint[][] {
  const out: TrendPoint[][] = [];
  let cur: TrendPoint[] = [];
  for (const p of points) {
    if (p.value === null) {
      if (cur.length) out.push(cur);
      cur = [];
    } else {
      cur.push(p);
    }
  }
  if (cur.length) out.push(cur);
  return out;
}

export function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** Median +/- MAD from the first `window` VALID days (MASTER 10.4 / 15.5). */
export function computeBaseline(days: DailyMetric[], window = 14): Baseline | null {
  const vals = toTrendPoints(days)
    .filter((p) => p.value !== null)
    .slice(0, window)
    .map((p) => p.value as number);
  const med = median(vals);
  if (med === null || vals.length < 3) return null;
  const mad = median(vals.map((v) => Math.abs(v - med))) as number;
  return {
    metric: 'active_min',
    median: med,
    mad,
    description: `Your usual = your median over your first ${vals.length} days with enough data`,
  };
}

export function bandOf(b: Baseline | null): Band | null {
  return b ? { low: Math.max(0, b.median - b.mad), high: b.median + b.mad, median: b.median } : null;
}

/** Y domain from real values and the band only: no-data days never pull the axis to 0. */
export function yDomain(points: TrendPoint[], band: Band | null): [number, number] {
  const nums = points.filter((p) => p.value !== null).map((p) => p.value as number);
  if (band) nums.push(band.low, band.high);
  if (nums.length === 0) return [0, 1];
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const pad = (hi - lo || 1) * 0.15;
  return [Math.max(0, lo - pad), hi + pad];
}

export function noDataCount(points: TrendPoint[]): number {
  return points.filter((p) => p.noData).length;
}

/** Plain-language caption: "Less data than usual", never a blank chart. */
export function coverageCaption(points: TrendPoint[]): string {
  const n = noDataCount(points);
  if (points.length === 0) return 'No data yet.';
  if (n === 0) return 'Enough data on every day shown.';
  if (n === points.length) return 'Not enough data on any day shown.';
  return `Less data than usual: ${n} of ${points.length} days had too little cane data (shown in grey).`;
}
