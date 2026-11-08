# Firmware patch: outbox time sync (pi/outbox.py)

Applies to `pi/outbox.py` as on `origin/firmware-canelink` (head `accdbbd`). Not applied by us; yours to merge.

## Status of the original concern

We expected your `outbox.py` to predate canonical commit `3d01279` (shared clock offset, correct the newest
boot). It does not: it already has the `meta` table, per-boot offsets and `register_boot()`, and your
`tests/canelink_adapter_tests.py` sections 7 and 9 cover the main two-process cases (79/79 pass).

## One remaining bug (what the patch fixes)

`time_sync()` picks the boot to correct as "boot of the newest record, else `meta['writer_boot']`".
Sequence that breaks:

1. Pi runs, phone syncs: boot A rows corrected, offset A stored.
2. Pi reboots. Writer registers boot B (`register_boot()`), no rows written yet.
3. Phone connects and sends `/time` before B's first minute record (up to 60 s window).

The newest record is still boot A, so the new offset is stored for **A** (overwriting A's good offset) and
**B's rows stay `unsynced`** for the whole boot (until a later `/time`). The fix: prefer the registered
`writer_boot`; fall back to the newest record only for writers that never register.

## Files

- `outbox-time-sync.patch`: `git apply` from the repo root (`git apply --check` passes against
  `pi/outbox.py` at `accdbbd`). 12-line change in `Store.time_sync` only.
- `test_two_process_time_sync.py`: copy into your `tests/`. Run from `pi/`:
  `python3 ../tests/test_two_process_time_sync.py` (pytest can collect it too). Four tests; the
  reboot-before-first-record test fails on the current file and passes with the patch. The other three
  pass either way (regression guards, including the legacy no-`register_boot` fallback).

Verified: your `canelink_adapter_tests.py` still passes 79/79 with the patch applied.
