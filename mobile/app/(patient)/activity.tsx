import React from 'react';
import { Body, H1, H2, Screen } from '../../src/ui/kit';
import { WeekBars } from '../../src/ui/parts';
import { useApp } from '../../src/state/services';
import { ACTIVE_LABEL, USUAL_TEXT } from '../../src/ui/format';

export default function Activity() {
  const pid = useApp((s) => s.activePatientId)!;
  return (
    <Screen>
      <H1>{ACTIVE_LABEL}</H1>
      <H2>Last 2 weeks</H2>
      <WeekBars pid={pid} days={14} />
      <Body sub>{USUAL_TEXT}. Days with too little cane data are shown as grey dashed boxes, not as zero.</Body>
    </Screen>
  );
}
