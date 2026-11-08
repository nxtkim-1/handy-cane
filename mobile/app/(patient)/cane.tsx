import React, { useEffect, useState } from 'react';
import { Badge, Body, Button, Card, ErrorText, Field, H1, H2, Screen, colors } from '../../src/ui/kit';
import { getMockCane, getTransport, useApp, useSync } from '../../src/state/services';
import { fmtAgo } from '../../src/ui/format';
import type { LiveSample } from '../../src/types';

export default function Cane() {
  const { mock, caneUrl, setConfig } = useApp();
  const sync = useSync();
  const [live, setLive] = useState<LiveSample | null>(null);
  const [liveOn, setLiveOn] = useState(false);
  const [liveErr, setLiveErr] = useState<string | null>(null);

  useEffect(() => { sync.refreshStatus(); }, []);

  useEffect(() => {
    if (!liveOn) return;
    let stop = false;
    const tick = async () => {
      try {
        const t = getTransport();
        if (!t.live) throw new Error('Live view is not available on this connection.');
        const s = await t.live();
        if (!stop) { setLive(s); setLiveErr(null); }
      } catch (e) {
        if (!stop) setLiveErr(e instanceof Error ? e.message : 'Lost the cane.');
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => { stop = true; clearInterval(id); };
  }, [liveOn]);

  return (
    <Screen>
      <H1>Cane</H1>
      {mock && <Badge text="SIMULATED CANE" />}
      <Card>
        <H2>Sync</H2>
        <Body>Last synced: {fmtAgo(sync.lastSyncMs)}</Body>
        {sync.waitingToUpload > 0 && <Body>Waiting to upload: {sync.waitingToUpload} records</Body>}
        {sync.message && <Body>{sync.message}</Body>}
        <ErrorText>{sync.error}</ErrorText>
        <Button label="Sync now" loading={sync.syncing} onPress={() => sync.run()} />
        <Body sub>The cane keeps your data until it has been copied to this phone, so nothing is lost if you are away.</Body>
      </Card>

      {!mock && (
        <Card>
          <H2>Connection</H2>
          <Field label="Cane address" value={caneUrl} autoCapitalize="none" onChangeText={(t) => setConfig({ caneUrl: t })} />
        </Card>
      )}

      <Card>
        <H2>Live view</H2>
        <Button label={liveOn ? 'Stop live view' : 'Start live view'} kind="secondary" onPress={() => setLiveOn(!liveOn)} />
        {liveOn && live && (
          <>
            <Body>State: {live.state}</Body>
            <Body>Motion: {live.dyn.toFixed(2)} g</Body>
            <Body>Cane steps in the last 10 s: {live.strikes_last_10s}</Body>
          </>
        )}
        <ErrorText>{liveErr}</ErrorText>
      </Card>

      {mock && (
        <Card>
          <H2>Demo</H2>
          <Button label="Simulate a potential fall" kind="danger" onPress={() => getMockCane()?.triggerFall()} />
          <Body sub style={{ color: colors.sub }}>Then press Sync now; the alert is uploaded with the other records.</Body>
        </Card>
      )}
    </Screen>
  );
}
