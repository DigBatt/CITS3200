
"""Tests for daily snapshot storage (S17)."""

from datetime import date

import pytest

from backend.snapshots import SnapshotStore


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path)


def test_save_and_load(store):
    day = date(2026, 10, 8)
    snapshot = {
        "date": "2026-10-08",
        "metrics": ["asset_utilisation"],
        "vehicles": [],
    }

    store.save(day, snapshot)

    assert store.exists(day)
    assert store.load(day) == snapshot


def test_duplicate_snapshot(store):
    day = date(2026, 10, 8)

    store.save(day, {"date": "2026-10-08"})

    with pytest.raises(FileExistsError):
        store.save(day, {"date": "2026-10-08"})


def test_list_dates(store):
    store.save(date(2026, 10, 7), {"date": "2026-10-07"})
    store.save(date(2026, 10, 8), {"date": "2026-10-08"})

    assert store.list_dates() == [
        date(2026, 10, 8),
        date(2026, 10, 7),
    ]


def test_empty_store(store):
    assert store.list_dates() == []
    assert not store.exists(date(2026, 10, 8))


def test_missing_snapshot(store):
    with pytest.raises(FileNotFoundError):
        store.load(date(2026, 10, 8))
