import React from 'react';
import { Redirect } from 'expo-router';
import { Body, H1, Loading, Screen } from '../src/ui/kit';
import { useApp } from '../src/state/services';
import { homeRouteFor } from '../src/state/routes';

export default function Index() {
  const user = useApp((s) => s.user);
  const ready = useApp((s) => s.ready);
  const route = homeRouteFor(user, ready);
  if (route === '/splash') {
    return (
      <Screen topInset>
        <H1>Smart Cane</H1>
        <Loading label="Restoring your session" />
        <Body sub>Getting things ready.</Body>
      </Screen>
    );
  }
  return <Redirect href={route} />;
}
