import json
import urllib.request

from cane.canelink.server import serve
from cane.canesense.store import Store
from cane.run_sim import run_session

START = 1_790_000_040_000


def http(port, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def make_store():
    # the Pi clock is wrong by an hour until the phone syncs
    return Store(device_id="cane-t", now_ms=lambda: START - 3_600_000)


def test_session_produces_minutes_and_expected_events():
    s = make_store()
    buzzer = run_session(s, start_ms=START - 3_600_000)
    recs = s.pull(0, 2000)["records"]
    minutes = [r for r in recs if r["type"] == "minute"]
    events = [r for r in recs if r["type"] == "event"]
    assert len(minutes) >= 6
    assert [e["outcome"] for e in events] == ["cancelled_by_user", "escalated"]
    assert buzzer.log[:3] == ["beep", "off", "beep"] and "continuous" in buzzer.log
    assert any(m["strike_count"] > 40 for m in minutes)      # the walking minutes
    assert all(r["time_quality"] == "unsynced" for r in recs)


def test_sync_protocol_resume_dedup_and_time_correction():
    s = make_store()
    run_session(s, start_ms=START - 3_600_000)
    srv = serve(s, host="127.0.0.1", port=0)
    port = srv.server_address[1]
    try:
        info = http(port, "/info")
        assert info["device_id"] == "cane-t" and info["unsynced_count"] > 5

        fix = http(port, "/time", {"phone_utc_ms": START})
        assert fix["offset_ms"] == 3_600_000 and fix["corrected"] == info["unsynced_count"]

        page1 = http(port, "/pull?after_seq=0&limit=3")
        assert len(page1["records"]) == 3 and page1["more"]
        assert all(r["time_quality"] == "corrected" for r in page1["records"])
        assert page1["records"][0]["ts"] >= "2026-" and page1["records"][0]["ts"].endswith("Z")
        http(port, "/ack", {"up_to_seq": page1["next_cursor"]})

        # "phone crash": resume from the committed cursor, then pull the rest
        seen = [r["seq"] for r in page1["records"]]
        cur = page1["next_cursor"]
        while True:
            p = http(port, f"/pull?after_seq={cur}&limit=3")
            seen += [r["seq"] for r in p["records"]]
            cur = p["next_cursor"]
            http(port, "/ack", {"up_to_seq": cur})
            if not p["more"]:
                break
        assert seen == sorted(set(seen)) and len(seen) == info["last_seq"]
        assert http(port, "/info")["unsynced_count"] == 0
    finally:
        srv.shutdown()


def test_seq_never_reused_after_reboot(tmp_path):
    db = str(tmp_path / "c.db")
    a = Store(db, now_ms=lambda: START)
    last = a.add("minute", START, {})
    b = Store(db, now_ms=lambda: START)          # reboot: new boot_id, same file
    assert b.boot_id != a.boot_id and b.add("minute", START, {}) == last + 1


def test_fall_detection_works_with_link_server_never_started():
    s = make_store()
    run_session(s, start_ms=START - 3_600_000)   # no canelink running at all
    assert any(r["type"] == "event" for r in s.pull(0, 2000)["records"])
