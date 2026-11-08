"""Tiny SQLite layer shared by cane_reader.py and app.py."""
import json, sqlite3, time
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS events  (ts REAL, type TEXT, detail TEXT, simulated INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS strides (ts REAL, interval REAL, simulated INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS activity(minute REAL PRIMARY KEY, moving_s REAL, upright_s REAL, simulated INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS status  (key TEXT PRIMARY KEY, value TEXT, ts REAL);
"""

def connect():
    con = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    con.executescript(SCHEMA)
    return con

def log_event(con, kind, **detail):
    con.execute("INSERT INTO events VALUES (?,?,?,0)", (time.time(), kind, json.dumps(detail)))
    con.commit()

def log_stride(con, interval):
    con.execute("INSERT INTO strides VALUES (?,?,0)", (time.time(), interval))
    con.commit()

def add_activity(con, moving_s, upright_s):
    minute = int(time.time() // 60) * 60
    con.execute("""INSERT INTO activity VALUES (?,?,?,0) ON CONFLICT(minute) DO UPDATE SET
                   moving_s = moving_s + excluded.moving_s, upright_s = upright_s + excluded.upright_s""",
                (minute, moving_s, upright_s))
    con.commit()

def set_status(con, key, value):
    con.execute("INSERT OR REPLACE INTO status VALUES (?,?,?)", (key, json.dumps(value), time.time()))
    con.commit()

def get_status(con, key, default=None):
    row = con.execute("SELECT value FROM status WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default
