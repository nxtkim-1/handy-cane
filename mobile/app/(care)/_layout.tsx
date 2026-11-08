import React from 'react';
import { Redirect, Stack } from 'expo-router';
import { useApp } from '../../src/state/services';

export default function CareLayout() {
  const user = useApp((s) => s.user);
  if (!user) return <Redirect href="/sign-in" />;
  return (
    <Stack screenOptions={{ headerTitleStyle: { fontSize: 22 } }}>
      <Stack.Screen name="patients" options={{ title: 'Patients' }} />
      <Stack.Screen name="patient/[pid]" options={{ title: 'Patient' }} />
    </Stack>
  );
}
