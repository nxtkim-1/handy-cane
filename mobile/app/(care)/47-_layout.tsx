import React from 'react';
import { Redirect, Stack } from 'expo-router';
import { useApp } from '../../src/state/services';
import { pendingConsent } from '../../src/state/consent';
import { AppBar } from '../../src/ui/kit';

export default function CareLayout() {
  const user = useApp((s) => s.user);
  if (!user || pendingConsent(user)) return <Redirect href="/" />;
  return (
    <Stack screenOptions={{ header: ({ back }) => <AppBar back={!!back} /> }}>
      <Stack.Screen name="patients" options={{ title: 'Patients' }} />
      <Stack.Screen name="patient/[pid]" options={{ title: 'Patient' }} />
    </Stack>
  );
}
