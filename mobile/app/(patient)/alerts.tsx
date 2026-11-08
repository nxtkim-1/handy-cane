import React from 'react';
import { Body, H1, Screen } from '../../src/ui/kit';
import { AlertsList } from '../../src/ui/parts';
import { useApp } from '../../src/state/services';

export default function Alerts() {
  const pid = useApp((s) => s.activePatientId)!;
  const role = useApp((s) => s.user!.role);
  return (
    <Screen>
      <H1>Alerts</H1>
      <Body sub>Alerts are never deleted. If one was not a fall, you can dismiss it and say why.</Body>
      <AlertsList pid={pid} canDismiss={role === 'patient'} />
    </Screen>
  );
}
