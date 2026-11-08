# Spoken voice cues

The phone speaks short cues when the cane reports certain events. The cane (Pi, `pi/cane_server.py`) serves the event feed and the voice clips; the app only polls and plays.

## Pairing
`POST /pair` with `{"code":"<pairing code>"}`. The response sets a `cane_session` cookie. The Pi's code is constant for the Pi server session (the cookie value is the code), so repeated `POST /pair` with the same code succeeds; the app pairs once and sends `Cookie: cane_session=...` on every later request (feed and clips).

## Event feed
`GET /events?since=<seq>` returns
```json
{"device":"...","time_quality":"...","events":[{"seq":12,"ts":1700000000,"type":"cue:ask_ok"}]}
```
The app polls about once a second, keeps the highest `seq` seen as an in-memory cursor, and handles events in `seq` order.

## Cue keys and mapping
Keys: `dropped`, `ask_ok`, `help`, `cancelled`, `sos`. Clip: `GET /voice/<key>.mp3`.

| Event type | Cue |
|---|---|
| `cue:<key>` (one of the five) | `<key>` |
| `cane_down` (legacy) | `dropped` |
| `alert` (legacy) | `help` |
| `flow_cancelled` (legacy) | `cancelled` |

Current firmware logs `cue:<key>` right before its legacy twin (e.g. `cue:help` then
`alert`). The feed plays the `cue:` event and suppresses one legacy twin per cue within 5 sequence numbers (a legacy event that plays also absorbs a `cue:` twin arriving within 2), so a cue never plays twice and a later incident is never swallowed. Legacy events without a recent
`cue:` twin still play, so old firmware keeps working.
| anything else, incl. `cue:<unknown>` | none (skipped) |

## No history replay
The first successful poll only sets the cursor; nothing is played. Only events that arrive afterwards are spoken. A failed poll does not move the cursor (one warning is logged, polling keeps retrying).

## Clip caching and playback
A clip is downloaded once (with the session cookie) to `documentDirectory/cues/<key>.mp3` and reused afterwards. Playback uses `expo-audio`, one cue at a time; a queue holds at most 2 waiting cues and the oldest is dropped beyond that. Failures are logged, never thrown.

## Configuration
`EXPO_PUBLIC_CANE_FEED_URL` (cane base URL) and `EXPO_PUBLIC_CANE_PAIR_CODE`. Both set: the feed starts. Either unset: nothing starts.

## Privacy
The voice clips live only on the Pi and are fetched over the local network at runtime. They are never committed to this repo and never bundled as app assets.
