"""
backend.ingest.rev_php: REV tracking responses onto the schema.
"""

from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from math import degrees, inf, nan
from pathlib import Path

import pytest

from backend.config import load_config
from backend.ingest.rev_php import PayloadError, Settings, parse
from backend.metrics.tum import EARTH_RADIUS_M
from backend.models import Position

FIXTURES = Path(__file__).parent / "fixtures" / "rev_php"
NOW = datetime(2026, 9, 17, 1, 0, 0, tzinfo=timezone.utc)
SETTINGS = Settings(
    latitude_bounds=(-36.0, -13.0),
    longitude_bounds=(112.0, 130.0),
    max_gap_seconds=30.0,
)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def payload(**fields) -> dict:
    base = {"lat": -31.98, "lon": 115.82, "heading": 45.0, "battery_percentage": 70, "timestamp": 1789000000}
    return {**base, **fields}


def run(body, previous=None, settings=SETTINGS) -> Position:
    return parse("1", body, previous, settings, NOW)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# Real responses, captured 2026-09-17.

def test_bus1_response():
    assert parse("1", fixture("bus1"), None, SETTINGS, NOW) == Position(
        vehicle_id="1",
        timestamp=utc(2025, 5, 15, 9, 14, 25),
        latitude=-31.984505,
        longitude=115.820154,
        heading_deg=pytest.approx(344.222512),
        gps_status=0,
    )


def test_bus2_response():
    assert parse("2", fixture("bus2"), None, SETTINGS, NOW) == Position(
        vehicle_id="2",
        timestamp=utc(2026, 2, 6, 3, 46, 39),
        latitude=-31.594105,
        longitude=115.671642,
        heading_deg=pytest.approx(161.625348),
        gps_status=0,
        battery_percent=76.0,
    )


@pytest.mark.parametrize(
    "name, timestamp, latitude, longitude",
    [
        ("bus3", utc(2026, 8, 17, 4, 16, 14), -31.981334, 115.815951),
        ("bus4", utc(2026, 8, 28, 12, 8, 18), -31.98078, 115.816247),
    ],
)
def test_bus3_and_bus4_responses_have_unset_heading_and_battery(name, timestamp, latitude, longitude):
    assert parse(name[-1], fixture(name), None, SETTINGS, NOW) == Position(
        vehicle_id=name[-1],
        timestamp=timestamp,
        latitude=latitude,
        longitude=longitude,
        gps_status=0,
    )


# Heading

@pytest.mark.parametrize(
    "raw, bearing",
    [
        (0, None),
        (0.0, None),
        (90, 0.0),
        (-90, 180.0),
        (180, 270.0),
        (-270, 0.0),
        (269.5, 180.5),
        (None, None),
        ("90", None),
        (nan, None),
    ],
)
def test_heading_east_anticlockwise_to_compass(raw, bearing):
    assert run(payload(heading=raw)).heading_deg == (None if bearing is None else pytest.approx(bearing))


# Coordinates

@pytest.mark.parametrize(
    "lat, lon",
    [
        (None, 115.82),
        (-31.98, None),
        ("-31.98", 115.82),
        (True, 115.82),
        (nan, 115.82),
        (-31.98, inf),
        (0, 0),
        (-53.393514, 52.815138),  # a real junk fix from bus 2's history
        (-36.0001, 115.82),
        (-31.98, 130.0001),
    ],
)
def test_implausible_coordinates_are_no_fix(lat, lon):
    position = run(payload(lat=lat, lon=lon))
    assert (position.latitude, position.longitude, position.gps_status) == (None, None, -1)
    assert position.speed_mps is None


def test_missing_coordinate_keys_are_no_fix():
    body = payload()
    del body["lat"], body["lon"]
    assert run(body).gps_status == -1


@pytest.mark.parametrize("lat, lon", [(-36.0, 112.0), (-13.0, 130.0), (-31.594105, 115.671642)])
def test_coordinates_inside_bounds_are_a_fix(lat, lon):
    position = run(payload(lat=lat, lon=lon))
    assert (position.latitude, position.longitude, position.gps_status) == (lat, lon, 0)


def test_no_bounds_admits_anywhere_but_null_island():
    open_settings = Settings()
    assert run(payload(lat=-53.39, lon=52.81), settings=open_settings).gps_status == 0
    assert run(payload(lat=0, lon=0), settings=open_settings).gps_status == -1


# Battery

@pytest.mark.parametrize("raw, stored", [(0, None), (-5, None), (150, None), (None, None), ("76", None), (76, 76.0), (100, 100.0), (0.5, 0.5)])
def test_battery(raw, stored):
    assert run(payload(battery_percentage=raw)).battery_percent == stored


def test_altitude_is_always_null():
    assert run(payload(altitude=12.0)).altitude_m is None


# Timestamp

@pytest.mark.parametrize("raw", [None, "1789000000", 0, -1, True, nan, 1e20])
def test_unusable_timestamp_raises(raw):
    with pytest.raises(PayloadError):
        run(payload(timestamp=raw))


def test_missing_timestamp_raises():
    body = payload()
    del body["timestamp"]
    with pytest.raises(PayloadError):
        run(body)


def test_future_timestamp_raises():
    with pytest.raises(PayloadError, match="future"):
        run(payload(timestamp=int((NOW + timedelta(days=1)).timestamp())))


def test_timestamp_within_clock_skew_is_accepted():
    ahead = NOW + timedelta(minutes=4)
    assert run(payload(timestamp=int(ahead.timestamp()))).timestamp == ahead


def test_fractional_timestamp_truncates_to_the_second():
    assert run(payload(timestamp=1789000000.9)).timestamp == utc(2026, 9, 10, 0, 26, 40)


def test_old_timestamp_is_accepted():
    assert run(payload(timestamp=1747300465)).timestamp == utc(2025, 5, 15, 9, 14, 25)


@pytest.mark.parametrize("body", [[], "not json", None, 42])
def test_non_object_raises(body):
    with pytest.raises(PayloadError):
        run(body)


# Speed

def fix_at(timestamp: datetime, latitude=-31.98, longitude=115.82, **fields) -> Position:
    return Position("1", timestamp, latitude, longitude, gps_status=0, **fields)


def body_at(timestamp: datetime, latitude=-31.98, longitude=115.82) -> dict:
    return payload(timestamp=int(timestamp.timestamp()), lat=latitude, lon=longitude)


T = utc(2026, 9, 17, 0, 0, 0)
FIFTY_METRES_NORTH = -31.98 + degrees(50 / EARTH_RADIUS_M)


def test_speed_from_previous_fix():
    later = T + timedelta(seconds=5)
    assert run(body_at(later, FIFTY_METRES_NORTH), previous=fix_at(T)).speed_mps == pytest.approx(10.0)


def test_stationary_speed_is_zero():
    assert run(body_at(T + timedelta(seconds=5)), previous=fix_at(T)).speed_mps == 0.0


@pytest.mark.parametrize(
    "previous",
    [
        None,
        fix_at(T, latitude=None, longitude=None),
        fix_at(T + timedelta(seconds=5)),  # same second as the new row
        fix_at(T + timedelta(seconds=6)),  # newer than the new row
        fix_at(T - timedelta(seconds=26)),  # 31 s gap
    ],
)
def test_speed_is_unknown_without_a_recent_earlier_fix(previous):
    assert run(body_at(T + timedelta(seconds=5), FIFTY_METRES_NORTH), previous=previous).speed_mps is None


def test_speed_at_exactly_the_max_gap():
    later = T + timedelta(seconds=30)
    assert run(body_at(later, FIFTY_METRES_NORTH), previous=fix_at(T)).speed_mps == pytest.approx(50 / 30)


def test_speed_without_a_max_gap_has_no_upper_limit():
    later = T + timedelta(hours=1)
    position = run(body_at(later, FIFTY_METRES_NORTH), previous=fix_at(T), settings=Settings())
    assert position.speed_mps == pytest.approx(50 / 3600)


# Config

def test_settings_from_config():
    assert Settings.from_config(load_config()) == SETTINGS
