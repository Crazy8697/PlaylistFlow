"""The automatic sign-in: a one-shot listener for Spotify's redirect.

While the wizard's sign-in step waits for the browser, this listens on
127.0.0.1:<port> (never 0.0.0.0, so nothing else on the network can reach it),
answers the /callback request with a short "you can close this tab" page and hands
the address to the wizard, which finishes the sign-in through SpotifyAuth.complete().
A request whose state isn't the one this sign-in sent is refused and ignored.

It stops as soon as the sign-in is caught, and on cancel, timeout or leaving the
step. When the port can't be bound, start() returns False and the wizard falls back
to pasting the address by hand.
"""

from __future__ import annotations

import hmac
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Playlist Flow</title>
<style>body{{background:#0c1016;color:#e6e9ee;font:16px Segoe UI,Arial,sans-serif;
display:flex;align-items:center;justify-content:center;height:90vh;margin:0}}
div{{max-width:30em;text-align:center}}h1{{font-size:22px}}p{{color:#9aa4b1}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p></div></body></html>"""

DONE = ("Signed in", "You can close this tab and go back to Playlist Flow.")
REFUSED = ("Sign-in link out of date",
           "This address doesn't belong to the sign-in Playlist Flow is waiting for. "
           "Go back to Playlist Flow and click Open Spotify sign-in again.")


class _Server(HTTPServer):
    # HTTPServer turns SO_REUSEADDR on, which on Windows would let another program
    # share the port; the opposite is wanted: exclusive, or not at all.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class CallbackListener:
    """start(state) -> bool; on_url(address) is called once, from the listener's
    thread, with the full redirect address. stop() is safe to call any time, twice,
    or from any thread other than the listener's own."""

    def __init__(self, port: int, on_url, path: str = "/callback"):
        self.port = int(port)
        self.on_url = on_url
        self.path = path
        self.state = ""
        self.caught = False
        self._srv: _Server | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def listening(self) -> bool:
        return self._srv is not None

    @property
    def address(self):
        return self._srv.server_address if self._srv else None

    def start(self, state: str) -> bool:
        self.stop()
        self.state, self.caught = state or "", False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):          # nothing logged anywhere
                pass

            def _page(self, code, title_text):
                body = PAGE.format(title=title_text[0], text=title_text[1]).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                if url.path != owner.path:
                    self.send_error(404)
                    return
                got = (urllib.parse.parse_qs(url.query).get("state") or [""])[0]
                if not owner.state or not got or not hmac.compare_digest(got, owner.state):
                    self._page(400, REFUSED)
                    return
                with owner._lock:
                    first = not owner.caught
                    owner.caught = True
                self._page(200, DONE)
                if first:
                    owner.on_url(f"http://{HOST}:{owner.port}{self.path}")

        try:
            srv = _Server((HOST, self.port), Handler)
        except OSError:
            return False
        srv.timeout = 0.5
        self._srv = srv
        self._thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="pf-signin-listener", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        srv, self._srv = self._srv, None
        if srv is None:
            return
        try:
            srv.shutdown()
        finally:
            srv.server_close()
        if self._thread is not None:
            self._thread.join(2)
            self._thread = None
