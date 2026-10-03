
"""S16: Snapshot metric selection and persistence tests."""

from __future__ import annotations

import json
import shutil

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.snapshot_settings import SnapshotSettingsStore
from tests.admin_support import sign_in, write_admin_secrets


DEFAULT_METRICS = [
    "asset_utilisation",
    "operating_efficiency",
    "effective_utilisation",
]


@pytest.fixture
def config_dir(tmp_path):
    """Create an isolated application configuration for each test."""

    for name in ("vehicles.yaml", "stops.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)

    app_config = yaml.safe_load(
        (DEFAULT_CONFIG_DIR / "app.yaml").read_text(encoding="utf-8")
    )

    app_config["storage"] = {
        "directory": str(tmp_path / "admin")
    }

    (tmp_path / "app.yaml").write_text(
        yaml.safe_dump(app_config, sort_keys=False),
        encoding="utf-8",
    )

    write_admin_secrets(tmp_path)
    return tmp_path


@pytest.fixture
def settings_file(config_dir):
    return config_dir / "admin" / "snapshot_settings.json"


@pytest.fixture
def client(config_dir):
    return sign_in(create_app(config_dir).test_client())


# ---- SnapshotSettingsStore ----


def test_missing_file_returns_defaults(tmp_path):
    store = SnapshotSettingsStore(tmp_path, DEFAULT_METRICS)

    assert store.load() == DEFAULT_METRICS


def test_save_writes_json(tmp_path):
    store = SnapshotSettingsStore(tmp_path, DEFAULT_METRICS)

    selected = ["asset_utilisation", "effective_utilisation"]
    assert store.save(selected) == selected

    saved = json.loads(
        (tmp_path / "snapshot_settings.json").read_text(encoding="utf-8")
    )

    assert saved == {"metrics": selected}


def test_settings_survive_new_store(tmp_path):
    store = SnapshotSettingsStore(tmp_path, DEFAULT_METRICS)

    selected = ["operating_efficiency"]
    store.save(selected)

    restarted = SnapshotSettingsStore(tmp_path, DEFAULT_METRICS)

    assert restarted.load() == selected


@pytest.mark.parametrize(
    "invalid_metrics",
    [
        [],
        ["unknown_metric"],
        ["asset_utilisation", "asset_utilisation"],
        "asset_utilisation",
        [123],
    ],
)
def test_invalid_metrics_are_rejected(tmp_path, invalid_metrics):
    store = SnapshotSettingsStore(tmp_path, DEFAULT_METRICS)

    with pytest.raises(ValueError):
        store.save(invalid_metrics)


def test_invalid_selection_does_not_overwrite_saved_file(tmp_path):
    store = SnapshotSettingsStore(tmp_path, DEFAULT_METRICS)

    selected = ["asset_utilisation"]
    store.save(selected)

    with pytest.raises(ValueError):
        store.save(["unknown_metric"])

    assert store.load() == selected


# ---- Admin API ----


def test_signed_out_is_401(config_dir):
    client = create_app(config_dir).test_client()

    assert client.get("/api/snapshot-settings").status_code == 401

    assert client.put(
        "/api/snapshot-settings",
        json={"metrics": DEFAULT_METRICS},
    ).status_code == 401


def test_get_returns_defaults(client):
    response = client.get("/api/snapshot-settings")

    assert response.status_code == 200
    assert response.get_json() == {"metrics": DEFAULT_METRICS}


def test_put_then_get(client, settings_file):
    selected = ["asset_utilisation", "effective_utilisation"]

    response = client.put(
        "/api/snapshot-settings",
        json={"metrics": selected},
    )

    assert response.status_code == 200
    assert response.get_json() == {"metrics": selected}

    assert client.get("/api/snapshot-settings").get_json() == {
        "metrics": selected
    }

    assert json.loads(
        settings_file.read_text(encoding="utf-8")
    ) == {"metrics": selected}


def test_settings_survive_app_restart(config_dir, client):
    selected = ["operating_efficiency"]

    response = client.put(
        "/api/snapshot-settings",
        json={"metrics": selected},
    )

    assert response.status_code == 200

    restarted = sign_in(create_app(config_dir).test_client())

    assert restarted.get("/api/snapshot-settings").get_json() == {
        "metrics": selected
    }


@pytest.mark.parametrize(
    "body",
    [
        {"metrics": []},
        {"metrics": ["invalid_metric"]},
        {"metrics": ["asset_utilisation", "asset_utilisation"]},
        {"metrics": "asset_utilisation"},
        {},
        [],
    ],
)
def test_invalid_put_returns_400(client, body):
    response = client.put(
        "/api/snapshot-settings",
        json=body,
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] in {
        "invalid_request",
        "invalid_metrics",
    }


def test_invalid_put_preserves_previous_selection(client):
    selected = ["asset_utilisation"]

    assert client.put(
        "/api/snapshot-settings",
        json={"metrics": selected},
    ).status_code == 200

    assert client.put(
        "/api/snapshot-settings",
        json={"metrics": ["invalid_metric"]},
    ).status_code == 400

    assert client.get("/api/snapshot-settings").get_json() == {
        "metrics": selected
    }


def test_corrupt_file_returns_500(client, settings_file):
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text("{invalid json", encoding="utf-8")

    response = client.get("/api/snapshot-settings")

    assert response.status_code == 500
    assert response.get_json()["error"]["code"] == "data_unavailable"
