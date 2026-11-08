const mockFS = {
  documentDirectory: 'file:///docs/',
  getInfoAsync: jest.fn(),
  makeDirectoryAsync: jest.fn(),
  downloadAsync: jest.fn(),
  deleteAsync: jest.fn(),
};
const mockPlayers: Array<{ uri: string }> = [];
jest.mock('expo-file-system/legacy', () => mockFS);
jest.mock('expo-audio', () => ({
  createAudioPlayer: (src: { uri: string }) => {
    mockPlayers.push(src);
    let cb: ((s: { didJustFinish?: boolean }) => void) | null = null;
    return {
      addListener: (_e: string, f: typeof cb) => { cb = f; return { remove: () => {} }; },
      play: () => setImmediate(() => cb?.({ didJustFinish: true })),
      remove: () => {},
    };
  },
}));

import { CuePlayer } from '../cues/CuePlayer';

const session = { baseUrl: 'http://cane.local:8080/', token: 'tok-abc' };
async function flush() {
  for (let i = 0; i < 50; i++) await new Promise((r) => setImmediate(r));
}

beforeEach(() => {
  mockPlayers.length = 0;
  Object.values(mockFS).forEach((f) => typeof f === 'function' && (f as jest.Mock).mockReset());
  mockFS.makeDirectoryAsync.mockResolvedValue(undefined);
  mockFS.deleteAsync.mockResolvedValue(undefined);
  mockFS.getInfoAsync.mockResolvedValue({ exists: false });
  mockFS.downloadAsync.mockResolvedValue({ status: 200 });
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});

test('uncached clip downloads with Authorization header (no Cookie) and correct URL, then plays', async () => {
  const p = new CuePlayer();
  p.play('help', session);
  await flush();
  expect(mockFS.downloadAsync).toHaveBeenCalledWith(
    'http://cane.local:8080/voice/help.mp3',
    'file:///docs/cues/help.mp3',
    { headers: { Authorization: 'Bearer tok-abc' } },
  );
  expect(mockPlayers).toEqual([{ uri: 'file:///docs/cues/help.mp3' }]);
});

test('cached clip skips download', async () => {
  mockFS.getInfoAsync.mockResolvedValue({ exists: true });
  const p = new CuePlayer();
  p.play('sos', session);
  await flush();
  expect(mockFS.downloadAsync).not.toHaveBeenCalled();
  expect(mockPlayers).toEqual([{ uri: 'file:///docs/cues/sos.mp3' }]);
});

test('non-200 download deletes the partial file and the queue continues', async () => {
  mockFS.downloadAsync.mockImplementation(async (url: string) => ({ status: url.includes('help') ? 404 : 200 }));
  const p = new CuePlayer();
  p.play('help', session);
  p.play('sos', session);
  await flush();
  expect(mockFS.deleteAsync).toHaveBeenCalledWith('file:///docs/cues/help.mp3', { idempotent: true });
  expect(mockPlayers).toEqual([{ uri: 'file:///docs/cues/sos.mp3' }]);
});

test('unknown cue key is ignored', async () => {
  const p = new CuePlayer();
  p.play('nope', session);
  await flush();
  expect(mockFS.getInfoAsync).not.toHaveBeenCalled();
  expect(mockPlayers).toEqual([]);
});

test('queue drops the oldest item beyond 2', async () => {
  const p = new CuePlayer();
  p.play('dropped', session); // starts draining immediately; shifted off the queue
  p.play('ask_ok', session);
  p.play('help', session);
  p.play('sos', session); // queue now [help, sos]; ask_ok dropped
  await flush();
  expect(mockPlayers.map((x) => x.uri)).toEqual([
    'file:///docs/cues/dropped.mp3',
    'file:///docs/cues/help.mp3',
    'file:///docs/cues/sos.mp3',
  ]);
});
