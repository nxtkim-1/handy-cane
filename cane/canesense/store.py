"""SQLite (WAL) outbox on the cane (MASTER 6.4, 7.4, 7.5).

seq is AUTOINCREMENT so it is never reused, even after rows are deleted or the Pi reboots.
Timestamps are wall-clock ms as the Pi believes them; rows written before a phone time sync
are 'unsynced' and become 'corrected' (shifted by the measured offset) when a sync arrives.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable

DEVICE_ID_DEFAULT = "cane-dev"


def iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path: str = ":memory:", device_id: str = DEVICE_ID_DEFAULT,
                 now_ms: Callable[[], int] | None = None, ntp_synced: bool = False,
                 sensor_model: str = "unknown", fw_version: str = "0.1.0"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.Lock()
        self.device_id, self.sensor_model, self.fw_version = device_id, sensor_model, fw_version
        self.boot_id = str(uuid.uuid4())
        self.ntp_synced = ntp_synced
        self._now_ms = now_ms or (lambda: int(datetime.now(timezone.utc).timestamp() * 1000))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                boot_id TEXT NOT NULL, ts_ms INTEGER NOT NULL, quality TEXT NOT NULL,
                type TEXT NOT NULL, payload TEXT NOT NULL, acked INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS rec_acked ON records(acked, seq);
        """)
        self.db.commit()

    # ---- writing (called only by canesense) ----
    def add(self, rtype: str, ts_ms: int, payload: dict) -> int:
        quality = "synced" if self.ntp_synced else "unsynced"
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO records(boot_id, ts_ms, quality, type, payload) VALUES (?,?,?,?,?)",
                (self.boot_id, ts_ms, quality, rtype, json.dumps(payload)))
            self.db.commit()
            return cur.lastrowid

    # ---- reading (called by canelink) ----
    def info(self) -> dict:
        with self.lock:
            last = self.db.execute("SELECT COALESCE(MAX(seq),0) FROM records").fetchone()[0]
            n = self.db.execute("SELECT COUNT(*) FROM records WHERE acked=0").fetchone()[0]
        return dict(device_id=self.device_id, fw_version=self.fw_version, sensor_model=self.sensor_model,
                    last_seq=last, unsynced_count=n, boot_id=self.boot_id)

    def pull(self, after_seq: int, limit: int = 500) -> dict:
        limit = max(1, min(limit, 2000))
        with self.lock:
            rows = self.db.execute(
                "SELECT seq, boot_id, ts_ms, quality, type, payload FROM records WHERE seq > ? "
                "ORDER BY seq LIMIT ?", (after_seq, limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        records = []
        for seq, boot_id, ts_ms, quality, rtype, payload in rows:
            d = json.loads(payload)
            d.update(type=rtype, seq=seq, boot_id=boot_id, ts=iso(ts_ms), time_quality=quality)
            records.append(d)
        return dict(records=records, next_cursor=rows[-1][0] if rows else after_seq, more=more)

    def ack(self, up_to_seq: int) -> int:
        with self.lock:
            cur = self.db.execute("UPDATE records SET acked=1 WHERE seq<=? AND acked=0", (up_to_seq,))
            self.db.commit()
            return cur.rowcount

    def time_sync(self, phone_utc_ms: int) -> dict:
        """Shift this boot's unsynced rows by the measured offset and trust the clock from now on."""
        delta = phone_utc_ms - self._now_ms()
        with self.lock:
            cur = self.db.execute(
                "UPDATE records SET ts_ms = ts_ms + ?, quality='corrected' "
                "WHERE boot_id=? AND quality='unsynced'", (delta, self.boot_id))
            self.db.commit()
        self.clock_offset_ms = delta
        return dict(corrected=cur.rowcount, offset_ms=delta)

    clock_offset_ms: int = 0

    def now_ms(self) -> int:
        """Clock as the Pi should now believe it (applies any phone-measured offset)."""
        return self._now_ms() + self.clock_offset_ms

    def quality_now(self) -> str:
        return "synced" if self.ntp_synced else ("corrected" if self.clock_offset_ms else "unsynced")
