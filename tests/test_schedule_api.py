"""
/api/schedule: reading the roster, replacing it, and what an empty one does
to /api/metrics.
"""

from __future__ import annotations
import shutil
from pathlib import Path

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR


@pytest.fixture
def client(tmp_path):
    # A copy of the real config, since a write here rewrites app.yaml.
    config_dir = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config_dir)

    app = create_app(config_dir=config_dir)
    app.config.update(TESTING=True, DOWNTIME_STORE=app.config["DOWNTIME_STORE"])
    with app.test_client() as test_client:
        test_client.config_dir = config_dir
        yield test_client


def test_get_returns_the_whole_week(client):
    body = client.get("/api/schedule").get_json()
    assert body["days"][0] == "monday"
    assert set(body["schedule"]) == set(body["days"])
    assert body["timezone"] == "Australia/Perth"
    assert body["configured"] is True


def test_get_is_public(client):
    # No session, no header, no cookie. S13 must keep it that way.
    assert client.get("/api/schedule").status_code == 200


def test_put_replaces_the_roster(client):
    response = client.put("/api/schedule", json={"tuesday": [["06:00", "09:00"]]})
    assert response.status_code == 200

    body = response.get_json()
    assert body["schedule"]["tuesday"] == [
        {"start": "06:00", "end": "09:00", "vehicles": None, "starts_on": None, "ends_on": None}
    ]
    assert body["schedule"]["monday"] == []
    assert client.get("/api/schedule").get_json()["schedule"]["tuesday"][0]["start"] == "06:00"


def test_put_accepts_a_wrapped_body(client):
    response = client.put("/api/schedule", json={"schedule": {"friday": [["08:00", "15:00"]]}})
    assert response.status_code == 200
    assert response.get_json()["schedule"]["friday"] == [
        {"start": "08:00", "end": "15:00", "vehicles": None, "starts_on": None, "ends_on": None}
    ]


def test_put_writes_through_to_app_yaml(client):
    client.put("/api/schedule", json={"monday": [["08:00", "12:00"], ["13:00", "17:00"]]})
    document = yaml.safe_load((client.config_dir / "app.yaml").read_text())
    assert document["utilisation"]["service_hours"]["monday"] == [
        {"hours": ["08:00", "12:00"]},
        {"hours": ["13:00", "17:00"]},
    ]


def test_put_keeps_the_rest_of_the_config(client):
    before = yaml.safe_load((client.config_dir / "app.yaml").read_text())
    client.put("/api/schedule", json={"monday": [["09:00", "10:00"]]})
    after = yaml.safe_load((client.config_dir / "app.yaml").read_text())

    assert after["logger"] == before["logger"]
    assert after["map"] == before["map"]
    assert after["utilisation"]["stationary_speed_mps"] == before["utilisation"]["stationary_speed_mps"]


def test_an_empty_roster_is_accepted_and_reported(client):
    body = client.put("/api/schedule", json={}).get_json()
    assert body["configured"] is False
    assert all(periods == [] for periods in body["schedule"].values())


def test_a_bad_day_is_rejected(client):
    response = client.put("/api/schedule", json={"funday": [["08:00", "17:00"]]})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_schedule"


def test_a_backwards_period_is_rejected(client):
    response = client.put("/api/schedule", json={"monday": [["17:00", "08:00"]]})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_schedule"


def test_overlapping_periods_are_rejected(client):
    response = client.put("/api/schedule", json={"monday": [["08:00", "12:00"], ["11:00", "17:00"]]})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_schedule"


def test_a_rejected_write_leaves_the_file_alone(client):
    before = (client.config_dir / "app.yaml").read_text()
    client.put("/api/schedule", json={"monday": [["17:00", "08:00"]]})
    assert (client.config_dir / "app.yaml").read_text() == before


# ---- AC2: the figures move with the config, no code change ----


def test_metrics_follow_a_schedule_change(client):
    query = "?vehicles=1&from=2026-09-21&to=2026-09-21"

    client.put("/api/schedule", json={"monday": [["08:00", "17:00"]]})
    nine_hours = client.get("/api/metrics" + query).get_json()["vehicles"][0]["buckets"]["scheduled_seconds"]

    client.put("/api/schedule", json={"monday": [["08:00", "12:00"]]})
    four_hours = client.get("/api/metrics" + query).get_json()["vehicles"][0]["buckets"]["scheduled_seconds"]

    assert nine_hours == 9 * 3600
    assert four_hours == 4 * 3600


# ---- AC3: no schedule is non-scheduled, with a note, not an error ----


def test_metrics_report_an_empty_schedule_as_unscheduled(client):
    client.put("/api/schedule", json={})

    response = client.get("/api/metrics?vehicles=1&from=2026-09-21&to=2026-09-21")
    assert response.status_code == 200

    figures = response.get_json()["vehicles"][0]
    assert figures["buckets"]["scheduled_seconds"] == 0
    assert figures["buckets"]["unscheduled_seconds"] == figures["buckets"]["calendar_seconds"]
    assert "no service schedule" in figures["notes"]["scheduled_seconds"].lower()


def test_a_rostered_schedule_carries_no_note(client):
    client.put("/api/schedule", json={"monday": [["08:00", "17:00"]]})
    figures = client.get("/api/metrics?vehicles=1&from=2026-09-21&to=2026-09-21").get_json()["vehicles"][0]
    assert figures["notes"] == {}


# ---- Per vehicle rosters ----


def test_the_fleet_is_offered_for_the_editor(client):
    body = client.get("/api/schedule").get_json()
    assert [vehicle["id"] for vehicle in body["vehicles"]] == ["1", "2", "3", "4"]


def test_a_period_can_name_vehicles(client):
    response = client.put("/api/schedule", json={"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1"]}]})
    assert response.status_code == 200
    assert response.get_json()["schedule"]["monday"][0]["vehicles"] == ["1"]


def test_a_roster_naming_an_unknown_vehicle_is_rejected(client):
    response = client.put("/api/schedule", json={"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["99"]}]})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_vehicle"


def test_metrics_are_scheduled_per_vehicle(client):
    client.put("/api/schedule", json={"monday": [
        {"start": "08:00", "end": "17:00", "vehicles": ["1"]},
        {"start": "10:00", "end": "14:00", "vehicles": ["2"]},
    ]})

    def scheduled(vehicle):
        body = client.get(f"/api/metrics?vehicles={vehicle}&from=2026-09-21&to=2026-09-21").get_json()
        return body["vehicles"][0]["buckets"]["scheduled_seconds"]

    assert scheduled("1") == 9 * 3600
    assert scheduled("2") == 4 * 3600
    assert scheduled("3") == 0


def test_an_unrostered_vehicle_is_noted_by_name(client):
    client.put("/api/schedule", json={"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1"]}]})
    figures = client.get("/api/metrics?vehicles=3&from=2026-09-21&to=2026-09-21").get_json()["vehicles"][0]
    assert "for this vehicle" in figures["notes"]["scheduled_seconds"]


# ---- Booked changes ----


def test_a_period_can_carry_dates(client):
    response = client.put("/api/schedule", json={"monday": [
        {"start": "08:00", "end": "17:00", "ends_on": "2026-10-01"},
        {"start": "06:00", "end": "20:00", "starts_on": "2026-10-01"},
    ]})
    assert response.status_code == 200

    monday = response.get_json()["schedule"]["monday"]
    assert [p["ends_on"] for p in monday] == [None, "2026-10-01"]
    assert [p["starts_on"] for p in monday] == ["2026-10-01", None]


def test_metrics_follow_a_booked_change(client):
    # Old hours run out on 28 Sept; the longer day takes over from then.
    client.put("/api/schedule", json={"monday": [
        {"start": "08:00", "end": "17:00", "ends_on": "2026-09-28"},
        {"start": "06:00", "end": "20:00", "starts_on": "2026-09-28"},
    ]})

    def scheduled(day):
        body = client.get(f"/api/metrics?vehicles=1&from={day}&to={day}").get_json()
        return body["vehicles"][0]["buckets"]["scheduled_seconds"]

    assert scheduled("2026-09-21") == 9 * 3600    # Monday before the change
    assert scheduled("2026-09-28") == 14 * 3600   # Monday on and after it


def test_a_period_that_has_not_started_contributes_nothing(client):
    client.put("/api/schedule", json={"monday": [{"start": "08:00", "end": "17:00", "starts_on": "2099-01-01"}]})
    body = client.get("/api/metrics?vehicles=1&from=2026-09-21&to=2026-09-21").get_json()
    assert body["vehicles"][0]["buckets"]["scheduled_seconds"] == 0


def test_a_reversed_date_window_is_rejected(client):
    response = client.put("/api/schedule", json={"monday": [
        {"start": "08:00", "end": "17:00", "starts_on": "2026-10-05", "ends_on": "2026-10-01"},
    ]})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_schedule"
