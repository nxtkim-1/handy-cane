# cane/ (reference implementation + simulator)

Run the simulator and sync API: `python -m cane.run_sim --port 8765` (add `--no-live` to drop `/live`).
Tests: `python -m pytest cane tools -q`.

## GET /live  (for the firmware team; matches mobile/PROTOCOL.md)

Response 200, polled by the phone about once a second:

```json
{ "ts": "2026-11-08T14:31:47Z", "mag": 1.12, "dyn": 0.12,
  "state": "walking", "strikes_last_10s": 9 }
```

| Field | Definition |
|---|---|
| `ts` | UTC ISO-8601, second resolution, the cane's clock at the last refresh |
| `mag` | mean of `|a|` (g) over the last 1 s |
| `dyn` | mean of `max(|a| - 1, 0)` over the last 1 s |
| `state` | `impact` if the fall FSM is in IMPACT / CHECK_STILL / PRE_ALERT / ALERT; else `flat` if tilt > 70 deg and 1-s std < `T_ACTIVE`; else `walking` if 1-s std of `|a|` > `T_ACTIVE`; else `idle` |
| `strikes_last_10s` | `detect_strikes` over the last 10 s of `|a|` |

Note: the original brief listed `walking/idle/down`; the phone contract (PROTOCOL.md, `src/types.ts`) uses
`idle | walking | flat | impact`, which is what is implemented.

Errors: `503 {"error": {"code": "no_live_data", "message": "..."}}` when no source is attached or no
sample has been taken yet. The route is read-only and does no I/O beyond the in-memory snapshot.

Implementation: `cane/canesense/live.py` (`LiveTracker`, thread-safe, strike counting once per second),
fed from `CaneRuntime.step(...)` via `CaneRuntime(..., live=tracker)`; served by
`serve(store, live=tracker)` in `cane/canelink/server.py`.

### Two-process deployment caveat

`/live` reads in-memory state, so it works when the sampling loop and the HTTP server share a process
(the simulator). With separate sensor and link processes (MASTER 6.4) the sensor loop must hand the
latest snapshot to the link process, for example by writing the `LiveTracker.snapshot()` dict to a
small file or a `meta` row about once a second (this must not block the sampling loop), and the link
process returns it unchanged. Keep `/live` optional: the safety path never depends on it.
