"""Local-network feed for the cane: logged events, live status, and the voice clips.

The master plan (app/MASTER.md) makes the phone<->cane link HTTP-over-local-Wi-Fi first.
This is the firmware side of that link, read-only: it never writes to the database
and never calls anything off the Pi.

Run from the pi/ folder:   .venv/bin/python cane_server.py
Then on a phone on the same Wi-Fi open:   http://<pi-ip>:8000/voice_preview.html

Endpoints:
  /events?since=<seq>  new logged events after <seq>; seq is the SQLite rowid, a
                       stable device-local sequence. time_quality says whether the
                       Pi's clock is network-synced (the Pi has no real-time clock).
  /status              latest detector status keys.
  /voice_preview.html  phone page: test clips manually or auto-play them on events.
  /voice/<key>.mp3     the voice clips themselves.
"""
import json, os, sqlite3, subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import db

ROOT = os.path.dirname(os.path.abspath(__file__))

def time_quality():
    """The Pi has no RTC; report whether the clock is network-synced."""
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
        return "synced" if out == "yes" else "unsynced"
    except Exception:
        return "unknown"

def _query(sql, args=()):
    con = db.connect()                 # creates the schema if the reader has not run yet
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")   # phone browser on the same LAN
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/events":
            try:
                since = int(parse_qs(u.query).get("since", ["0"])[0] or 0)
            except ValueError:
                since = 0
            rows = _query("SELECT rowid, ts, type, detail FROM events WHERE rowid>? ORDER BY rowid LIMIT 200", (since,))
            self._json({"device": "cane", "time_quality": time_quality(),
                        "events": [{"seq": r[0], "ts": r[1], "type": r[2],
                                    "detail": json.loads(r[3] or "{}")} for r in rows]})
        elif u.path == "/status":
            rows = _query("SELECT key, value, ts FROM status")
            self._json({"device": "cane", "time_quality": time_quality(),
                        "status": {k: {"value": json.loads(v), "ts": t} for k, v, t in rows}})
        else:
            super().do_GET()   # static files from pi/: /voice_preview.html, /voice/...

if __name__ == "__main__":
    port = int(os.getenv("CANE_FEED_PORT", "8000"))
    print(f"Cane feed on http://0.0.0.0:{port} - phone page: http://<pi-ip>:{port}/voice_preview.html")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
