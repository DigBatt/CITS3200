"""
/api/downtime: the round trip through Flask, and the documented error shapes.
"""

from __future__ import annotations
from dataclasses import replace

import pytest

from backend.app import create_app
from backend.config import load_config

START = "2026-09-17T01:00:00Z"
END = "2026-09-17T03:00:00Z"


@pytest.fixture
def client(tmp_path):
    config = replace(load_config(), downtime_database=tmp_path / "downtime.sqlite3")
    app = create_app(config)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        test_client.vehicle_id = config.vehicles[0].id
        yield test_client


def post(client, **overrides):
    body = {"vehicle_id": client.vehicle_id, "start": START, "end": END, "reason": "Brake fault"}
    return client.post("/api/downtime", json={**body, **overrides})


def test_empty_log_is_not_an_error(client):
    response = client.get("/api/downtime")
    assert response.status_code == 200
    assert response.get_json() == {"from": None, "to": None, "records": []}


def test_a_stored_record_survives_a_new_request(client):
    created = post(client)
    assert created.status_code == 201

    records = client.get("/api/downtime").get_json()["records"]
    assert len(records) == 1
    assert records[0]["id"] == created.get_json()["record"]["id"]
    assert records[0]["reason"] == "Brake fault"
    assert records[0]["start"] == "2026-09-17T01:00:00.000000Z"


def test_records_persist_across_app_instances(client, tmp_path):
    post(client)
    config = replace(load_config(), downtime_database=tmp_path / "downtime.sqlite3")
    with create_app(config).test_client() as second:
        assert len(second.get("/api/downtime").get_json()["records"]) == 1


def test_list_is_ascending_and_filterable(client):
    post(client, start="2026-09-20T01:00:00Z", end="2026-09-20T02:00:00Z")
    post(client)
    starts = [r["start"] for r in client.get("/api/downtime").get_json()["records"]]
    assert starts == sorted(starts)

    scoped = client.get("/api/downtime?from=2026-09-20&to=2026-09-20").get_json()
    assert len(scoped["records"]) == 1
    assert scoped["from"] is not None


def test_overlap_is_reported_but_still_stored(client):
    assert post(client).get_json()["overlaps"] == []

    second = post(client, start="2026-09-17T02:00:00Z", end="2026-09-17T04:00:00Z")
    assert second.status_code == 201
    assert len(second.get_json()["overlaps"]) == 1
    assert len(client.get("/api/downtime").get_json()["records"]) == 2


def test_touching_periods_do_not_overlap(client):
    post(client)
    second = post(client, start=END, end="2026-09-17T05:00:00Z")
    assert second.get_json()["overlaps"] == []


def test_patch_changes_only_what_it_sends(client):
    created = post(client).get_json()["record"]
    updated = client.patch(f"/api/downtime/{created['id']}", json={"reason": "Parts on order"})

    assert updated.status_code == 200
    record = updated.get_json()["record"]
    assert record["reason"] == "Parts on order"
    assert record["start"] == created["start"]
    assert record["created_at"] == created["created_at"]


def test_patch_does_not_clash_with_itself(client):
    created = post(client).get_json()["record"]
    updated = client.patch(f"/api/downtime/{created['id']}", json={"reason": "Same period"})
    assert updated.get_json()["overlaps"] == []


def test_delete_removes_the_record(client):
    created = post(client).get_json()["record"]
    assert client.delete(f"/api/downtime/{created['id']}").status_code == 204
    assert client.get("/api/downtime").get_json()["records"] == []


def test_delete_twice_is_not_found(client):
    created = post(client).get_json()["record"]
    client.delete(f"/api/downtime/{created['id']}")

    repeated = client.delete(f"/api/downtime/{created['id']}")
    assert repeated.status_code == 404
    assert repeated.get_json()["error"]["code"] == "not_found"


def test_patch_of_a_missing_record_is_not_found(client):
    response = client.patch("/api/downtime/nope", json={"reason": "x"})
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_end_before_start_is_bad_range(client):
    response = post(client, start=END, end=START)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_range"


def test_empty_reason_is_rejected(client):
    response = post(client, reason="   ")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_record"


def test_unknown_vehicle_is_rejected(client):
    response = post(client, vehicle_id="does-not-exist")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_vehicle"


def test_missing_fields_are_named(client):
    response = client.post("/api/downtime", json={"vehicle_id": client.vehicle_id})
    assert response.status_code == 400
    message = response.get_json()["error"]["message"]
    assert "start" in message and "end" in message and "reason" in message


def test_unparseable_time_is_bad_timestamp(client):
    response = post(client, start="not a time")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_timestamp"


def test_a_body_that_is_not_an_object_is_rejected(client):
    response = client.post("/api/downtime", json=["nope"])
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_request"


def test_unknown_vehicle_in_a_query_is_rejected(client):
    response = client.get("/api/downtime?vehicles=nope")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_vehicle"


def test_reversed_window_is_bad_range(client):
    response = client.get("/api/downtime?from=2026-09-20&to=2026-09-17")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_range"
