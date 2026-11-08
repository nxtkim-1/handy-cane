import React from 'react';
import { Text, View } from 'react-native';
import Svg, { Line, Polyline, Rect, Circle } from 'react-native-svg';
import type { Band, TrendPoint } from '../charts/trend';
import { coverageCaption, lineSegments, yDomain } from '../charts/trend';
import { colors } from './kit';

const W = 340;
const H = 180;
const PAD = { l: 8, r: 8, t: 10, b: 22 };

/**
 * Cane-active time trend with the "usual" band (median +/- MAD). Days without
 * enough data are grey markers on the baseline axis and BREAK the line.
 */
export function TrendChart({ points, band }: { points: TrendPoint[]; band: Band | null }) {
  const [lo, hi] = yDomain(points, band);
  const n = Math.max(points.length, 2);
  const x = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const index = new Map(points.map((p, i) => [p.day, i]));
  const segs = lineSegments(points);

  return (
    <View accessible accessibilityLabel={`Cane-active time trend. ${coverageCaption(points)}`}>
      <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
        {band && (
          <Rect
            x={PAD.l} width={W - PAD.l - PAD.r} y={y(band.high)} height={Math.max(2, y(band.low) - y(band.high))}
            fill={colors.bandFill} />
        )}
        {band && (
          <Line x1={PAD.l} x2={W - PAD.r} y1={y(band.median)} y2={y(band.median)} stroke={colors.primary} strokeDasharray="4 4" strokeWidth={1.5} />
        )}
        <Line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} stroke={colors.border} strokeWidth={1} />
        {segs.map((s, k) => (
          <Polyline
            key={k}
            fill="none" stroke={colors.text} strokeWidth={2.5}
            points={s.map((p) => `${x(index.get(p.day) as number)},${y(p.value as number)}`).join(' ')}
          />
        ))}
        {points.map((p, i) =>
          p.value === null ? (
            <Rect key={p.day} x={x(i) - 3} y={H - PAD.b - 10} width={6} height={10} fill={colors.grey} />
          ) : (
            <Circle key={p.day} cx={x(i)} cy={y(p.value)} r={3} fill={colors.text} />
          ),
        )}
      </Svg>
      <Text style={{ fontSize: 16, color: colors.sub }}>
        Shaded band = your usual range. Grey marks = not enough cane data that day (not zero).
      </Text>
      <Text style={{ fontSize: 16, color: colors.text }}>{coverageCaption(points)}</Text>
    </View>
  );
}

/** Daily/weekly bars. No-data days are a grey outlined stub labelled as such, never an empty bar. */
export function ActivityBars({ points }: { points: TrendPoint[] }) {
  const max = Math.max(1, ...points.map((p) => p.value ?? 0));
  const bw = W / Math.max(points.length, 1);
  return (
    <View accessible accessibilityLabel={`Cane-active time per day. ${coverageCaption(points)}`}>
      <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
        {points.map((p, i) => {
          const bx = i * bw + bw * 0.15;
          const w = bw * 0.7;
          if (p.value === null) {
            return (
              <Rect key={p.day} x={bx} y={H - PAD.b - 14} width={w} height={14} fill="none"
                stroke={colors.grey} strokeWidth={2} strokeDasharray="3 3" />
            );
          }
          const h = (p.value / max) * (H - PAD.t - PAD.b);
          return <Rect key={p.day} x={bx} y={H - PAD.b - h} width={w} height={h} fill={colors.primary} />;
        })}
        <Line x1={0} x2={W} y1={H - PAD.b} y2={H - PAD.b} stroke={colors.border} />
      </Svg>
      <Text style={{ fontSize: 16, color: colors.text }}>{coverageCaption(points)}</Text>
    </View>
  );
}
