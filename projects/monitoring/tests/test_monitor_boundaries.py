"""Reject invalid monitor settings and samples before persistence."""

import sqlite3
from typing import Any

import pytest
from meeple_monitor.monitor import Check, record


@pytest.mark.parametrize("field,value", [
    ("threshold_ms", True),
    ("threshold_ms", 0),
    ("threshold_ms", 1.5),
    ("failures_before_alert", False),
    ("failures_before_alert", -1),
    ("failures_before_alert", 2.5),
    ("name", "   "),
])
def test_invalid_monitor_configuration(field, value):
    values: dict[str, Any] = {"name": "web", "url": "http://127.0.0.1:8000/", "threshold_ms": 400,
              "failures_before_alert": 2}
    values[field] = value
    with pytest.raises(ValueError):
        Check(**values)


@pytest.mark.parametrize("status,elapsed", [
    (True, 1), (-1, 1), (99, 1), (600, 1), (200.5, 1), (200, True),
    (200, -1), (200, 1.1),
])
def test_invalid_sample_does_not_create_db(tmp_path, status, elapsed):
    db = tmp_path / "monitor.sqlite"
    with pytest.raises(ValueError):
        record(db, Check("web", "http://127.0.0.1:8000/"), status, elapsed, "t1")
    assert not db.exists()


def test_valid_sample_still_records(tmp_path):
    db = tmp_path / "monitor.sqlite"
    assert record(db, Check("web", "http://127.0.0.1:8000/"), 200, 12, "t1")["healthy"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
