import React from 'react';
import { Body, H1, Screen } from '../../src/ui/kit';
import { AlertsList, usePullRefresh } from '../../src/ui/parts';
import { useApp } from '../../src/state/services';
import { canDismissFor } from '../../src/state/routes';

export default function Alerts() {
  const pid = useApp((s) => s.activePatientId)!;
  const user = useApp((s) => s.user)!;
  const refresh = usePullRefresh();
  const canDismiss = canDismissFor(user, pid);
  return (
    <Screen onRefresh={refresh.onRefresh} refreshing={refresh.refreshing}>
      <H1>Alerts</H1>
      <Body sub>
        {canDismiss
          ? 'Alerts are never deleted. If one was not a fall, you can dismiss it and say why.'
          : 'Alerts are never deleted. You can mark them as seen.'}
      </Body>
      <AlertsList pid={pid} canDismiss={canDismiss} />
    </Screen>
  );
}
