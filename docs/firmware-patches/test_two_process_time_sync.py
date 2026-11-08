"""Two-process time-sync tests for pi/outbox.py (sensor loop and link server are SEPARATE processes,
each with its own Store and boot_id on one SQLite file).

Drop this file into the firmware repo's tests/ dir. Run from pi/ like the other tests:
    cd pi && python3 ../tests/test_two_process_time_sync.py
(also collectable by pytest). Localhost, no hardware. Imports `outbox` from the current dir or ../pi.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pi"))

from outbox import Store, iso  # noqa: E402


def _recs(store):
    return store.pull(0, 2000)["records"]


def _db():
    return os.path.join(tempfile.mkdtemp(), "o.db")


def test_sync_corrects_writer_rows_and_later_rows():
    db, clk = _db(), [1_000_000]
    w = Store(db, now_ms=lambda: clk[0]); w.register_boot()
    s = Store(db, now_ms=lambda: clk[0])
    assert w.boot_id != s.boot_id
    w.add("minute", 1000, {})
    r = s.time_sync(clk[0] + 5000)
    assert r == dict(corrected=1, offset_ms=5000)
    w.add("minute", 2000, {})
    rs = _recs(w)
    assert [x["time_quality"] for x in rs] == ["corrected"] * 2
    assert [x["ts"] for x in rs] == [iso(6000), iso(7000)]


def test_sync_right_after_reboot_before_first_record_targets_new_boot():
    """Writer reboots (new boot_id + register_boot) and the phone syncs BEFORE the new boot wrote a
    row. The newest row belongs to the OLD boot, but the offset must be keyed to the NEW writer
    boot, otherwise every row of the new boot stays 'unsynced' (and the old boot's offset is
    overwritten)."""
    db, clk = _db(), [1_000_000]
    old = Store(db, now_ms=lambda: clk[0]); old.register_boot()
    old.add("minute", 1000, {})
    s = Store(db, now_ms=lambda: clk[0])
    s.time_sync(clk[0] + 5000)                                   # old boot corrected
    new = Store(db, now_ms=lambda: clk[0]); new.register_boot()  # reboot, no rows yet
    r = s.time_sync(clk[0] + 9000)                               # phone connects again
    assert r["offset_ms"] == 9000 and r["corrected"] == 0
    assert new._get_offset(new.boot_id) == 9000, "offset must belong to the rebooted writer"
    assert old._get_offset(old.boot_id) == 5000, "old boot's offset must not be overwritten"
    new.add("minute", 4000, {})
    last = _recs(new)[-1]
    assert last["boot_id"] == new.boot_id
    assert last["time_quality"] == "corrected" and last["ts"] == iso(13000)


def test_old_boot_rows_never_inherit_new_offset():
    db, clk = _db(), [1_000_000]
    old = Store(db, now_ms=lambda: clk[0]); old.register_boot()
    old.add("minute", 1000, {})                                  # never synced
    new = Store(db, now_ms=lambda: clk[0]); new.register_boot()
    new.add("minute", 2000, {})
    Store(db, now_ms=lambda: clk[0]).time_sync(clk[0] + 7000)
    rs = _recs(new)
    assert rs[0]["time_quality"] == "unsynced" and rs[0]["ts"] == iso(1000)
    assert rs[1]["time_quality"] == "corrected" and rs[1]["ts"] == iso(9000)


def test_writer_without_register_boot_falls_back_to_newest_record():
    db, clk = _db(), [1_000_000]
    w = Store(db, now_ms=lambda: clk[0])                         # legacy writer: no register_boot()
    w.add("minute", 1000, {})
    r = Store(db, now_ms=lambda: clk[0]).time_sync(clk[0] + 3000)
    assert r == dict(corrected=1, offset_ms=3000)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
