"""
Pickup requests: backend.pickup_requests and the /api/pickup-requests
endpoints (S08).
"""

from __future__ import annotations
import shutil

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR


def stop(stop_id, latitude=-31.98, longitude=115.82, name=None):
    name = str(stop_id).title() if name is None else name
    return {"id": stop_id, "name": name, "latitude": latitude, "longitude": longitude}


NETWORK = {
    "stops": [stop("reid-library"), stop("civ-mech")],
    "routes": [{"id": "campus-loop", "name": "Campus loop", "stops": ["reid-library", "civ-mech"]}],
}


@pytest.fixture
def config_dir(tmp_path):
    """
    A copy of the real config directory whose stops.yaml a test can rewrite.
    """
    for name in ("app.yaml", "vehicles.yaml", "stops.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    (tmp_path / "stops.yaml").write_text(yaml.safe_dump(NETWORK, sort_keys=False), encoding="utf-8")
    return tmp_path


@pytest.fixture
def app(config_dir):
    return create_app(config_dir)


@pytest.fixture
def client(app):
    return app.test_client()


# ---- S08.3: create-request endpoint ----


def test_unknown_stop_is_400(client):
    response = client.post("/api/pickup-requests", json={"stop_id": "zzz"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_stop"


def test_missing_stop_id_is_400(client):
    response = client.post("/api/pickup-requests", json={})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_stop"


def test_create_request_needs_no_login(client):
    """
    No auth header, no session, no prior request. S08.5.
    """
    response = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    assert response.status_code == 201
    body = response.get_json()["request"]
    assert body["stop_id"] == "reid-library"
    assert body["status"] == "open"
    assert body["cleared_at"] is None
    assert "rider_token" not in body


def test_create_request_issues_a_rider_cookie(client):
    response = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    assert "rider_token=" in response.headers.get("Set-Cookie", "")


# ---- S08.5: duplicate suppression ----


def test_duplicate_request_same_rider_same_stop_is_suppressed(client):
    first = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    second = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.get_json()["request"]["id"] == second.get_json()["request"]["id"]

    listed = client.get("/api/pickup-requests").get_json()["requests"]
    assert len(listed) == 1


def test_same_rider_different_stop_is_not_a_duplicate(client):
    client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    second = client.post("/api/pickup-requests", json={"stop_id": "civ-mech"})

    assert second.status_code == 201
    listed = client.get("/api/pickup-requests").get_json()["requests"]
    assert len(listed) == 2


def test_different_riders_at_the_same_stop_are_not_duplicates(app):
    rider_a = app.test_client()
    rider_b = app.test_client()

    rider_a.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    response = rider_b.post("/api/pickup-requests", json={"stop_id": "reid-library"})

    assert response.status_code == 201
    listed = rider_a.get("/api/pickup-requests").get_json()["requests"]
    assert len(listed) == 2


# ---- GET /api/pickup-requests ----


def test_list_is_empty_with_no_requests(client):
    assert client.get("/api/pickup-requests").get_json()["requests"] == []


def test_list_can_filter_by_status(client):
    client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    body = client.get("/api/pickup-requests?status=open").get_json()
    assert len(body["requests"]) == 1
    assert client.get("/api/pickup-requests?status=collected").get_json()["requests"] == []


# ---- S08.5: a new stop appearing in the list ----


def test_new_stop_can_be_requested_with_no_code_change(config_dir):
    raw = yaml.safe_load((config_dir / "stops.yaml").read_text(encoding="utf-8"))
    raw["stops"].append(stop("new-stop", name="New Stop"))
    (config_dir / "stops.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    client = create_app(config_dir).test_client()
    response = client.post("/api/pickup-requests", json={"stop_id": "new-stop"})
    assert response.status_code == 201
    assert response.get_json()["request"]["stop_id"] == "new-stop"
