"""
Pickup requests: backend.pickup_requests and the /api/pickup-requests
endpoints (S08).
"""

from __future__ import annotations
import json
import shutil

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from tests.admin_support import allow_pickup_requests_any_time, sign_in, write_admin_secrets


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
    A copy of the real config directory whose stops.json a test can rewrite.
    """
    for name in ("app.yaml", "vehicles.yaml", "stops.json"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    (tmp_path / "stops.json").write_text(json.dumps(NETWORK), encoding="utf-8")
    # Not testing operating hours here: open every day, so this suite does
    # not depend on what time it is when it runs.
    allow_pickup_requests_any_time(tmp_path)
    write_admin_secrets(tmp_path)
    return tmp_path


@pytest.fixture
def app(config_dir):
    return create_app(config_dir)


@pytest.fixture
def client(app):
    # Signed in: the operator and list endpoints are admin-only (S13).
    return sign_in(app.test_client())


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
    # Listing is admin-only (S13), so check as the admin, not as either rider.
    listed = sign_in(app.test_client()).get("/api/pickup-requests").get_json()["requests"]
    assert len(listed) == 2


# ---- GET /api/pickup-requests ----


def test_list_is_empty_with_no_requests(client):
    assert client.get("/api/pickup-requests").get_json()["requests"] == []


def test_list_can_filter_by_status(client):
    client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    body = client.get("/api/pickup-requests?status=open").get_json()
    assert len(body["requests"]) == 1
    assert client.get("/api/pickup-requests?status=collected").get_json()["requests"] == []


# ---- S15: GET /api/pickup-requests/mine ----


def test_mine_is_null_with_no_rider_cookie(client):
    assert client.get("/api/pickup-requests/mine").get_json()["request"] is None


def test_mine_returns_my_own_open_request(client):
    created = client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]
    mine = client.get("/api/pickup-requests/mine").get_json()["request"]
    assert mine["id"] == created["id"]
    assert mine["status"] == "open"


def test_mine_does_not_see_another_riders_request(app):
    rider_a = app.test_client()
    rider_b = app.test_client()
    rider_a.post("/api/pickup-requests", json={"stop_id": "reid-library"})

    assert rider_b.get("/api/pickup-requests/mine").get_json()["request"] is None


# ---- S15: POST /api/pickup-requests/<id>/cancel ----


def test_cancel_own_open_request(client):
    created = client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]

    response = client.post(f"/api/pickup-requests/{created['id']}/cancel")
    assert response.status_code == 200
    body = response.get_json()["request"]
    assert body["status"] == "cancelled"
    assert body["cleared_at"] is not None

    assert client.get("/api/pickup-requests/mine").get_json()["request"]["status"] == "cancelled"


def test_cancel_unknown_id_is_404(client):
    response = client.post("/api/pickup-requests/does-not-exist/cancel")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "unknown_request"


def test_cancel_someone_elses_request_is_403(app):
    rider_a = app.test_client()
    rider_b = app.test_client()
    created = rider_a.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]

    response = rider_b.post(f"/api/pickup-requests/{created['id']}/cancel")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "not_your_request"


def test_cancel_needs_no_login(client):
    """
    No auth header, no admin session: just the rider_token cookie. S08.5-style
    guarantee extended to S15's rider-facing endpoints.
    """
    created = client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]
    response = client.post(f"/api/pickup-requests/{created['id']}/cancel")
    assert response.status_code == 200


def test_cancelling_an_already_collected_request_is_409(client):
    created = client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]
    client.post("/api/stops/reid-library/collect", json={"vehicle_id": "1", "route_id": "campus-loop"})

    response = client.post(f"/api/pickup-requests/{created['id']}/cancel")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "request_not_open"


def test_cancelling_frees_the_stop_for_a_new_request(client):
    """
    Cancelling closes the request, so it is no longer "open" and the
    no-duplicate rule (S08.3) does not block a fresh one at the same stop.
    """
    created = client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]
    client.post(f"/api/pickup-requests/{created['id']}/cancel")

    second = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    assert second.status_code == 201
    assert second.get_json()["request"]["id"] != created["id"]


# ---- S08.5: a new stop appearing in the list ----


def test_new_stop_can_be_requested_with_no_code_change(config_dir):
    raw = json.loads((config_dir / "stops.json").read_text(encoding="utf-8"))
    raw["stops"].append(stop("new-stop", name="New Stop"))
    (config_dir / "stops.json").write_text(json.dumps(raw), encoding="utf-8")

    client = create_app(config_dir).test_client()
    response = client.post("/api/pickup-requests", json={"stop_id": "new-stop"})
    assert response.status_code == 201
    assert response.get_json()["request"]["stop_id"] == "new-stop"
