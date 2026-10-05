"""Open the inspector with saving switched on.

    python -m semalpha.serve                     # http://127.0.0.1:8766, opens your browser
    python -m semalpha.serve 9000 --no-browser

The page is the same as outputs/inspector.html. The difference is the Save button: here it
writes your edited expectations to semalpha/expectations.json, so `python -m
semalpha.label` and `python -m semalpha.verify` use them from then on. Opened as a plain
file, the page can only offer the edited file as a download.

The server listens on this computer only and can write nothing but that one file.
Stop it with Ctrl+C.
"""
from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from semalpha import expected
from semalpha.inspector import render

MAX_BODY = 4_000_000   # bytes; the whole expectations file is about 40 kB


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, kind: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, answer: dict) -> None:
        self._send(status, json.dumps(answer).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/inspector.html"):
            self._send(200, render().encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/ping":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/api/expectations":
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("empty or oversized request")
            posted = json.loads(self.rfile.read(length).decode("utf-8"))
            expected.check(posted)
            data = expected.read()
            data.update(posted)            # runs the page does not know about are kept as they are
            expected.write(data)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            return self._json(400, {"ok": False, "error": str(error)})
        print(f"saved {len(posted)} expectations to {expected.FILE}")
        self._json(200, {"ok": True, "stamp": expected.stamp()})

    def log_message(self, *args):      # keep the terminal quiet; saves are announced above
        pass


def main(argv) -> int:
    ports = [a for a in argv if a.isdigit()]
    port = int(ports[0]) if ports else 8766
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Inspector with saving: {url}\nLabelling the recorded runs for the first page takes a few seconds. Ctrl+C to stop.")
    if "--no-browser" not in argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
