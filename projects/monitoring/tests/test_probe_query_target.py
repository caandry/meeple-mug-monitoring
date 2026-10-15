"""Local monitoring must preserve query parameters in HTTP request targets."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from meeple_monitor.monitor import Check, probe_local


def test_probe_preserves_query_and_empty_path():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        for suffix, expected in [
            ("/health?mode=full&view=all", "/health?mode=full&view=all"),
            ("?mode=full", "/?mode=full"),
            ("/health", "/health"),
        ]:
            check = Check("query-probe", f"http://127.0.0.1:{port}{suffix}")
            status, elapsed = probe_local(check)
            assert status == 200
            assert elapsed >= 0
            assert seen[-1] == expected
    finally:
        server.shutdown()
        server.server_close()
