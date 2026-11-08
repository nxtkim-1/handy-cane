import React from 'react';
import { H1, Screen } from '../../src/ui/kit';
import { ReportsList, usePullRefresh } from '../../src/ui/parts';
import { useApp } from '../../src/state/services';

export default function Reports() {
  const pid = useApp((s) => s.activePatientId)!;
  const refresh = usePullRefresh();
  return (
    <Screen onRefresh={refresh.onRefresh} refreshing={refresh.refreshing}>
      <H1>Reports</H1>
      <ReportsList pid={pid} canGenerate={false} />
    </Screen>
  );
}
