
"""Tests for daily snapshot generation (S17)."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from backend.snapshot_generator import generate_daily_snapshot
from backend.snapshots import SnapshotStore


def test_generate_daily_snapshot(tmp_path):
    day = date(2026, 10, 8)
    store = SnapshotStore(tmp_path)

    config = SimpleNamespace(
        live_directory=tmp_path,
        vehicles=[],
    )

    settings_store = SimpleNamespace(
        load=lambda: ["asset_utilisation"]
    )

    with (
        patch(
            "backend.snapshot_generator.Settings.from_config",
            return_value=object(),
        ),
        patch(
            "backend.snapshot_generator.with_synced_roster",
            return_value=object(),
        ),
    ):
        snapshot = generate_daily_snapshot(
            day,
            config,
            settings_store,
            store,
        )

    assert snapshot["date"] == "2026-10-08"
    assert snapshot["timezone"] == "Australia/Perth"
    assert snapshot["from"] == "2026-10-07T16:00:00+00:00"
    assert snapshot["to"] == "2026-10-08T16:00:00+00:00"
    assert snapshot["metrics"] == ["asset_utilisation"]
    assert snapshot["vehicles"] == []

    assert store.exists(day)
    assert store.load(day) == snapshot


def test_snapshot_selected_vehicle_metrics(tmp_path):
    day = date(2026, 10, 8)
    store = SnapshotStore(tmp_path)

    config = SimpleNamespace(
        live_directory=tmp_path,
        vehicles=[],
    )

    settings_store = SimpleNamespace(
        load=lambda: [
            "asset_utilisation",
            "operating_efficiency",
        ]
    )

    fake_result = {
        "kpis": {
            "asset_utilisation": 0.75,
            "operating_efficiency": None,
            "uptime": 0.90,
        },
        "unavailable": {
            "operating_efficiency": "Insufficient data",
        },
    }

    with (
        patch("backend.snapshot_generator.CsvRepository") as repo_class,
        patch("backend.snapshot_generator.summarise") as mock_summarise,
        patch(
            "backend.snapshot_generator.Settings.from_config",
            return_value=object(),
        ),
        patch(
            "backend.snapshot_generator.with_synced_roster",
            return_value=object(),
        ),
    ):
        repository = repo_class.return_value
        repository.vehicle_ids.return_value = ["vehicle_1"]
        repository.get_positions.return_value = {"vehicle_1": []}

        mock_summarise.return_value.to_dict.return_value = fake_result

        snapshot = generate_daily_snapshot(
            day,
            config,
            settings_store,
            store,
        )

    vehicle = snapshot["vehicles"][0]

    assert vehicle["vehicle_id"] == "vehicle_1"
    assert vehicle["kpis"] == {
        "asset_utilisation": 0.75,
        "operating_efficiency": None,
    }
    assert vehicle["unavailable"] == {
        "operating_efficiency": "Insufficient data",
    }
    assert store.load(day) == snapshot
