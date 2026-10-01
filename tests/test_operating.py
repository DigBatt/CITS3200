"""
Operating time in and outside schedule: the splitting itself, and
/api/operating against the sample data and /api/metrics.
"""

from __future__ import annotations
import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.metrics.operating import OperatingInterval, operating_stretches, split_by_schedule
from backend.metrics.tum import Span, State
from backend.models import parse_timestamp

T0 = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc)  # 08:00 Perth, a Monday
SAMPLE_DAY = {"from": "2025-09-04", "to": "2025-09-04"}  # the sample data's Thursday


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def shape(intervals):
    """Intervals as (start hour, end hour, in_schedule), for readable asserts."""
    hours = lambda moment: (moment - T0).total_seconds() / 3600
    return [(hours(i.start), hours(i.end), i.in_schedule) for i in intervals]


# ---- Splitting ----


@pytest.mark.parametrize(
    "stretch, periods, expected",
    [
        ((1, 2), [(0, 9)], [(1, 2, True)]),
        ((10, 11), [(0, 9)], [(10, 11, False)]),
        ((8, 10), [(0, 9)], [(8, 9, True), (9, 10, False)]),
        ((-1, 1), [(0, 9)], [(-1, 0, False), (0, 1, True)]),
        ((2, 7), [(0, 3), (5, 9)], [(2, 3, True), (3, 5, False), (5, 7, True)]),
        ((1, 2), [], [(1, 2, False)]),
    ],
    ids=["inside", "outside", "runs-past-close", "starts-before-open", "across-a-break", "nothing-rostered"],
)
def test_split_by_schedule(stretch, periods, expected):
    stretches = [(at(stretch[0]), at(stretch[1]))]
    roster = [(at(a), at(b)) for a, b in periods]
    assert shape(split_by_schedule(stretches, roster)) == expected


def test_unknown_schedule_marks_nothing_either_way():
    assert split_by_schedule([(at(1), at(2))], None) == [OperatingInterval(at(1), at(2), None)]


def test_working_and_delay_together_are_one_stretch():
    classified = [
        Span(State.NOT_REPORTING, at(0), at(1)),
        Span(State.WORKING, at(1), at(2)),
        Span(State.DELAY, at(2), at(3)),
        Span(State.STANDBY, at(3), at(4)),
        Span(State.WORKING, at(4), at(5)),
    ]
    assert operating_stretches(classified) == [(at(1), at(3)), (at(4), at(5))]


# ---- /api/operating ----


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def seconds(interval):
    return (parse_timestamp(interval["end"]) - parse_timestamp(interval["start"])).total_seconds()


def test_operating_time_matches_the_metrics(client):
    operating = client.get("/api/operating", query_string=SAMPLE_DAY).get_json()["vehicles"]
    metrics = client.get("/api/metrics", query_string=SAMPLE_DAY).get_json()["vehicles"]

    for ours, theirs in zip(operating, metrics):
        assert ours["vehicle_id"] == theirs["vehicle_id"]
        total = sum(seconds(interval) for interval in ours["intervals"])
        assert total == pytest.approx(theirs["buckets"]["operating_seconds"]), ours["vehicle_id"]


def test_sample_day_is_inside_the_weekday_roster(client):
    vehicles = client.get("/api/operating", query_string=SAMPLE_DAY).get_json()["vehicles"]
    intervals = [interval for vehicle in vehicles for interval in vehicle["intervals"]]
    assert intervals, "the sample data should operate on its Thursday"
    assert all(interval["in_schedule"] is True for interval in intervals)


def test_with_nothing_rostered_it_is_all_outside_schedule(tmp_path):
    config_dir = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config_dir)
    app_yaml = config_dir / "app.yaml"
    config = yaml.safe_load(app_yaml.read_text(encoding="utf-8"))
    config["utilisation"]["service_hours"] = {}
    app_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")

    app = create_app(config_dir)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        vehicles = client.get("/api/operating", query_string=SAMPLE_DAY).get_json()["vehicles"]
    intervals = [interval for vehicle in vehicles for interval in vehicle["intervals"]]
    assert intervals and all(interval["in_schedule"] is False for interval in intervals)


def test_follows_the_vehicle_selection(client):
    body = client.get("/api/operating", query_string={**SAMPLE_DAY, "vehicles": "2"}).get_json()
    assert [vehicle["vehicle_id"] for vehicle in body["vehicles"]] == ["2"]


@pytest.mark.parametrize(
    "query, code",
    [
        ({"from": "not a date"}, "bad_timestamp"),
        ({"from": "2025-09-05", "to": "2025-09-04"}, "bad_range"),
        ({**SAMPLE_DAY, "vehicles": "99"}, "unknown_vehicle"),
    ],
)
def test_rejects_what_metrics_rejects(client, query, code):
    response = client.get("/api/operating", query_string=query)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == code
