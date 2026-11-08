"""HTTP sync server for the phone (MASTER 7.2 Phase 1). Stdlib only, separate from canesense.

Routes (see mobile/PROTOCOL.md once the mobile agent lands it; these match the brief):
  GET  /info                         -> device info
  POST /time   {"phone_utc_ms": N}   -> shift this boot's unsynced rows
  GET  /pull?after_seq=N&limit=K     -> {records, next_cursor, more}
  POST /ack    {"up_to_seq": N}      -> mark delivered
It only talks to the SQLite store, so a crash here never affects fall detection.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cane.canesense.store import Store


def make_handler(store: Store):
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/info":
                return self._send(200, store.info())
            if u.path == "/pull":
                try:
                    return self._send(200, store.pull(int(q.get("after_seq", 0)), int(q.get("limit", 500))))
                except ValueError:
                    return self._send(400, {"error": "bad_params"})
            self._send(404, {"error": "not_found"})

        def do_POST(self):
            try:
                b = self._body()
                if self.path == "/time":
                    return self._send(200, store.time_sync(int(b["phone_utc_ms"])))
                if self.path == "/ack":
                    return self._send(200, {"acked": store.ack(int(b["up_to_seq"]))})
            except (KeyError, ValueError, json.JSONDecodeError):
                return self._send(400, {"error": "bad_body"})
            self._send(404, {"error": "not_found"})

        def log_message(self, *a):  # quiet
            pass

    return H


def serve(store: Store, host: str = "0.0.0.0", port: int = 8765) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), make_handler(store))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
