import React, { useState } from 'react';
import { View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DISMISS_REASONS, type EventItem, type Report } from '../api/types';
import { getApi, getStore } from '../state/services';
import { Badge, Body, Button, Card, Chip, ErrorText, H2, Loading, SimulatedBadge, colors } from './kit';
import { eventTitle, fmtDateTime, outcomeText } from './format';
import { ActivityBars, TrendChart } from './charts';
import { bandOf, computeBaseline, toTrendPoints } from '../charts/trend';

export function useDaily(pid: string, days = 56) {
  return useQuery({
    queryKey: ['daily', pid, days],
    queryFn: async () => {
      const to = new Date();
      const from = new Date(to.getTime() - days * 86400_000);
      const rows = await getApi().daily(pid, from.toISOString().slice(0, 10), to.toISOString().slice(0, 10));
      const baseline = (await getApi().baseline(pid)) ?? computeBaseline(rows);
      return { points: toTrendPoints(rows), baseline };
    },
  });
}

export function TrendSection({ pid, weeks = 8 }: { pid: string; weeks?: number }) {
  const q = useDaily(pid, weeks * 7);
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Body>Could not load the trend. Pull down to try again.</Body>;
  return (
    <View style={{ gap: 8 }}>
      <TrendChart points={q.data.points} band={bandOf(q.data.baseline)} />
      <Body sub>{q.data.baseline?.description ?? 'Not enough days with data to show your usual yet.'}</Body>
    </View>
  );
}

export function WeekBars({ pid, days = 14 }: { pid: string; days?: number }) {
  const q = useDaily(pid, days);
  if (q.isLoading) return <Loading />;
  if (!q.data) return null;
  return <ActivityBars points={q.data.points.slice(-days)} />;
}

export function AlertsList({
  pid, canDismiss, canAcknowledge = true,
}: { pid: string; canDismiss: boolean; canAcknowledge?: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['events', pid],
    queryFn: async () => {
      try {
        const rows = await getApi().events(pid);
        (await getStore()).putCache('events', pid, JSON.stringify(rows)).catch(() => {});
        return rows;
      } catch (e) {
        const cached = await (await getStore()).getCache('events', pid);
        if (cached) return JSON.parse(cached) as EventItem[];
        throw e;
      }
    },
  });
  const [dismissing, setDismissing] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const patch = useMutation({
    mutationFn: (v: { id: string; status: 'acknowledged' | 'dismissed'; reason?: string }) =>
      getApi().patchEvent(v.id, { status: v.status, reason: v.reason }),
    onSuccess: () => {
      setDismissing(null);
      setReason(null);
      setError(null);
      qc.invalidateQueries({ queryKey: ['events', pid] });
      qc.invalidateQueries({ queryKey: ['overview', pid] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : 'Something went wrong.'),
  });

  if (q.isLoading) return <Loading />;
  if (!q.data || q.data.length === 0) return <Body>No alerts. Nothing needs your attention.</Body>;

  return (
    <View style={{ gap: 12 }}>
      {q.data.map((e) => (
        <Card key={e.event_id} tone={e.status === 'open' ? 'warn' : undefined}>
          <H2>{eventTitle(e)}</H2>
          <Body>{fmtDateTime(e.ts)}</Body>
          <Body sub>{outcomeText(e.outcome)}</Body>
          {e.time_quality === 'unsynced' && <Badge text="TIME UNCERTAIN" color={colors.warn} />}
          <Body>
            Status: {e.status === 'open' ? 'Needs a look' : e.status === 'acknowledged' ? 'Seen' : 'Dismissed'}
          </Body>
          {e.status === 'dismissed' && (
            <Body sub>
              Reason: {DISMISS_REASONS.find((r) => r.code === e.dismiss_reason)?.label ?? e.dismiss_reason}
              {e.note ? ` (${e.note})` : ''}
            </Body>
          )}
          {e.status === 'open' && canAcknowledge && (
            <Button label="I have seen this" kind="secondary"
              onPress={() => patch.mutate({ id: e.event_id, status: 'acknowledged' })} />
          )}
          {e.status !== 'dismissed' && canDismiss && dismissing !== e.event_id && (
            <Button label="Dismiss with a reason" kind="secondary"
              hint="Alerts are never deleted. You choose why it can be dismissed."
              onPress={() => { setDismissing(e.event_id); setReason(null); setError(null); }} />
          )}
          {dismissing === e.event_id && (
            <View accessibilityRole="radiogroup">
              <Body>Why can this be dismissed?</Body>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
                {DISMISS_REASONS.map((r) => (
                  <Chip key={r.code} label={r.label} selected={reason === r.code} onPress={() => setReason(r.code)} />
                ))}
              </View>
              <ErrorText>{error}</ErrorText>
              <Button label="Confirm dismiss" disabled={!reason} loading={patch.isPending}
                onPress={() => reason && patch.mutate({ id: e.event_id, status: 'dismissed', reason })} />
              <Button label="Cancel" kind="secondary" onPress={() => setDismissing(null)} />
            </View>
          )}
        </Card>
      ))}
    </View>
  );
}

export function ReportCard({ r }: { r: Report }) {
  return (
    <Card>
      <SimulatedBadge show={r.is_simulated} />
      <H2>{r.period_start} to {r.period_end}</H2>
      {r.status === 'fallback' && <Badge text="TEMPLATE REPORT" color={colors.warn} />}
      {r.status === 'insufficient_data' && <Badge text="NOT ENOUGH DATA" color={colors.warn} />}
      <Body style={{ fontWeight: '700' }}>{r.headline}</Body>
      {r.sections.map((s) => (
        <View key={s.title}>
          <Body style={{ fontWeight: '700' }}>{s.title}</Body>
          <Body>{s.body}</Body>
        </View>
      ))}
    </Card>
  );
}

export function ReportsList({ pid, canGenerate }: { pid: string; canGenerate: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['reports', pid],
    queryFn: async () => {
      try {
        const rows = await getApi().reports(pid);
        (await getStore()).putCache('reports', pid, JSON.stringify(rows)).catch(() => {});
        return { rows, offline: false };
      } catch (e) {
        const cached = await (await getStore()).getCache('reports', pid);
        if (cached) return { rows: JSON.parse(cached) as Report[], offline: true };
        throw e;
      }
    },
  });
  const gen = useMutation({
    mutationFn: () => getApi().generateReport(pid, new Date().toISOString().slice(0, 10)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reports', pid] }),
  });
  if (q.isLoading) return <Loading />;
  return (
    <View style={{ gap: 12 }}>
      {q.data?.offline && <Badge text="SAVED COPY (OFFLINE)" color={colors.warn} />}
      {canGenerate && <Button label="Generate report now" loading={gen.isPending} onPress={() => gen.mutate()} />}
      {(q.data?.rows ?? []).length === 0 && <Body>No reports yet.</Body>}
      {(q.data?.rows ?? []).map((r) => <ReportCard key={r.report_id} r={r} />)}
    </View>
  );
}
