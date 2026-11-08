import React from 'react';
import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import {
  Body, Button, Card, ErrorBox, H1, H2, HighAlertBanner, Loading, Screen, SimulatedBadge,
} from '../../src/ui/kit';
import { getApi, useApp, useSync } from '../../src/state/services';
import { ACTIVE_LABEL, USUAL_TEXT, last7Text } from '../../src/ui/format';
import { SyncStatusLines, usePullRefresh } from '../../src/ui/parts';
import { highAlertText } from '../../src/api/severity';

export default function Home() {
  const router = useRouter();
  const user = useApp((s) => s.user)!;
  const pid = useApp((s) => s.activePatientId)!;
  const sync = useSync();
  const refresh = usePullRefresh();
  const q = useQuery({ queryKey: ['overview', pid], queryFn: () => getApi().overview(pid) });

  if (q.isLoading) return <Screen><Loading /></Screen>;
  if (q.isError || !q.data) {
    return (
      <Screen onRefresh={refresh.onRefresh} refreshing={refresh.refreshing}>
        <H1>Hello, {user.display_name}</H1>
        <ErrorBox message="Could not load your summary. Check your connection." onRetry={() => q.refetch()} />
        <SyncStatusLines />
      </Screen>
    );
  }
  const o = q.data;
  const down = o.change_flags.find((f) => f.direction === 'down');
  const high = o.open_events_by_severity.high;

  return (
    <Screen onRefresh={refresh.onRefresh} refreshing={refresh.refreshing}>
      {high > 0 && <HighAlertBanner text={highAlertText(high)} onPress={() => router.push('/alerts')} />}
      <H1>Hello, {user.display_name}</H1>
      <SimulatedBadge show={o.patient.is_simulated} />

      <Card>
        <H2>{ACTIVE_LABEL} today</H2>
        {o.today.active_min === null ? (
          <Body>Not enough data yet today.</Body>
        ) : (
          <Body>{o.today.active_min} min so far ({o.today.coverage_h} h of cane data)</Body>
        )}
        <Body sub>
          {last7Text(o.last_7_valid_days.active_min_median)}
        </Body>
        <Body sub>{USUAL_TEXT}</Body>
        {down && <Body>Less cane-active time than usual since {down.since}. This may mean you walked without the cane.</Body>}
      </Card>

      <Card tone={o.open_events > 0 ? 'warn' : undefined}>
        <H2>Alerts</H2>
        <Body>{o.open_events > 0 ? `${o.open_events} open alert${o.open_events === 1 ? '' : 's'} need${o.open_events === 1 ? 's' : ''} a look.` : 'No open alerts.'}</Body>
        <Button label="See alerts" kind="secondary" onPress={() => router.push('/alerts')} />
      </Card>

      <Card>
        <H2>Cane</H2>
        <SyncStatusLines />
        <Button label="Sync now" loading={sync.syncing} onPress={() => sync.run()} />
      </Card>

      {o.latest_report ? (
        <Card>
          <H2>Latest report</H2>
          <Body>For the period ending {o.latest_report.period_end}</Body>
          <Button label="Read report" kind="secondary" onPress={() => router.push('/reports')} />
        </Card>
      ) : (
        <Card>
          <H2>Latest report</H2>
          <Body sub>No report yet. One is written after about two weeks of cane data.</Body>
        </Card>
      )}
    </Screen>
  );
}
