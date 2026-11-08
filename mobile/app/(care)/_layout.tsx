import React from 'react';
import { Redirect, Stack } from 'expo-router';
import { useApp } from '../../src/state/services';
import { AppBar } from '../../src/ui/kit';

export default function CareLayout() {
  const user = useApp((s) => s.user);
  if (!user) return <Redirect href="/sign-in" />;
  return (
    <Stack screenOptions={{ header: ({ back }) => <AppBar back={!!back} /> }}>
      <Stack.Screen name="patients" options={{ title: 'Patients' }} />
      <Stack.Screen name="patient/[pid]" options={{ title: 'Patient' }} />
    </Stack>
  );
}
