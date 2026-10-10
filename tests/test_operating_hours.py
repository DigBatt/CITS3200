"""
Shuttle operating hours (S15 follow-up): backend.operating_hours.OperatingHours,
the gate on POST /api/pickup-requests, and GET /api/pickup-requests/hours.

The HTTP tests below each use an explicitly all-open or all-closed config
(never the sample Mon-Fri 08:00-17:00 straight from config/app.yaml), so they
pass no matter what day or time it is when the suite actually runs.
"""

from __future__ import annotations
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml

from backend.app import create_app
from backend.config import ConfigError, DEFAULT_CONFIG_DIR
from backend.operating_hours import DAYS, OperatingHours, OperatingHoursError

PERTH = "Australia/Perth"
ALL_DAY = {day: ["00:00", "23:59"] for day in DAYS}
ALL_CLOSED = {day: None for day in DAYS}


# ---- OperatingHours: pure logic, explicit instants, no real clock ----


def test_no_block_at_all_turns_the_feature_off():
    hours = OperatingHours.from_config_block(None)
    assert hours.configured is False
    # Saturday at 2am Perth time -- would be closed under any normal config.
    assert hours.covers(datetime(2026, 10, 10, 2, tzinfo=ZoneInfo(PERTH)), PERTH) is True


def test_an_empty_block_also_turns_the_feature_off():
    assert OperatingHours.from_config_block({}).configured is False


def test_a_day_explicitly_closed_is_still_a_configured_feature():
    hours = OperatingHours.from_config_block({"monday": None})
    assert hours.configured is True
    assert hours.window_for("monday") is None
    assert hours.covers(datetime(2026, 10, 12, 9, tzinfo=ZoneInfo(PERTH)), PERTH) is False


def test_covers_is_true_inside_the_window_and_false_outside_it():
    hours = OperatingHours.from_config_block({"monday": ["08:00", "17:00"]})
    # 2026-10-12 is a Monday.
    before = datetime(2026, 10, 12, 7, 59, tzinfo=ZoneInfo(PERTH))
    opening = datetime(2026, 10, 12, 8, 0, tzinfo=ZoneInfo(PERTH))
    inside = datetime(2026, 10, 12, 12, 0, tzinfo=ZoneInfo(PERTH))
    closing = datetime(2026, 10, 12, 17, 0, tzinfo=ZoneInfo(PERTH))

    assert hours.covers(before, PERTH) is False
    assert hours.covers(opening, PERTH) is True
    assert hours.covers(inside, PERTH) is True
    assert hours.covers(closing, PERTH) is False  # half open: closing time itself is out


def test_a_day_with_no_window_is_closed_even_when_others_are_open():
    hours = OperatingHours.from_config_block({"monday": ["08:00", "17:00"]})
    # 2026-10-13 is the Tuesday after that Monday; nothing configured for it.
    assert hours.covers(datetime(2026, 10, 13, 12, tzinfo=ZoneInfo(PERTH)), PERTH) is False


def test_a_naive_moment_is_read_as_utc():
    hours = OperatingHours.from_config_block({"monday": ["08:00", "17:00"]})
    # Midday UTC on that Monday is 8pm Perth (UTC+8) -- after close.
    assert hours.covers(datetime(2026, 10, 12, 12, 0), PERTH) is False
    # 1am UTC is 9am Perth -- inside the window.
    assert hours.covers(datetime(2026, 10, 12, 1, 0), PERTH) is True


def test_covers_is_true_when_the_timezone_is_not_set():
    hours = OperatingHours.from_config_block({"monday": ["08:00", "17:00"]})
    assert hours.covers(datetime(2026, 10, 12, 12, tzinfo=timezone.utc), "") is True
    assert hours.covers(datetime(2026, 10, 12, 12, tzinfo=timezone.utc), None) is True


def test_to_dict_lists_every_day_monday_first():
    hours = OperatingHours.from_config_block({"wednesday": ["08:00", "17:00"]})
    assert list(hours.to_dict().keys()) == list(DAYS)
    assert hours.to_dict()["wednesday"] == ["08:00", "17:00"]
    assert hours.to_dict()["monday"] is None


@pytest.mark.parametrize(
    "block",
    [
        {"someday": ["08:00", "17:00"]},
        {"monday": ["not-a-time", "17:00"]},
        {"monday": ["17:00", "08:00"]},  # closes before it opens
        {"monday": ["08:00", "08:00"]},  # closes exactly when it opens
        {"monday": ["08:00"]},  # not a pair
    ],
)
def test_a_malformed_block_is_rejected(block):
    with pytest.raises(OperatingHoursError):
        OperatingHours.from_config_block(block)


# ---- The endpoints, over HTTP ----


def stop(stop_id, latitude=-31.98, longitude=115.82):
    return {"id": stop_id, "name": stop_id.title(), "latitude": latitude, "longitude": longitude}


NETWORK = {
    "stops": [stop("reid-library")],
    "routes": [{"id": "campus-loop", "name": "Campus loop", "stops": ["reid-library"]}],
}


def build_app(tmp_path, operating_hours):
    """
    An app whose `pickup_requests.operating_hours` is set to exactly
    `operating_hours`, or left out of app.yaml entirely when it is the
    string `"absent"` -- every other setting is the real sample config.
    """
    shutil.copy(DEFAULT_CONFIG_DIR / "vehicles.yaml", tmp_path / "vehicles.yaml")
    (tmp_path / "stops.yaml").write_text(yaml.safe_dump(NETWORK, sort_keys=False), encoding="utf-8")

    app_config = yaml.safe_load((DEFAULT_CONFIG_DIR / "app.yaml").read_text(encoding="utf-8"))
    if operating_hours == "absent":
        app_config.get("pickup_requests", {}).pop("operating_hours", None)
    else:
        app_config.setdefault("pickup_requests", {})["operating_hours"] = operating_hours
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")

    return create_app(tmp_path)


def test_a_request_is_accepted_when_open_all_day(tmp_path):
    client = build_app(tmp_path, ALL_DAY).test_client()
    response = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    assert response.status_code == 201


def test_a_request_is_refused_when_closed_all_week(tmp_path):
    client = build_app(tmp_path, ALL_CLOSED).test_client()
    response = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "outside_operating_hours"


def test_no_block_configured_accepts_a_request_regardless(tmp_path):
    client = build_app(tmp_path, "absent").test_client()
    response = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    assert response.status_code == 201


def test_an_unknown_stop_is_400_even_when_closed(tmp_path):
    """
    The stop is checked first: a typo in the stop id should not be masked by
    "closed", which would be a more confusing message for a mistake that has
    nothing to do with the time of day.
    """
    client = build_app(tmp_path, ALL_CLOSED).test_client()
    response = client.post("/api/pickup-requests", json={"stop_id": "nope"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "unknown_stop"


def test_a_malformed_config_block_fails_at_startup(tmp_path):
    with pytest.raises(ConfigError):
        build_app(tmp_path, {"someday": ["08:00", "17:00"]})


def test_hours_endpoint_when_the_feature_is_off(tmp_path):
    body = build_app(tmp_path, "absent").test_client().get("/api/pickup-requests/hours").get_json()
    assert body["configured"] is False
    assert body["open_now"] is True
    assert body["hours"] == {day: None for day in DAYS}


def test_hours_endpoint_when_open_all_day(tmp_path):
    body = build_app(tmp_path, ALL_DAY).test_client().get("/api/pickup-requests/hours").get_json()
    assert body["configured"] is True
    assert body["open_now"] is True
    assert body["timezone"] == "Australia/Perth"
    assert body["today"] in DAYS
    assert body["today_hours"] == ["00:00", "23:59"]
    assert body["hours"][body["today"]] == ["00:00", "23:59"]


def test_hours_endpoint_when_closed_all_week(tmp_path):
    body = build_app(tmp_path, ALL_CLOSED).test_client().get("/api/pickup-requests/hours").get_json()
    assert body["configured"] is True
    assert body["open_now"] is False
    assert body["today_hours"] is None
    assert all(value is None for value in body["hours"].values())
