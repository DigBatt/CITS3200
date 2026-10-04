"""
Clearing a pickup (S10): PickupRequestStore.collect and .expire, the
POST /api/stops/<id>/collect endpoint, and expiry through the read endpoints.
The page's "Picked up" button is tested in the browser in test_operator_view.py.
"""

from __future__ import annotations
import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from tests.admin_support import sign_in, write_admin_secrets
from backend.models import PickupRequest
from backend.pickup_requests import PickupRequestStore


def stop(stop_id, latitude=-31.98, longitude=115.82):
    return {"id": stop_id, "name": stop_id.replace("-", " ").title(), "latitude": latitude, "longitude": longitude}


# 'shared' is on both routes, so clearing it must clear riders for either.
NETWORK = {
    "stops": [stop("north-end"), stop("shared"), stop("south-end"), stop("off-route")],
    "routes": [
        {"id": "loop", "name": "Campus loop", "loop": True, "stops": ["north-end", "shared", "south-end"]},
        {"id": "spur", "name": "Spur", "stops": ["shared", "off-route"]},
    ],
}

EXPIRE_AFTER_MINUTES = 10
NOW = datetime(2025, 9, 4, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def config_dir(tmp_path):
    """
    The real config with a known expiry age and a small stop network.
    """
    shutil.copy(DEFAULT_CONFIG_DIR / "vehicles.yaml", tmp_path / "vehicles.yaml")
    app_config = yaml.safe_load((DEFAULT_CONFIG_DIR / "app.yaml").read_text(encoding="utf-8"))
    app_config["pickup_requests"] = {"expire_after_seconds": EXPIRE_AFTER_MINUTES * 60}
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")
    (tmp_path / "stops.yaml").write_text(yaml.safe_dump(NETWORK, sort_keys=False), encoding="utf-8")
    write_admin_secrets(tmp_path)
    return tmp_path


@pytest.fixture
def app(config_dir):
    return create_app(config_dir)


@pytest.fixture
def client(app):
    # Signed in: the operator and list endpoints are admin-only (S13).
    return sign_in(app.test_client())


def open_request(app, stop_id, rider, minutes_ago):
    """
    A request opened `minutes_ago` before the real now, straight into the store.
    """
    created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return app.config["PICKUP_REQUEST_STORE"].create(stop_id, rider, created)[0]


def waiting(client, route_id):
    body = client.get(f"/api/routes/{route_id}/waiting").get_json()
    return {s["id"]: s["waiting"] for s in body["stops"]}


def statuses(client, status):
    return client.get(f"/api/pickup-requests?status={status}").get_json()["requests"]


# ---- The store ----


def test_collect_closes_only_open_requests_at_that_stop():
    store = PickupRequestStore()
    a, _ = store.create("shared", "rider-a", NOW - timedelta(minutes=3))
    b, _ = store.create("shared", "rider-b", NOW - timedelta(minutes=1))
    other, _ = store.create("north-end", "rider-a", NOW - timedelta(minutes=2))

    closed = store.collect("shared", "1", "loop", NOW)

    assert [r.id for r in closed] == [a.id, b.id]
    assert all(
        r.status == PickupRequest.COLLECTED and r.cleared_at == NOW and r.vehicle_id == "1" and r.route_id == "loop"
        for r in closed
    )
    assert [r.id for r in store.list(status=PickupRequest.OPEN)] == [other.id]


def test_collect_with_nobody_waiting_closes_nothing():
    store = PickupRequestStore()
    assert store.collect("shared", "1", "loop", NOW) == []


def test_collect_does_not_touch_already_closed_requests():
    store = PickupRequestStore()
    store.create("shared", "rider-a", NOW - timedelta(minutes=3))
    store.collect("shared", "1", "loop", NOW - timedelta(minutes=1))

    assert store.collect("shared", "1", "loop", NOW) == []
    (kept,) = store.list()
    assert kept.cleared_at == NOW - timedelta(minutes=1)


def test_expire_closes_only_requests_older_than_max_age():
    store = PickupRequestStore()
    old, _ = store.create("shared", "rider-a", NOW - timedelta(minutes=11))
    fresh, _ = store.create("shared", "rider-b", NOW - timedelta(minutes=9))

    expired = store.expire(NOW, timedelta(minutes=10))

    assert [r.id for r in expired] == [old.id]
    assert expired[0].status == PickupRequest.EXPIRED
    assert expired[0].cleared_at == NOW
    assert [r.id for r in store.list(status=PickupRequest.OPEN)] == [fresh.id]


def test_expire_leaves_collected_requests_collected():
    store = PickupRequestStore()
    store.create("shared", "rider-a", NOW - timedelta(minutes=30))
    store.collect("shared", "1", "loop", NOW - timedelta(minutes=20))

    assert store.expire(NOW, timedelta(minutes=10)) == []
    assert store.list()[0].status == PickupRequest.COLLECTED


# ---- Criterion 1: marking a pickup collected clears the stop ----


def collect(client, stop_id, vehicle_id="1", route_id="loop"):
    return client.post(f"/api/stops/{stop_id}/collect", json={"vehicle_id": vehicle_id, "route_id": route_id})


def test_collect_clears_the_stop_on_the_next_refresh(app, client):
    open_request(app, "shared", "rider-a", minutes_ago=3)
    open_request(app, "shared", "rider-b", minutes_ago=1)
    open_request(app, "south-end", "rider-c", minutes_ago=2)

    response = collect(client, "shared")

    assert response.status_code == 200
    collected = response.get_json()["collected"]
    assert len(collected) == 2
    assert all(r["status"] == "collected" and r["cleared_at"] for r in collected)
    assert waiting(client, "loop") == {"north-end": 0, "shared": 0, "south-end": 1}


def test_collect_stamps_the_vehicle_and_route_onto_closed_requests(app, client):
    open_request(app, "shared", "rider-a", minutes_ago=3)

    response = collect(client, "shared", vehicle_id="2", route_id="spur")

    (closed,) = response.get_json()["collected"]
    assert closed["vehicle_id"] == "2"
    assert closed["route_id"] == "spur"


def test_collect_at_a_shared_stop_clears_it_on_every_route(app, client):
    open_request(app, "shared", "rider-a", minutes_ago=3)

    collect(client, "shared")

    assert waiting(client, "loop")["shared"] == 0
    assert waiting(client, "spur")["shared"] == 0


def test_collect_with_nobody_waiting_is_ok_and_empty(client):
    response = collect(client, "shared")
    assert response.status_code == 200
    assert response.get_json() == {"collected": []}


def test_collect_at_unknown_stop_is_404(client):
    # Checked ahead of the body, so this is 404 even with none sent at all.
    response = client.post("/api/stops/nowhere/collect")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "unknown_stop"


# ---- S15 follow-up: both vehicle and route are required to collect ----


@pytest.mark.parametrize("body", [{}, {"vehicle_id": "1"}, {"route_id": "loop"}, {"vehicle_id": "", "route_id": "loop"}])
def test_collect_without_both_fields_is_400(client, body):
    response = client.post("/api/stops/shared/collect", json=body)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "missing_field"


def test_collect_with_unknown_vehicle_is_400(client):
    response = collect(client, "shared", vehicle_id="no-such-vehicle")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_vehicle"


def test_collect_with_unknown_route_is_400(client):
    response = collect(client, "shared", route_id="no-such-route")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_route"


def test_rider_can_ask_again_after_being_collected(client):
    first = client.post("/api/pickup-requests", json={"stop_id": "shared"})
    collect(client, "shared")
    again = client.post("/api/pickup-requests", json={"stop_id": "shared"})

    assert again.status_code == 201
    assert again.get_json()["request"]["id"] != first.get_json()["request"]["id"]


# ---- Criterion 2: a request open beyond the configured age expires ----


def test_old_request_is_not_shown_to_the_operator(app, client):
    open_request(app, "shared", "rider-a", minutes_ago=EXPIRE_AFTER_MINUTES + 1)
    open_request(app, "south-end", "rider-b", minutes_ago=EXPIRE_AFTER_MINUTES - 1)

    assert waiting(client, "loop") == {"north-end": 0, "shared": 0, "south-end": 1}
    (expired,) = statuses(client, "expired")
    assert expired["stop_id"] == "shared"
    assert expired["cleared_at"]


def test_rider_with_a_stale_request_gets_a_new_one(app, client):
    client.post("/api/pickup-requests", json={"stop_id": "shared"})
    # Age the rider's request past the limit, as if they had waited that long.
    store = app.config["PICKUP_REQUEST_STORE"]
    store.expire(datetime.now(timezone.utc) + timedelta(minutes=EXPIRE_AFTER_MINUTES + 1),
                 timedelta(minutes=EXPIRE_AFTER_MINUTES))

    again = client.post("/api/pickup-requests", json={"stop_id": "shared"})

    assert again.status_code == 201
    assert waiting(client, "loop")["shared"] == 1


def test_no_expiry_configured_means_requests_stay_open(config_dir):
    app_config = yaml.safe_load((config_dir / "app.yaml").read_text(encoding="utf-8"))
    del app_config["pickup_requests"]
    (config_dir / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")
    app = create_app(config_dir)
    open_request(app, "shared", "rider-a", minutes_ago=24 * 60)

    assert waiting(sign_in(app.test_client()), "loop")["shared"] == 1


# ---- Criterion 3: cleared requests stay in the record ----


def test_cleared_requests_are_kept_with_the_time_they_were_cleared(app, client):
    open_request(app, "shared", "rider-a", minutes_ago=3)
    open_request(app, "north-end", "rider-b", minutes_ago=EXPIRE_AFTER_MINUTES + 5)
    collect(client, "shared")

    (collected,) = statuses(client, "collected")
    (expired,) = statuses(client, "expired")
    assert collected["stop_id"] == "shared" and collected["cleared_at"]
    assert expired["stop_id"] == "north-end" and expired["cleared_at"]
    assert len(client.get("/api/pickup-requests").get_json()["requests"]) == 2
