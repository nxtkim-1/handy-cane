import React from 'react';
import { View } from 'react-native';
import { Redirect, useRouter } from 'expo-router';
import { AppBar, Body, Button, Card, H1, H2, Screen } from '../src/ui/kit';
import { signOut, useApp } from '../src/state/services';

const ROLE: Record<string, string> = {
  patient: 'Patient', caregiver: 'Caregiver', clinician: 'Clinician', admin: 'Administrator',
};

export default function Profile() {
  const router = useRouter();
  const { user, mock, apiUrl, caneUrl } = useApp();
  if (!user) return <Redirect href="/sign-in" />;
  return (
    <View style={{ flex: 1 }}>
      <AppBar back />
      <Screen>
        <H1>Profile</H1>
        <Card>
          <H2>{user.display_name}</H2>
          <Body>{user.email}</Body>
          <Body sub>Role: {ROLE[user.role] ?? user.role}</Body>
        </Card>
        <Card>
          <H2>Connection</H2>
          <Body>{mock ? 'Demo mode: simulated cane and simulated backend. All data is simulated.' : 'Live mode'}</Body>
          {!mock && <Body sub>Backend: {apiUrl}</Body>}
          {!mock && <Body sub>Cane: {caneUrl}</Body>}
        </Card>
        <Button label="Sign out" kind="danger" onPress={async () => { await signOut(); router.replace('/sign-in'); }} />
      </Screen>
    </View>
  );
}
