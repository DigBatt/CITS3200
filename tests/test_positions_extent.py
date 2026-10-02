"""
/api/positions/extent: the first and last position in a period, against the
committed sample data (4 Sep 2025, vehicles 1 and 2 only).
"""

from __future__ import annotations

import pytest

from backend.app import create_app

SAMPLE_DAY = {"from": "2025-09-04", "to": "2025-09-04T23:59:59+08:00"}


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_extent_matches_the_positions_it_summarises(client):
    extent = client.get("/api/positions/extent", query_string=SAMPLE_DAY).get_json()
    tracks = client.get("/api/positions", query_string=SAMPLE_DAY).get_json()["vehicles"]

    stamps = [p["timestamp"] for vehicle in tracks for p in vehicle["positions"]]
    assert stamps, "the sample data should have positions on this day"
    assert extent["first"] == min(stamps)
    assert extent["last"] == max(stamps)

    for summary, track in zip(extent["vehicles"], tracks):
        assert summary["vehicle_id"] == track["vehicle_id"]
        assert summary["count"] == track["count"]
        assert summary["first"] == (track["positions"][0]["timestamp"] if track["positions"] else None)
        assert summary["last"] == (track["positions"][-1]["timestamp"] if track["positions"] else None)


def test_extent_is_null_when_the_period_holds_nothing(client):
    body = client.get("/api/positions/extent", query_string={"from": "2020-01-01", "to": "2020-01-02"}).get_json()
    assert body["first"] is None and body["last"] is None
    assert all(vehicle["count"] == 0 and vehicle["first"] is None for vehicle in body["vehicles"])


def test_extent_follows_the_vehicle_selection(client):
    body = client.get("/api/positions/extent", query_string={**SAMPLE_DAY, "vehicles": "3"}).get_json()
    assert [vehicle["vehicle_id"] for vehicle in body["vehicles"]] == ["3"]
    assert body["first"] is None


@pytest.mark.parametrize(
    "query, code",
    [
        ({"from": "not a date"}, "bad_timestamp"),
        ({"from": "2025-09-05", "to": "2025-09-04"}, "bad_range"),
        ({**SAMPLE_DAY, "vehicles": "99"}, "unknown_vehicle"),
    ],
)
def test_extent_rejects_what_positions_rejects(client, query, code):
    response = client.get("/api/positions/extent", query_string=query)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code
