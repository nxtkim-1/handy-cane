import React, { useEffect, useState } from 'react';
import { useRouter } from 'expo-router';
import { Badge, Body, Button, Card, ErrorText, Field, H1, H2, Screen, colors } from '../../src/ui/kit';
import {
  getCueFeed, getCueStatus, getMockCane, getTransport, isCueFeedRunning, persistSettingsIfSignedIn,
  setCueStatusListener, stopCueFeed, useApp, useSync,
} from '../../src/state/services';
import { SyncStatusLines, usePullRefresh } from '../../src/ui/parts';
import { LIVE_UNAVAILABLE_TEXT, startLivePoller } from '../../src/comm/liveView';
import type { LiveSample } from '../../src/types';

export default function Cane() {
  const router = useRouter();
  const { mock, caneUrl, feedUrl, pairCode, setConfig } = useApp();
  const sync = useSync();
  const refresh = usePullRefresh();
  const [live, setLive] = useState<LiveSample | null>(null);
  const [liveOn, setLiveOn] = useState(false);
  const [liveErr, setLiveErr] = useState<string | null>(null);
  const [liveGone, setLiveGone] = useState(false);
  const [cuesOn, setCuesOn] = useState(isCueFeedRunning());
  const [cueStatus, setCueStatus] = useState<string | null>(getCueStatus());

  useEffect(() => {
    setCueStatusListener(setCueStatus);
    return () => setCueStatusListener(null);
  }, []);

  const toggleCues = () => {
    if (cuesOn) { stopCueFeed(); setCuesOn(false); return; }
    setCuesOn(getCueFeed() !== null);
  };

  useEffect(() => { sync.refreshStatus().catch(() => {}); }, []);

  useEffect(() => {
    if (!liveOn) return;
    setLiveErr(null);
    return startLivePoller(getTransport(), {
      onSample: (s) => { setLive(s); setLiveErr(null); },
      onError: (m) => setLiveErr(m),
      onUnavailable: () => { setLiveGone(true); setLiveOn(false); setLive(null); },
    });
  }, [liveOn]);

  return (
    <Screen onRefresh={refresh.onRefresh} refreshing={refresh.refreshing}>
      <H1>Cane</H1>
      {mock && <Badge text="SIMULATED CANE" />}
      <Card>
        <H2>Sync</H2>
        <SyncStatusLines />
        {sync.message && <Body sub>{sync.message}</Body>}
        <ErrorText>{sync.error}</ErrorText>
        <ErrorText>{sync.rejectedMessage}</ErrorText>
        <Button label="Sync now" loading={sync.syncing} onPress={() => sync.run()} />
        <Body sub>The cane keeps your data until it has been copied to this phone, so nothing is lost if you are away.</Body>
      </Card>

      {!mock && (
        <Card>
          <H2>Connection</H2>
          <Field
            label="Cane address" value={caneUrl} autoCapitalize="none"
            onChangeText={(t) => { setConfig({ caneUrl: t }); void persistSettingsIfSignedIn(); }}
          />
        </Card>
      )}

      {!mock && (
        <Card>
          <H2>Voice cues</H2>
          <Field label="Cane feed address" value={feedUrl} autoCapitalize="none" autoCorrect={false} onChangeText={(t) => { setConfig({ feedUrl: t }); setCuesOn(false); }} />
          <Field label="Pairing code" value={pairCode} autoCapitalize="none" autoCorrect={false} onChangeText={(t) => { setConfig({ pairCode: t }); setCuesOn(false); }} />
          <Button label={cuesOn ? 'Turn voice cues off' : 'Turn voice cues on'} kind="secondary" onPress={toggleCues} />
          {cuesOn && cueStatus === 'paired' && <Body sub>Paired. Listening for cues.</Body>}
          {cuesOn && cueStatus !== 'paired' && <ErrorText>{cueStatus}</ErrorText>}
        </Card>
      )}

      <Card>
        <H2>Live view</H2>
        {liveGone ? (
          <Body>{LIVE_UNAVAILABLE_TEXT}</Body>
        ) : (
          <Button label={liveOn ? 'Stop live view' : 'Start live view'} kind="secondary" onPress={() => setLiveOn(!liveOn)} />
        )}
        {liveOn && !live && !liveErr && <Body sub>Waiting for the cane.</Body>}
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
          <Button
            label="Simulate a potential fall" kind="danger" loading={sync.syncing}
            onPress={async () => { getMockCane()?.triggerFall(); await sync.run(); router.push('/alerts'); }}
          />
          <Body sub style={{ color: colors.sub }}>The cane records the fall, the phone syncs it, and you land on Alerts.</Body>
        </Card>
      )}
    </Screen>
  );
}
