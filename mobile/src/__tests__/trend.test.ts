import { makeDailySeries } from '../api/MockApiClient';
import type { DailyMetric } from '../api/types';
import {
  bandOf, computeBaseline, coverageCaption, lineSegments, median, toTrendPoints, yDomain,
} from '../charts/trend';

const d = (day: string, valid: boolean, v: number | null): DailyMetric => ({
  day, valid, coverage_h: valid ? 11 : 3, active_min: v, strikes: v === null ? null : v * 38,
});

describe('no-data is not zero', () => {
  test('invalid days become null values, even if a number leaked through', () => {
    const pts = toTrendPoints([d('2026-01-01', true, 60), d('2026-01-02', false, 0), d('2026-01-03', false, null)]);
    expect(pts.map((p) => p.value)).toEqual([60, null, null]);
    expect(pts.map((p) => p.noData)).toEqual([false, true, true]);
  });

  test('a genuine valid day with 0 active minutes stays 0 (cane not used is data)', () => {
    const pts = toTrendPoints([d('2026-01-01', true, 0)]);
    expect(pts[0].value).toBe(0);
    expect(pts[0].noData).toBe(false);
  });

  test('no-data days break the line into segments instead of dipping to zero', () => {
    const pts = toTrendPoints([
      d('2026-01-01', true, 60), d('2026-01-02', true, 62), d('2026-01-03', false, null),
      d('2026-01-04', true, 58), d('2026-01-05', false, null),
    ]);
    const segs = lineSegments(pts);
    expect(segs.map((s) => s.map((p) => p.day))).toEqual([
      ['2026-01-01', '2026-01-02'], ['2026-01-04'],
    ]);
  });

  test('baseline ignores invalid days and y-domain is not dragged to zero', () => {
    const days = [d('1', true, 60), d('2', false, null), d('3', true, 64), d('4', true, 62), d('5', false, null)];
    const b = computeBaseline(days)!;
    expect(b.median).toBe(62);
    expect(b.mad).toBe(2);
    const [lo] = yDomain(toTrendPoints(days), bandOf(b));
    expect(lo).toBeGreaterThan(50);
  });

  test('baseline needs enough valid days', () => {
    expect(computeBaseline([d('1', true, 60), d('2', false, null)])).toBeNull();
  });

  test('median', () => {
    expect(median([])).toBeNull();
    expect(median([3, 1, 2])).toBe(2);
    expect(median([1, 2, 3, 4])).toBe(2.5);
  });

  test('caption says less data than usual, and mock series contains no zero-for-missing', () => {
    const pts = toTrendPoints(makeDailySeries(new Date('2026-11-08T12:00:00Z')));
    expect(coverageCaption(pts)).toMatch(/^Less data than usual/);
    expect(pts.some((p) => p.noData)).toBe(true);
    expect(pts.filter((p) => p.noData).every((p) => p.value === null)).toBe(true);
  });
});
