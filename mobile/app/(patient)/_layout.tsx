import React from 'react';
import { Redirect, Tabs } from 'expo-router';
import { useApp } from '../../src/state/services';
import { colors } from '../../src/ui/kit';

export default function PatientLayout() {
  const user = useApp((s) => s.user);
  if (!user) return <Redirect href="/sign-in" />;
  return (
    <Tabs
      screenOptions={{
        headerTitleStyle: { fontSize: 22 },
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
