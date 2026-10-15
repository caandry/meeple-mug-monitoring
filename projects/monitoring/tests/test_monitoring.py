"""Incident lifecycle and endpoint safety tests."""
import pytest
from meeple_monitor.monitor import Check, history, record


def test_alert_opens_only_after_two_failures_and_recovers(tmp_path):
    db = tmp_path / "monitor.sqlite"
    check = Check("website", "http://localhost:8000/health")
    assert record(db, check, 503, 100, "t1")["incident_action"] == "none"
    assert record(db, check, 503, 100, "t2")["incident_action"] == "opened"
    assert record(db, check, 503, 100, "t3")["incident_action"] == "none"
    assert len(history(db)["open_incidents"]) == 1
    assert record(db, check, 200, 45, "t4")["incident_action"] == "resolved"
    assert history(db)["open_incidents"] == []
    assert history(db)["services"][0]["healthy_checks"] == 1


def test_latency_counts_as_failure(tmp_path):
    check = Check("website", "http://127.0.0.1:9000/", threshold_ms=100, failures_before_alert=1)
    assert record(tmp_path / "db.sqlite", check, 200, 101, "t1")["incident_action"] == "opened"


@pytest.mark.parametrize("url", [
    "http://example.org:80/", "https://127.0.0.1:8000/", "http://10.0.0.1:5000/",
    "http://localhost:8000/#secret", "http://user:pw@localhost:8000/",
    "http://localhost/",
])
def test_nonlocal_or_unsafe_targets_rejected(url):
    with pytest.raises(ValueError):
        Check("service", url)


def test_actual_authorized_local_http_probe():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from meeple_monitor.monitor import probe_local

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        check = Check("authorized", f"http://127.0.0.1:{server.server_address[1]}/")
        status, elapsed = probe_local(check)
        assert status == 200
        assert elapsed >= 0
    finally:
        server.shutdown()
        server.server_close()
