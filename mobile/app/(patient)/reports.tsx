import React from 'react';
import { H1, Screen } from '../../src/ui/kit';
import { ReportsList } from '../../src/ui/parts';
import { useApp } from '../../src/state/services';

export default function Reports() {
  const pid = useApp((s) => s.activePatientId)!;
  return (
    <Screen>
      <H1>Reports</H1>
      <ReportsList pid={pid} canGenerate={false} />
    </Screen>
  );
}
