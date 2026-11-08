import React from 'react';
import { Redirect, Tabs } from 'expo-router';
import { useApp } from '../../src/state/services';
import { pendingConsent } from '../../src/state/consent';
import { AppBar, colors } from '../../src/ui/kit';

export default function PatientLayout() {
  const user = useApp((s) => s.user);
  // Not signed in yet, still restoring, or consent still needed: the index screen decides where to go.
  if (!user || pendingConsent(user)) return <Redirect href="/" />;
  return (
    <Tabs
      screenOptions={{
        header: () => <AppBar />,
        tabBarLabelStyle: { fontSize: 14, fontWeight: '700' },
        tabBarActiveTintColor: colors.primary,
        tabBarStyle: { minHeight: 64 },
        tabBarIconStyle: { display: 'none' },
      }}
    >
      <Tabs.Screen name="home" options={{ title: 'Home' }} />
      <Tabs.Screen name="activity" options={{ title: 'Activity' }} />
      <Tabs.Screen name="alerts" options={{ title: 'Alerts' }} />
      <Tabs.Screen name="reports" options={{ title: 'Reports' }} />
      <Tabs.Screen name="cane" options={{ title: 'Cane' }} />
    </Tabs>
  );
}
