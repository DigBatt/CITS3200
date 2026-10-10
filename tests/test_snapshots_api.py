
"""Tests for S17 daily snapshot admin API."""

import json
import shutil
from datetime import date

from backend.app import create_app
from backend.snapshots import SnapshotStore
from backend.snapshot_scheduler import SnapshotScheduler
from backend.config import DEFAULT_CONFIG_DIR
from tests.admin_support import sign_in, write_admin_secrets


def test_snapshot_list_and_download(tmp_path):
    # Create a temporary configuration with test admin credentials.
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    for name in ("app.yaml", "vehicles.yaml", "stops.json"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, config_dir / name)

    write_admin_secrets(config_dir)

    app = create_app(config_dir)
    app.config["TESTING"] = True

    store = SnapshotStore(tmp_path)
    day = date(2026, 10, 7)

    snapshot = {
        "date": day.isoformat(),
        "timezone": "Australia/Perth",
        "from": "2026-10-06T16:00:00+00:00",
        "to": "2026-10-07T16:00:00+00:00",
        "metrics": ["asset_utilisation"],
        "vehicles": [],
    }

    store.save(day, snapshot)

    scheduler = SnapshotScheduler(tmp_path, store, generate=None)
    scheduler._save_state({
        "last_checked": "2026-10-09",
        "missing": ["2026-10-08"],
    })

    app.config["SNAPSHOT_STORE"] = store
    app.config["SNAPSHOT_SCHEDULE_STORE"] = scheduler

    # Test through the Flask client.
    # Admin authentication is handled by the existing project setup.
    with app.test_client() as client:
        sign_in(client)

        response = client.get("/api/snapshots")
        assert response.status_code == 200

        data = response.get_json()
        assert day.isoformat() in data["available"]
        assert "2026-10-08" in data["missing"]

        response = client.get(
            f"/api/snapshots/{day.isoformat()}/download"
        )
        assert response.status_code == 200
        assert json.loads(response.data) == snapshot

        response = client.get(
            "/api/snapshots/2026-10-08/download"
        )
        assert response.status_code == 404

def test_snapshot_endpoints_require_admin(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    for name in ("app.yaml", "vehicles.yaml", "stops.json"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, config_dir / name)

    write_admin_secrets(config_dir)

    app = create_app(config_dir)
    app.config["TESTING"] = True

    with app.test_client() as client:
        assert client.get("/api/snapshots").status_code == 401
        assert client.get(
            "/api/snapshots/2026-10-07/download"
        ).status_code == 401
