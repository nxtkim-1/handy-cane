# Spoken voice cues

The phone speaks short cues when the cane reports certain events. The cane (Pi, `pi/cane_server.py`) serves the event feed and the voice clips; the app only polls and plays.

## Pairing and bearer flow
`POST /pair` with `{"code":"<pairing code>"}`. On success the response is `{"paired": true, "session": "<token>"}` (any non-200 means pairing failed). The server also sets a `cane_session` cookie, but the app ignores it: browsers (Expo web) cannot read `Set-Cookie` or set a `Cookie` header from JS. The app keeps the `session` token in memory only (never stored) and sends `Authorization: Bearer <token>` on `/events`, `/voice/<key>.mp3` (clip download) and `/status`.

A wrong or missing token on those routes returns 401. On a 401 poll the app drops its token, re-pairs once on the next poll, and if that pairing fails shows "Could not pair. Check the address and pairing code."

## Trust model
The pairing code and session token travel over the local hotspot in plaintext (plain HTTP). Use trusted networks only, and never expose the Pi to the internet. The pairing code changes on every Pi start, so it must be re-entered in the app after each cane restart.

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
`alert`). The feed plays the `cue:` event and suppresses one legacy twin per cue within 5 sequence numbers (a legacy event that plays also absorbs a `cue:` twin arriving within 2), so a cue never plays twice and a later incident is never swallowed.

**Legacy fallback rule.** Legacy event types (`cane_down`, `alert`, `flow_cancelled`) play only until the first `cue:` event has ever been observed by the feed instance (old-firmware mode; history seen during the baseline poll counts). Once any `cue:` event is seen, legacy events never play: their `cue:` twins cover them, and twinless legacy events are intentionally silent. In particular, firmware logs `cane_down` without `cue:dropped` on an impact fall (the cane stays silent by design), so the phone stays silent too.

**Capability field `fw`.** `GET /events` responses carry a top-level `"fw"` string (the firmware version, e.g. `"0.4.0"`). When a poll response has a non-empty `fw`, the feed is treated as new firmware immediately, from the first baseline poll: legacy events never play, even if no `cue:` event exists yet (empty history, or only silent impact `cane_down` events). Feeds without `fw` (truly old firmware) keep the `cue:`-seen rule above.

| anything else, incl. `cue:<unknown>` | none (skipped) |

## No history replay
The first successful poll only sets the cursor; nothing is played. Only events that arrive afterwards are spoken. A failed poll does not move the cursor (one warning is logged, polling keeps retrying).

## Clip caching and playback
A clip is downloaded once (with the bearer token) to `documentDirectory/cues/<key>.mp3` and reused afterwards. Playback uses `expo-audio`, one cue at a time; a queue holds at most 2 waiting cues and the oldest is dropped beyond that. Failures are logged, never thrown.

## Pairing from the app
On the Cane screen (non-simulated mode), enter the cane feed address and the pairing code under "Voice cues", then turn voice cues on. The env vars `EXPO_PUBLIC_CANE_FEED_URL` / `EXPO_PUBLIC_CANE_PAIR_CODE` are only defaults for those fields. The pairing code changes on every Pi start; re-enter it in the app.

## Configuration
`EXPO_PUBLIC_CANE_FEED_URL` (cane base URL) and `EXPO_PUBLIC_CANE_PAIR_CODE`. Both set: the feed starts. Either unset: nothing starts.

## Privacy
The voice clips live only on the Pi and are fetched over the local network at runtime. They are never committed to this repo and never bundled as app assets.
