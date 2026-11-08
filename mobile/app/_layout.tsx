import React, { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient as qc } from '../src/state/queryClient';
import { bootstrap, useForegroundSync } from '../src/state/services';

export default function RootLayout() {
  // Restore the saved session once; the index screen shows a splash until it is done.
  useEffect(() => { void bootstrap(); }, []);
  // Upload every 30 s and pull from the cane every 60 s, only while the app is open and consent is given.
  useForegroundSync();
  return (
    <QueryClientProvider client={qc}>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false }} />
    </QueryClientProvider>
  );
}
