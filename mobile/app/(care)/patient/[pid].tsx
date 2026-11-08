import React from 'react';
import { useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Body, Card, H1, H2, Loading, Screen, SimulatedBadge } from '../../../src/ui/kit';
import { AlertsList, ReportsList, TrendSection } from '../../../src/ui/parts';
import { getApi, useApp } from '../../../src/state/services';
import { ACTIVE_LABEL, USUAL_TEXT, fmtDateTime } from '../../../src/ui/format';

export default function PatientDetail() {
  const { pid } = useLocalSearchParams<{ pid: string }>();
  const role = useApp((s) => s.user!.role);
  const q = useQuery({ queryKey: ['overview', pid], queryFn: () => getApi().overview(pid) });
  if (q.isLoading || !q.data) return <Screen><Loading /></Screen>;
  const o = q.data;

  return (
    <Screen>
      <H1>{o.patient.display_name}</H1>
      <SimulatedBadge show={o.patient.is_simulated} />

      <H2>Overview</H2>
      <Card>
        <Body>{o.last_7_valid_days.active_min_median === null ? `${ACTIVE_LABEL}: not enough data yet.` : `${ACTIVE_LABEL}, last 7 days with enough data: ${o.last_7_valid_days.active_min_median} min per day (median, ${o.last_7_valid_days.valid_days} days)`}</Body>
        <Body sub>{USUAL_TEXT}</Body>
        {o.change_flags.map((f) => (
          <Body key={f.metric}>
            {ACTIVE_LABEL} has been {f.direction === 'down' ? 'lower' : 'higher'} than usual since {f.since}. This may mean the cane was used less, not that mobility changed.
          </Body>
        ))}
      </Card>

      <H2>Trends (8 weeks)</H2>
      <TrendSection pid={pid} weeks={8} />

      <H2>Alerts</H2>
      <AlertsList pid={pid} canDismiss={false} />

      <H2>Reports</H2>
      <ReportsList pid={pid} canGenerate={role === 'clinician'} />

      <H2>Device</H2>
      <Card>
        <Body>Cane: {o.device.device_id}</Body>
        <Body>Sensor: {o.device.sensor_model}</Body>
        <Body>Last seen: {o.device.last_seen_at ? fmtDateTime(o.device.last_seen_at) : 'never'}</Body>
        {o.device.unsynced_hint && <Body>The cane may hold data that has not been synced yet.</Body>}
      </Card>
    </Screen>
  );
}
