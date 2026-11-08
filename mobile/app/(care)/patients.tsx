import React from 'react';
import { Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { Badge, Body, Button, Card, H1, H2, Loading, Screen, SimulatedBadge, colors } from '../../src/ui/kit';
import { getApi } from '../../src/state/services';
import { fmtDateTime } from '../../src/ui/format';

export default function Patients() {
  const router = useRouter();
  const q = useQuery({ queryKey: ['patients'], queryFn: () => getApi().patients() });
  return (
    <Screen>
      <H1>Your patients</H1>
      {q.isLoading && <Loading />}
      {q.data?.map((p) => (
        <Pressable
          key={p.patient_id}
          accessibilityRole="button"
          accessibilityLabel={`${p.display_name}. ${p.open_events} open alerts.`}
          onPress={() => router.push({ pathname: '/patient/[pid]', params: { pid: p.patient_id } })}
          style={{ minHeight: 48 }}
        >
          <Card tone={p.open_events > 0 ? 'warn' : undefined}>
            <H2>{p.display_name}</H2>
            <SimulatedBadge show={p.is_simulated} />
            {p.open_events > 0 && <Badge text={`${p.open_events} OPEN ALERT(S)`} color={colors.danger} />}
            {p.sustained_change && <Badge text="CHANGE OVER TIME" color={colors.warn} />}
            {p.stale_sync && <Badge text="NOT SYNCED RECENTLY" color={colors.warn} />}
            <Body sub>Last sync: {p.last_sync_at ? fmtDateTime(p.last_sync_at) : 'never'}</Body>
          </Card>
        </Pressable>
      ))}
    </Screen>
  );
}
