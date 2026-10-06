"""
The traffic light beside "Last seen": backend.freshness.freshness and the
`freshness` field of /api/vehicles.
"""

from __future__ import annotations
import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from backend.api.params import PERTH_TZ
from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.freshness import freshness
from backend.models import Position
from tests.admin_support import write_admin_secrets


def perth(day, hour=12, minute=0):
    """A Perth wall clock time in October 2026."""
    return datetime(2026, 10, day, hour, minute, tzinfo=PERTH_TZ)


# October 2026: the 2nd and 9th are Fridays, the 5th and 12th Mondays.
FRIDAY, SATURDAY, SUNDAY, MONDAY, TUESDAY, WEDNESDAY, THURSDAY = 2, 3, 4, 5, 6, 7, 8


def light(last_seen, now, green_within_weekdays=1, red_after_days=10):
    return freshness(last_seen, now, green_within_weekdays, red_after_days)


def test_the_calendar_above_is_right():
    assert perth(FRIDAY).strftime("%A") == "Friday"
    assert perth(MONDAY).strftime("%A") == "Monday"


def test_never_seen_has_no_light():
    assert light(None, perth(MONDAY)) is None


def test_seen_today_is_green():
    assert light(perth(WEDNESDAY, 8), perth(WEDNESDAY, 9)) == "green"


def test_seen_yesterday_is_green_from_the_start_of_that_day():
    assert light(perth(TUESDAY, 0, 1), perth(WEDNESDAY, 23)) == "green"


def test_seen_the_day_before_yesterday_on_a_weekday_is_yellow():
    assert light(perth(MONDAY, 23, 59), perth(WEDNESDAY, 0, 1)) == "yellow"


@pytest.mark.parametrize("today", [SATURDAY + 7, SUNDAY + 7, MONDAY + 7], ids=["saturday", "sunday", "monday"])
def test_seen_friday_is_still_green_over_the_weekend(today):
    assert light(perth(FRIDAY + 7, 16), perth(today, 9)) == "green"


def test_seen_thursday_is_yellow_on_monday():
    assert light(perth(THURSDAY, 16), perth(MONDAY + 7, 9)) == "yellow"


def test_more_weekdays_widens_green():
    assert light(perth(THURSDAY, 16), perth(MONDAY + 7, 9), green_within_weekdays=2) == "green"


def test_red_only_after_more_than_the_configured_days():
    now = perth(16, 9)
    assert light(now - timedelta(days=10), now) == "yellow"
    assert light(now - timedelta(days=11), now) == "red"
    assert light(now - timedelta(days=3), now, red_after_days=2) == "red"


def test_days_are_perth_days_not_utc_days():
    # Tuesday 06:00 in Perth is still Monday in UTC.
    seen = perth(TUESDAY, 6).astimezone(timezone.utc)
    assert seen.date().day == MONDAY
    assert light(seen, perth(WEDNESDAY, 9).astimezone(timezone.utc)) == "green"


# ---- /api/vehicles ----


class LatestOnly:
    """A repository holding only each vehicle's latest position."""

    def __init__(self, latest):
        self.latest = latest

    def get_latest_positions(self):
        return self.latest


@pytest.fixture
def config_dir(tmp_path):
    for name in ("app.yaml", "vehicles.yaml", "stops.json"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    write_admin_secrets(tmp_path)
    return tmp_path


def get_vehicles(config_dir, latest):
    app = create_app(config_dir)
    app.config["REPOSITORY"] = LatestOnly(latest)
    return app.test_client().get("/api/vehicles")


def test_api_reports_each_vehicles_light_and_the_rule(config_dir):
    now = datetime.now(timezone.utc)
    latest = {
        "1": Position(vehicle_id="1", timestamp=now - timedelta(minutes=1)),
        "2": Position(vehicle_id="2", timestamp=now - timedelta(days=30)),
    }
    response = get_vehicles(config_dir, latest)
    assert response.status_code == 200
    body = response.get_json()

    assert body["freshness_rule"] == {"green_within_weekdays": 1, "red_after_days": 10}
    lights = {vehicle["id"]: vehicle["freshness"] for vehicle in body["vehicles"]}
    assert lights["1"] == "green"
    assert lights["2"] == "red"
    assert lights["3"] is None  # no telemetry at all


def test_api_refuses_without_the_freshness_settings(config_dir):
    app_yaml = config_dir / "app.yaml"
    settings = yaml.safe_load(app_yaml.read_text(encoding="utf-8"))
    del settings["liveness"]["red_after_days"]
    app_yaml.write_text(yaml.safe_dump(settings), encoding="utf-8")

    response = get_vehicles(config_dir, {})
    assert response.status_code == 500
    error = response.get_json()["error"]
    assert error["code"] == "data_unavailable"
    assert "red_after_days" in error["message"]
