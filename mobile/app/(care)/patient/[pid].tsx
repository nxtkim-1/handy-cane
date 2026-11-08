import React, { useState } from 'react';
import { useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import {
  Body, Card, ErrorBox, H1, H2, HighAlertBanner, Loading, Screen, Segmented, SimulatedBadge,
} from '../../../src/ui/kit';
import { AlertsList, ReportsList, TrendSection, usePullRefresh } from '../../../src/ui/parts';
import { getApi, useApp } from '../../../src/state/services';
import { ACTIVE_LABEL, USUAL_TEXT, fmtDateTime } from '../../../src/ui/format';
import { canDismissFor } from '../../../src/state/routes';
import { highAlertText } from '../../../src/api/severity';

type Section = 'overview' | 'trends' | 'alerts' | 'reports' | 'device';
const SECTIONS: { key: Section; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'trends', label: 'Trends' },
  { key: 'alerts', label: 'Alerts' },
  { key: 'reports', label: 'Reports' },
  { key: 'device', label: 'Device' },
];

export default function PatientDetail() {
  const { pid } = useLocalSearchParams<{ pid: string }>();
  const user = useApp((s) => s.user)!;
  const refresh = usePullRefresh();
  const [section, setSection] = useState<Section>('overview');
  const q = useQuery({ queryKey: ['overview', pid], queryFn: () => getApi().overview(pid) });

  if (q.isLoading) return <Screen><Loading /></Screen>;
  if (q.isError || !q.data) {
    return (
      <Screen onRefresh={refresh.onRefresh} refreshing={refresh.refreshing}>
        <ErrorBox message="Could not load this patient." onRetry={() => q.refetch()} />
      </Screen>
    );
  }
  const o = q.data;
  const high = o.open_events_by_severity.high;

  return (
    <Screen onRefresh={refresh.onRefresh} refreshing={refresh.refreshing}>
      {high > 0 && <HighAlertBanner text={highAlertText(high)} onPress={() => setSection('alerts')} />}
      <H1>{o.patient.display_name}</H1>
      <SimulatedBadge show={o.patient.is_simulated} />
      <Segmented options={SECTIONS} value={section} onChange={setSection} />

      {section === 'overview' && (
        <>
          <H2>Overview</H2>
          <Card>
            <Body>
              {ACTIVE_LABEL}, last 7 days with enough data: {o.last_7_valid_days.active_min_median ?? 'no data'} min per day
              (median, {o.last_7_valid_days.valid_days} days)
            </Body>
            <Body sub>{USUAL_TEXT}</Body>
            {o.change_flags.length === 0 && <Body sub>No change over time is flagged.</Body>}
            {o.change_flags.map((f) => (
              <Body key={f.metric}>
                {ACTIVE_LABEL} has been {f.direction === 'down' ? 'lower' : 'higher'} than usual since {f.since}. This may mean the cane was used less, not that mobility changed.
              </Body>
            ))}
          </Card>
          <Card tone={o.open_events > 0 ? 'warn' : undefined}>
            <Body>
              Open alerts: {o.open_events} ({o.open_events_by_severity.high} high, {o.open_events_by_severity.medium} medium, {o.open_events_by_severity.low} low)
            </Body>
          </Card>
        </>
      )}

      {section === 'trends' && (
        <>
          <H2>Trends (8 weeks)</H2>
          <TrendSection pid={pid} weeks={8} />
        </>
      )}

      {section === 'alerts' && (
        <>
          <H2>Alerts</H2>
          {!canDismissFor(user, pid) && (
            <Body sub>You can mark alerts as seen. Only the patient, or a caregiver they allow, can dismiss them.</Body>
          )}
          <AlertsList pid={pid} canDismiss={canDismissFor(user, pid)} />
        </>
      )}

      {section === 'reports' && (
        <>
          <H2>Reports</H2>
          <ReportsList pid={pid} canGenerate={user.role === 'clinician'} />
        </>
      )}

      {section === 'device' && (
        <>
          <H2>Device</H2>
          <Card>
            <Body>Cane: {o.device.device_id}</Body>
            <Body>Sensor: {o.device.sensor_model}</Body>
            <Body>Last seen: {o.device.last_seen_at ? fmtDateTime(o.device.last_seen_at) : 'never'}</Body>
            {o.device.unsynced_hint && <Body>The cane may hold data that has not been synced yet.</Body>}
          </Card>
          <EscalationHistory pid={pid} />
        </>
      )}
    </Screen>
  );
}

/** Who was told about which alert. If the call fails (older backend, no access) nothing is shown, not an error. */
function EscalationHistory({ pid }: { pid: string }) {
  const q = useQuery({ queryKey: ['escalations', pid], queryFn: () => getApi().escalations(pid), retry: false });
  if (q.isLoading) return <Loading />;
  if (!q.data || q.data.length === 0) return null;
  return (
    <Card>
      <H2>Escalation history</H2>
      {q.data.map((e, i) => (
        <Body key={`${e.event_id}-${e.sent_at}-${i}`}>
          {fmtDateTime(e.sent_at)}: {e.channel} {e.ok ? 'sent' : 'failed'} (attempt {e.attempt})
        </Body>
      ))}
    </Card>
  );
}
