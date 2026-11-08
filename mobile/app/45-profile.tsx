import React, { useState } from 'react';
import { View } from 'react-native';
import { Redirect, useRouter } from 'expo-router';
import { AppBar, Body, Button, Card, ErrorText, Field, H1, H2, Screen } from '../src/ui/kit';
import { getApi, signOut, useApp } from '../src/state/services';
import { canManageOwnData, deleteConfirmed, deleteMyData, withdrawConsent } from '../src/state/consent';

const ROLE: Record<string, string> = {
  patient: 'Patient', caregiver: 'Caregiver', clinician: 'Clinician', admin: 'Administrator',
};

type Step = 'idle' | 'withdraw' | 'delete1' | 'delete2';

export default function Profile() {
  const router = useRouter();
  const { user, mock, apiUrl, caneUrl, activePatientId } = useApp();
  const [step, setStep] = useState<Step>('idle');
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!user) return <Redirect href="/" />;
  const own = canManageOwnData(user, activePatientId);

  async function run(job: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await job();
      await signOut();
      router.replace('/sign-in');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Nothing was changed.');
    } finally {
      setBusy(false);
    }
  }

  const cancel = () => { setStep('idle'); setTyped(''); setError(null); };

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

        {own && (
          <Card tone="warn">
            <H2>Your data</H2>
            {step === 'idle' && (
              <>
                <Body>You can stop sharing your data, or have it deleted.</Body>
                <Button label="Withdraw consent" kind="secondary" onPress={() => setStep('withdraw')} />
                <Button label="Delete my data" kind="danger" onPress={() => setStep('delete1')} />
              </>
            )}
            {step === 'withdraw' && (
              <>
                <Body>
                  Withdraw consent? The cane keeps working, but nothing more is shared with your care team.
                  You will be signed out, and asked again next time you sign in.
                </Body>
                <ErrorText>{error}</ErrorText>
                <Button label="Yes, withdraw consent" kind="danger" loading={busy}
                  onPress={() => run(() => withdrawConsent(getApi(), activePatientId!))} />
                <Button label="Cancel" kind="secondary" disabled={busy} onPress={cancel} />
              </>
            )}
            {step === 'delete1' && (
              <>
                <Body>
                  Delete all of your cane data, alerts and reports from the server? This cannot be undone.
                  Records of who looked at your data are kept.
                </Body>
                <Button label="Continue" kind="danger" onPress={() => setStep('delete2')} />
                <Button label="Cancel" kind="secondary" onPress={cancel} />
              </>
            )}
            {step === 'delete2' && (
              <>
                <Body>To confirm, type DELETE in capital letters.</Body>
                <Field label="Type DELETE" value={typed} onChangeText={setTyped} autoCapitalize="characters" autoCorrect={false} />
                <ErrorText>{error}</ErrorText>
                <Button label="Delete my data for good" kind="danger" loading={busy} disabled={!deleteConfirmed(typed)}
                  onPress={() => run(() => deleteMyData(getApi(), activePatientId!, typed))} />
                <Button label="Cancel" kind="secondary" disabled={busy} onPress={cancel} />
              </>
            )}
          </Card>
        )}

        <Button label="Sign out" kind="danger" onPress={async () => { await signOut(); router.replace('/sign-in'); }} />
      </Screen>
    </View>
  );
}
