"""Local-only service monitoring with persistent incident history."""
import argparse
import http.client
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
 id INTEGER PRIMARY KEY,service TEXT NOT NULL,checked_at TEXT NOT NULL,
 status_code INTEGER,response_ms INTEGER NOT NULL,healthy INTEGER NOT NULL CHECK(healthy IN(0,1)));
CREATE INDEX IF NOT EXISTS samples_service ON samples(service,id);
CREATE TABLE IF NOT EXISTS incidents (
 id INTEGER PRIMARY KEY,service TEXT NOT NULL,opened_at TEXT NOT NULL,
 resolved_at TEXT,reason TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS open_incident ON incidents(service) WHERE resolved_at IS NULL;
"""


@dataclass(frozen=True)
class Check:
    """An explicitly configured local service."""

    name: str
    url: str
    threshold_ms: int = 400
    failures_before_alert: int = 2

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Only local HTTP endpoints are permitted")
        if parsed.username or parsed.password or parsed.fragment or parsed.port is None:
            raise ValueError("Supply a local port without credentials or fragment")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Monitor name must be a nonblank string")
        if type(self.threshold_ms) is not int or self.threshold_ms <= 0:
            raise ValueError("threshold_ms must be a positive integer")
        if type(self.failures_before_alert) is not int or self.failures_before_alert < 1:
            raise ValueError("failures_before_alert must be a positive integer")


def probe_local(check: Check, timeout: float = 2.0) -> tuple[int | None, int]:
    """Probe loopback only, no redirects; failed connections count as downtime."""
    parts = urlsplit(check.url)
    start = time.perf_counter()
    connection = http.client.HTTPConnection("127.0.0.1", parts.port, timeout=timeout)
    try:
        request_target = parts.path or "/"
        if parts.query:
            request_target += f"?{parts.query}"
        connection.request("GET", request_target, headers={"Host": "localhost"})
        response = connection.getresponse()
        code = response.status
        response.read(4096)
    except (OSError, TimeoutError, http.client.HTTPException):
        code = None
    finally:
        connection.close()
    elapsed = max(0, int((time.perf_counter() - start) * 1000))
    return code, elapsed


def record(db_path: str | Path, check: Check, status: int | None,
           elapsed_ms: int, checked_at: str) -> dict:
    """Open an incident after N bad samples; close after a healthy sample.

    Samples are appended in order. Complexity O(N) for N consecutive recent
    samples up to threshold. A partial outage is distinguished from a slow site.
    """
    if type(elapsed_ms) is not int or elapsed_ms < 0:
        raise ValueError("elapsed_ms must be a nonnegative integer")
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError("status must be an HTTP status code or None")
    healthy = status is not None and 200 <= status < 300 and elapsed_ms <= check.threshold_ms
    reason = "unreachable or HTTP error" if status is None or not 200 <= status < 300 else "slow response"
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(SCHEMA)
        with connection:
            connection.execute(
                "INSERT INTO samples(service,checked_at,status_code,response_ms,healthy) VALUES(?,?,?,?,?)",
                (check.name, checked_at, status, elapsed_ms, int(healthy)),
            )
            recent = connection.execute(
                "SELECT healthy FROM samples WHERE service=? ORDER BY id DESC LIMIT ?",
                (check.name, check.failures_before_alert),
            ).fetchall()
            streak = len(recent) >= check.failures_before_alert
            for row in recent:
                if row[0] != 0:
                    streak = False
                    break
            open_incident = connection.execute(
                "SELECT id FROM incidents WHERE service=? AND resolved_at IS NULL",
                (check.name,),
            ).fetchone()
            action = "none"
            if healthy and open_incident is not None:
                connection.execute(
                    "UPDATE incidents SET resolved_at=? WHERE id=?",
                    (checked_at, open_incident[0]),
                )
                action = "resolved"
            elif streak and open_incident is None:
                connection.execute(
                    "INSERT INTO incidents(service,opened_at,reason) VALUES(?,?,?)",
                    (check.name, checked_at, reason),
                )
                action = "opened"
        return {"service": check.name, "healthy": healthy, "response_ms": elapsed_ms,
                "status_code": status, "incident_action": action}
    finally:
        connection.close()


def history(db_path: str | Path) -> dict:
    """Summarize recorded measurements and open incidents."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SCHEMA)
        samples = connection.execute(
            "SELECT service,COUNT(*) AS checks,SUM(healthy) AS healthy_checks,"
            "ROUND(AVG(response_ms),1) AS average_ms FROM samples GROUP BY service"
        ).fetchall()
        incidents = connection.execute(
            "SELECT service,opened_at,reason FROM incidents WHERE resolved_at IS NULL"
        ).fetchall()
        return {"services": [dict(s) for s in samples],
                "open_incidents": [dict(i) for i in incidents]}
    finally:
        connection.close()


def main() -> None:
    """Run a single local probe or use deterministic offline simulation."""
    from datetime import UTC, datetime

    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--name", default="local-website")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--simulate", choices=["healthy", "down", "slow"])
    args = parser.parse_args()
    check = Check(args.name, args.url)
    result: tuple[int | None, int]
    if args.simulate == "healthy":
        result = (200, 40)
    elif args.simulate == "down":
        result = (503, 90)
    elif args.simulate == "slow":
        result = (200, 800)
    else:
        result = probe_local(check)
    stamp = datetime.now(UTC).isoformat()
    print(json.dumps(record(args.database, check, *result, stamp), indent=2))
    print(json.dumps(history(args.database), indent=2))


if __name__ == "__main__":
    main()
