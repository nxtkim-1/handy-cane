import React, { useState } from 'react';
import { Redirect, useRouter } from 'expo-router';
import { Body, Button, Card, ErrorText, H1, H2, Screen } from '../src/ui/kit';
import { getApi, signOut, useApp } from '../src/state/services';
import { acceptConsent, pendingConsent } from '../src/state/consent';

/** Shown before anything else, once, for the patient (or the caregiver acting for them). MASTER 16.6. */
export default function Consent() {
  const router = useRouter();
  const user = useApp((s) => s.user);
  const setUser = useApp((s) => s.setUser);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = pendingConsent(user);
  if (!user || !pending) return <Redirect href="/" />;
  const forSelf = pending.relation === 'self';

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      setUser(await acceptConsent(getApi(), pending!.patient_id));
      router.replace('/');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save your choice. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  async function decline() {
    await signOut();
    router.replace('/sign-in');
  }

  return (
    <Screen topInset>
      <H1>Before you start</H1>
      <Body>
        {forSelf
          ? 'Please read how your information is used. You can say no, and you can change your mind later.'
          : 'You are signing in on behalf of the person who uses this cane. Please read how their information is used.'}
      </Body>

      <Card>
        <H2>What is collected</H2>
        <Body>Summaries of how the cane moves, such as minutes of cane-active time and cane steps.</Body>
        <Body>Potential fall events: when the cane detects a hard drop or a fall, and what happened next.</Body>
        <Body>Nothing is recorded as audio, video or location.</Body>
      </Card>

      <Card>
        <H2>Who sees it</H2>
        <Body>Only the care team: {forSelf ? 'you' : 'the patient'}, the caregivers and the clinicians linked to this account.</Body>
        <Body>
          To write the reports, a third-party AI service receives de-identified numbers only. It does not get a name,
          an email address or any other detail that says who this is. That service may be outside Canada.
        </Body>
      </Card>

      <Card>
        <H2>Your choices</H2>
        <Body>
          You can withdraw consent at any time in Profile, and you can ask to delete your data there too.
          Records of who looked at the data are kept.
        </Body>
        <Body sub>This is a prototype, not a medical device. It does not replace emergency help.</Body>
      </Card>

      <ErrorText>{error}</ErrorText>
      <Button label="I agree" onPress={accept} loading={busy} hint="Saves your consent and opens the app" />
      <Button label="No thanks, sign out" kind="secondary" disabled={busy} onPress={decline} />
    </Screen>
  );
}
