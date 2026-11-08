"""Local feed for the cane: logged events, live status, and the voice clips.

The master plan (app/MASTER.md) makes the phone<->cane link HTTP-over-local-Wi-Fi
first. This is the firmware side of that link, read-only: it never writes to the
database and never calls anything off the Pi.

SAFE DEFAULT: binds to 127.0.0.1 (this Pi only). Nothing is reachable from the network.

Phone testing on a Wi-Fi network you trust:
    .venv/bin/python cane_server.py --lan
LAN mode prints a one-time pairing code on the Pi's screen. The phone page asks for
that code once; without it, the feed and the clips answer 401. The code changes every
time the server starts. Never port-forward this server, and never use LAN mode on a
network you do not trust (event logs reveal daily activity patterns).

Endpoints:
  / or /voice_preview.html   the phone test page (contains no data itself)
  /events?since=<seq>        events after <seq>: seq/ts/type only, no details; seq is
                             the SQLite rowid, a stable device-local sequence
  /status                    latest detector status keys
  /voice/<key>.mp3|.wav      the voice clips
  POST /pair {"code": ...}   exchanges the pairing code for a session cookie
Only the paths above are served. Source files, the database and directory listings
are never served. time_quality says whether the Pi clock is network-synced (the Pi
has no real-time clock).
"""
import argparse, http.cookies, json, os, re, secrets, subprocess
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import db

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(ROOT, "voice_preview.html")
CLIP_RE = re.compile(r"^/voice/([A-Za-z0-9_-]{1,40})\.(mp3|wav)$")
MIME = {"mp3": "audio/mpeg", "wav": "audio/wav"}

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

class Handler(BaseHTTPRequestHandler):
    pairing_code = None                # set only in LAN mode

    def log_message(self, *a):         # never log request lines (they could carry codes)
        pass

    # --- helpers ---------------------------------------------------------
    def _authed(self):
        if not self.pairing_code:
            return True                # loopback mode: this Pi only, nothing to pair against
        c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        m = c.get("cane_session")
        return m is not None and secrets.compare_digest(m.value, self.pairing_code)

    def _send(self, code, body=b"", ctype="text/plain", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200, extra=None):
        self._send(code, json.dumps(obj).encode(), "application/json", extra)

    # --- routes ----------------------------------------------------------
    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/pair" and self.pairing_code:
            n = min(int(self.headers.get("Content-Length") or 0), 200)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            if secrets.compare_digest(str(body.get("code", "")), self.pairing_code):
                self._json({"paired": True},
                           extra={"Set-Cookie": "cane_session=%s; SameSite=Strict; Path=/; HttpOnly" % self.pairing_code})
            else:
                self._json({"error": "wrong code"}, 403)
        else:
            self._send(404)

    def do_GET(self):
        self._route(head=False)

    def do_HEAD(self):                 # the page probes clips with HEAD
        self._route(head=True)

    def _route(self, head):
        u = urlparse(self.path)
        if u.path in ("/", "/voice_preview.html"):
            self._send(200, b"" if head else open(PAGE, "rb").read(), "text/html; charset=utf-8")
            return
        if not self._authed():
            self._json({"error": "pairing required"}, 401)
            return
        if u.path == "/events":
            try:
                since = int(parse_qs(u.query).get("since", ["0"])[0] or 0)
            except ValueError:
                since = 0
            rows = _query("SELECT rowid, ts, type FROM events WHERE rowid>? ORDER BY rowid LIMIT 200", (since,))
            import config                 # lazy, like db: capability signal for the phone app
            self._json({"device": "cane", "time_quality": time_quality(), "fw": config.FW_VERSION,
                        "events": [{"seq": r[0], "ts": r[1], "type": r[2]} for r in rows]})
        elif u.path == "/status":
            rows = _query("SELECT key, value, ts FROM status")
            self._json({"device": "cane", "time_quality": time_quality(),
                        "status": {k: {"value": json.loads(v), "ts": t} for k, v, t in rows}})
        else:
            m = CLIP_RE.match(u.path)
            if m:
                p = os.path.join(ROOT, "voice", m.group(1) + "." + m.group(2))
                if os.path.isfile(p):
                    body = b"" if head else open(p, "rb").read()
                    self._send(200, body, MIME[m.group(2)])
                    return
            self._send(404)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cane local feed (safe loopback default)")
    ap.add_argument("--lan", action="store_true",
                    help="serve the local network with a one-time pairing code (trusted Wi-Fi only)")
    ap.add_argument("--port", type=int, default=int(os.getenv("CANE_FEED_PORT", "8000")))
    a = ap.parse_args()
    if a.lan:
        Handler.pairing_code = secrets.token_urlsafe(8)
        print("LAN mode on a TRUSTED network only. Phone pairing code (this session only):", Handler.pairing_code, flush=True)
        bind = "0.0.0.0"
    else:
        bind = "127.0.0.1"
        print("Loopback mode: reachable from this Pi only. Use --lan on a trusted network for phone testing.", flush=True)
    print(f"Cane feed on http://{bind}:{a.port} - phone page: /voice_preview.html", flush=True)
    ThreadingHTTPServer((bind, a.port), Handler).serve_forever()
