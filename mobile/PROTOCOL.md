# Cane HTTP protocol (phone <-> Pi `canelink`)

Implements MASTER 7.4 over HTTP. The phone always initiates. JSON everywhere,
`Content-Type: application/json`. The Pi listens on a configurable address
(default `http://192.168.4.1:8080`, the Pi's own hotspot). Errors: any non-2xx
status; body `{"error": {"code": "...", "message": "..."}}`.

Record fields are exactly those in MASTER 13.2 (`type: "minute" | "event"`,
`seq`, `boot_id`, `ts`, `time_quality`, ...). `seq` is strictly increasing per
device across minute and event records.

## GET /info  (HELLO / INFO)

Response 200:

```json
{ "device_id": "cane-7f3a", "fw_version": "0.3.1", "last_seq": 48214,
  "unsynced_count": 1203, "sensor_model": "ADXL345" }
```

## POST /time  (TIME_SYNC)

Request: `{ "phone_utc_ms": 1762612345678 }`. Response 200: `{ "ok": true }`.
Pi stores the offset for the current `boot_id` and corrects `ts` of this boot's
`unsynced` rows (they become `corrected`), per MASTER 7.5.

## GET /pull?after_seq=<int>&limit=<int>  (PULL)

Returns records with `seq > after_seq`, ascending, at most `limit` (phone uses 500).
Response 200:

```json
{ "records": [ { "type": "minute", "seq": 101, "...": "..." } ],
  "next_cursor": 600, "more": true }
```

`next_cursor` is the `seq` of the last returned record (or `after_seq` if none).
`more` is true if records with `seq > next_cursor` exist. Pulling is read-only:
it must NOT mark rows as synced.

## POST /ack  (ACK)

Request: `{ "up_to_seq": 600 }`. Response 200: `{ "ok": true }`.
Sent only after the phone durably wrote the page. Pi marks `seq <= up_to_seq`
as `synced_to_phone`. Idempotent; a lower value than before is a no-op.

## GET /live  (optional, demo live view)

Response 200:

```json
{ "ts": "2026-11-08T14:31:47Z", "mag": 1.12, "dyn": 0.12,
  "state": "walking", "strikes_last_10s": 9 }
```

`state` is one of `idle | walking | flat | impact`. Phone polls about once a second.

## Guarantees the phone relies on

- Re-pulling the same range returns the same records (dedup is by `(device_id, seq)` on the phone).
- If a transfer is interrupted, the phone resumes from its last committed cursor.
- The Pi never deletes unacknowledged rows (except critical storage pressure, MASTER 17).

## Cane alerts

HTTP cannot push. Potential-fall events appear in `/pull` as `type: "event"`
records; the BLE transport (stub in `src/comm/BleCaneTransport.ts`) will
deliver them via notify.
