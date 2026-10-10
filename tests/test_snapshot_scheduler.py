
"""Tests for daily snapshot scheduling (S17)."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.snapshot_scheduler import SnapshotScheduler
from backend.snapshots import SnapshotStore


PERTH = ZoneInfo("Australia/Perth")


def perth_time(day, hour=0, minute=0):
    return datetime(
        day.year, day.month, day.day,
        hour, minute,
        tzinfo=PERTH,
    )


def test_generate_after_midnight(tmp_path):
    store = SnapshotStore(tmp_path)
    generated = []

    def generate(day):
        generated.append(day)
        store.save(day, {"date": day.isoformat()})

    scheduler = SnapshotScheduler(tmp_path, store, generate)

    scheduler.start(perth_time(date(2026, 10, 8), 20))
    scheduler.check(perth_time(date(2026, 10, 9), 0, 1))

    assert generated == [date(2026, 10, 8)]
    assert store.exists(date(2026, 10, 8))


def test_missing_when_logger_restarts(tmp_path):
    store = SnapshotStore(tmp_path)
    generated = []

    scheduler = SnapshotScheduler(
        tmp_path,
        store,
        lambda day: generated.append(day),
    )

    scheduler.start(perth_time(date(2026, 10, 8), 20))

    # Logger was stopped before midnight.
    # It restarts the next morning.
    scheduler.start(perth_time(date(2026, 10, 9), 10))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert "2026-10-08" in state["missing"]
    assert generated == []
    assert not store.exists(date(2026, 10, 8))


def test_no_duplicate_snapshot(tmp_path):
    store = SnapshotStore(tmp_path)
    generated = []

    def generate(day):
        generated.append(day)
        store.save(day, {"date": day.isoformat()})

    scheduler = SnapshotScheduler(tmp_path, store, generate)

    scheduler.start(perth_time(date(2026, 10, 8), 20))
    scheduler.check(perth_time(date(2026, 10, 9), 0, 1))
    scheduler.check(perth_time(date(2026, 10, 9), 0, 2))

    assert generated == [date(2026, 10, 8)]


def test_first_start_does_not_backfill(tmp_path):
    store = SnapshotStore(tmp_path)
    generated = []

    scheduler = SnapshotScheduler(
        tmp_path,
        store,
        lambda day: generated.append(day),
    )

    scheduler.start(perth_time(date(2026, 10, 9), 10))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert state["last_checked"] == "2026-10-09"
    assert state["missing"] == []
    assert generated == []


def test_generation_failure_does_not_stop_scheduler(tmp_path):
    store = SnapshotStore(tmp_path)
    attempts = []

    def failing_generate(day):
        attempts.append(day)
        raise RuntimeError("Simulated snapshot failure")

    scheduler = SnapshotScheduler(
        tmp_path,
        store,
        failing_generate,
    )

    scheduler.start(perth_time(date(2026, 10, 8), 20))

    # Generation fails just after midnight.
    scheduler.check(perth_time(date(2026, 10, 9), 0, 1))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert attempts == [date(2026, 10, 8)]
    assert state["last_checked"] == "2026-10-08"
    assert not store.exists(date(2026, 10, 8))

    # Still inside the retry window, so it tries again.
    scheduler.check(perth_time(date(2026, 10, 9), 0, 10))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert len(attempts) == 2
    assert state["last_checked"] == "2026-10-08"
    assert state["missing"] == []

    # One last attempt after the window, then the day is recorded as missing.
    scheduler.check(perth_time(date(2026, 10, 9), 1, 10))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert len(attempts) == 3
    assert "2026-10-08" in state["missing"]
    assert state["last_checked"] == "2026-10-09"

    scheduler.check(perth_time(date(2026, 10, 9), 1, 11))

    assert len(attempts) == 3


def test_generates_when_the_first_check_after_midnight_is_late(tmp_path):
    store = SnapshotStore(tmp_path)
    generated = []

    def generate(day):
        generated.append(day)
        store.save(day, {"date": day.isoformat()})

    scheduler = SnapshotScheduler(tmp_path, store, generate)

    scheduler.start(perth_time(date(2026, 10, 8), 20))

    # A feed outage held the polls up well past midnight.
    scheduler.check(perth_time(date(2026, 10, 9), 0, 40))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert generated == [date(2026, 10, 8)]
    assert state["missing"] == []
    assert state["last_checked"] == "2026-10-09"


def test_retry_succeeds_after_a_failure(tmp_path):
    store = SnapshotStore(tmp_path)
    attempts = []

    def generate(day):
        attempts.append(day)
        if len(attempts) == 1:
            raise RuntimeError("Simulated snapshot failure")
        store.save(day, {"date": day.isoformat()})

    scheduler = SnapshotScheduler(tmp_path, store, generate)

    scheduler.start(perth_time(date(2026, 10, 8), 20))
    scheduler.check(perth_time(date(2026, 10, 9), 0, 1))
    scheduler.check(perth_time(date(2026, 10, 9), 0, 2))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert store.exists(date(2026, 10, 8))
    assert state["missing"] == []
    assert state["last_checked"] == "2026-10-09"


@pytest.mark.parametrize("content", ["{not json", "[]", "{}", '{"last_checked": "soon"}',
                                     '{"last_checked": "2026-10-08", "missing": "none"}'])
def test_unreadable_state_starts_afresh(tmp_path, content, caplog):
    store = SnapshotStore(tmp_path)
    generated = []
    scheduler = SnapshotScheduler(tmp_path, store, generated.append)

    scheduler.path.write_text(content, encoding="utf-8")
    scheduler.start(perth_time(date(2026, 10, 9), 10))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert state == {"last_checked": "2026-10-09", "missing": []}
    assert "Ignoring unreadable snapshot schedule" in caplog.text

    scheduler.path.write_text(content, encoding="utf-8")
    scheduler.check(perth_time(date(2026, 10, 9), 11))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert state == {"last_checked": "2026-10-09", "missing": []}
    assert generated == []


def test_check_survives_a_deleted_state_file(tmp_path):
    store = SnapshotStore(tmp_path)
    scheduler = SnapshotScheduler(tmp_path, store, lambda day: None)

    scheduler.start(perth_time(date(2026, 10, 9), 10))
    scheduler.path.unlink()
    scheduler.check(perth_time(date(2026, 10, 9), 11))

    state = json.loads(scheduler.path.read_text(encoding="utf-8"))

    assert state == {"last_checked": "2026-10-09", "missing": []}
