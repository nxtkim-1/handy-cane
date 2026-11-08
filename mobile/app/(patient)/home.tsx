import React, { useEffect } from 'react';
import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Body, Button, Card, H1, H2, Loading, Screen, SimulatedBadge } from '../../src/ui/kit';
import { getApi, useApp, useSync } from '../../src/state/services';
import { ACTIVE_LABEL, USUAL_TEXT, fmtAgo, last7Text } from '../../src/ui/format';

export default function Home() {
  const router = useRouter();
  const user = useApp((s) => s.user)!;
  const pid = useApp((s) => s.activePatientId)!;
  const sync = useSync();
  useEffect(() => { sync.refreshStatus(); }, []);
  const q = useQuery({ queryKey: ['overview', pid], queryFn: () => getApi().overview(pid) });

  if (q.isLoading || !q.data) return <Screen><Loading /></Screen>;
  const o = q.data;
  const down = o.change_flags.find((f) => f.direction === 'down');

  return (
    <Screen>
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
        <Body>{o.open_events > 0 ? `${o.open_events} potential fall or cane drop alert(s) need a look.` : 'No open alerts.'}</Body>
        <Button label="See alerts" kind="secondary" onPress={() => router.push('/alerts')} />
      </Card>

      <Card>
        <H2>Cane</H2>
        <Body>Last synced: {fmtAgo(sync.lastSyncMs)}</Body>
        <Button label="Sync now" loading={sync.syncing} onPress={() => sync.run()} />
      </Card>

      {o.latest_report && (
        <Card>
          <H2>Latest report</H2>
          <Body>For the period ending {o.latest_report.period_end}</Body>
          <Button label="Read report" kind="secondary" onPress={() => router.push('/reports')} />
        </Card>
      )}
    </Screen>
  );
}
