"""SQLite (WAL) outbox on the cane (MASTER 6.4, 7.4, 7.5). Vendored from the canonical canesense/store.py.

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
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.db.commit()

    # ---- writing (called only by link.py) ----
    def _offset_key(self, boot_id: str) -> str:
        return "clock_offset_ms:" + boot_id

    def _get_offset(self, boot_id: str) -> int:
        """Phone-measured offset for ONE boot (0 if none). Caller holds self.lock.
        Read from the DB each time: the /time receiver is a different process from the writer."""
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (self._offset_key(boot_id),)).fetchone()
        return int(row[0]) if row else 0

    def add(self, rtype: str, ts_ms: int, payload: dict) -> int:
        with self.lock:
            # Only THIS writer's own boot offset applies; a rebooted Pi never inherits an old boot's offset.
            offset = 0 if self.ntp_synced else self._get_offset(self.boot_id)
            quality = "synced" if self.ntp_synced else ("corrected" if offset else "unsynced")
            cur = self.db.execute(
                "INSERT INTO records(boot_id, ts_ms, quality, type, payload) VALUES (?,?,?,?,?)",
                (self.boot_id, ts_ms + offset, quality, rtype, json.dumps(payload)))
            self.db.commit()
            return cur.lastrowid

    # ---- reading (called by link_server.py) ----
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

    def register_boot(self) -> None:
        """Called once by the WRITER process at startup: lets /time (another process) find the
        writer's boot before any record exists."""
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('writer_boot', ?)", (self.boot_id,))
            self.db.commit()

    def time_sync(self, phone_utc_ms: int) -> dict:
        """Shift the current boot's unsynced rows by the measured offset and remember it for that boot.

        The receiver of /time (link server) is a different process from the writer, so self.boot_id
        is NOT the writer's boot. The current boot is the boot_id of the newest record, else the
        registered meta['writer_boot'], else own boot_id. The offset is stored per boot so a later boot does not inherit it."""
        delta = phone_utc_ms - self._now_ms()
        with self.lock:
            row = self.db.execute("SELECT boot_id FROM records ORDER BY seq DESC LIMIT 1").fetchone()
            if row:
                boot = row[0]
            else:
                wb = self.db.execute("SELECT value FROM meta WHERE key='writer_boot'").fetchone()
                boot = wb[0] if wb else self.boot_id
            cur = self.db.execute(
                "UPDATE records SET ts_ms = ts_ms + ?, quality='corrected' "
                "WHERE boot_id=? AND quality='unsynced'", (delta, boot))
            self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
                            (self._offset_key(boot), str(delta)))
            self.db.commit()
        return dict(corrected=cur.rowcount, offset_ms=delta)

    @property
    def clock_offset_ms(self) -> int:
        with self.lock:
            return self._get_offset(self.boot_id)

    def now_ms(self) -> int:
        """Clock as the Pi should now believe it (applies this boot's phone-measured offset)."""
        return self._now_ms() + self.clock_offset_ms

    def quality_now(self) -> str:
        return "synced" if self.ntp_synced else ("corrected" if self.clock_offset_ms else "unsynced")
