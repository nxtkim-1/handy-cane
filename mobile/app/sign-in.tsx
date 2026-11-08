import React, { useState } from 'react';
import { Switch, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Body, Button, Card, ErrorText, Field, H1, Screen } from '../src/ui/kit';
import { getApi, saveRefreshToken, useApp } from '../src/state/services';

export default function SignIn() {
  const router = useRouter();
  const { mock, apiUrl, caneUrl, setConfig, setUser } = useApp();
  const [email, setEmail] = useState(mock ? 'patient@demo' : '');
  const [password, setPassword] = useState(mock ? 'demo' : '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const { user, tokens } = await getApi().login(email, password);
      await saveRefreshToken(tokens.refresh_token);
      setUser(user);
      router.replace('/');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not sign in.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <H1>Smart Cane</H1>
      <Body sub>Sign in to see cane-active time, alerts and reports.</Body>
      <Field label="Email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" />
      <Field label="Password" value={password} onChangeText={setPassword} secureTextEntry />
      <ErrorText>{error}</ErrorText>
      <Button label="Sign in" onPress={submit} loading={busy} />

      <Card>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 48 }}>
          <Body>Demo mode (no backend, simulated cane)</Body>
          <Switch
            accessibilityLabel="Demo mode"
            value={mock}
            onValueChange={(v) => setConfig({ mock: v })}
          />
        </View>
        {mock ? (
          <Body sub>Demo accounts: patient@demo or clinician@demo, password demo. All data is simulated.</Body>
        ) : (
          <>
            <Field label="Backend address" value={apiUrl} onChangeText={(t) => setConfig({ apiUrl: t })} autoCapitalize="none" />
            <Field label="Cane address" value={caneUrl} onChangeText={(t) => setConfig({ caneUrl: t })} autoCapitalize="none" />
          </>
        )}
      </Card>
    </Screen>
  );
}
