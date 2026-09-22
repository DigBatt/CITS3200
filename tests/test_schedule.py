"""
Schedule: reading the roster, answering about an instant, and rewriting the
service_hours block of app.yaml without disturbing the rest of the file.
"""

from __future__ import annotations
from datetime import datetime, time, timezone
from pathlib import Path

import pytest
import yaml

from backend.schedule import DAYS, Schedule, ScheduleError, ServicePeriod, load_schedule, save_schedule

PERTH = "Australia/Perth"

APP_YAML = """\
# Application configuration.
data:
  directory: data/sample

display:
  timezone: Australia/Perth

utilisation:
  # a comment that must survive
  stationary_speed_mps: 0.2

  service_hours:
    monday:
      - ["08:00", "17:00"]

logger:
  poll_interval_seconds: 30
"""


@pytest.fixture
def app_yaml(tmp_path) -> Path:
    path = tmp_path / "app.yaml"
    path.write_text(APP_YAML, encoding="utf-8")
    return path


def hours(schedule: Schedule, day: str, vehicle_id=None) -> list[tuple[time, time]]:
    """
    One day's periods as plain (open, close) pairs, for readable asserts.
    """
    return [(period.start, period.end) for period in schedule.for_day(day, vehicle_id)]


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """
    A Perth wall clock instant in the week of 2026-09-21, a Monday.
    """
    from zoneinfo import ZoneInfo

    return datetime(2026, 9, 21 + day, hour, minute, tzinfo=ZoneInfo(PERTH))


# ---- AC1: the system can answer whether an instant is scheduled ----


def test_covers_an_instant_inside_service():
    schedule = Schedule.from_dict({"monday": [["08:00", "17:00"]]})
    assert schedule.covers(at(0, 9), PERTH) is True


def test_does_not_cover_outside_service():
    schedule = Schedule.from_dict({"monday": [["08:00", "17:00"]]})
    assert schedule.covers(at(0, 7, 59), PERTH) is False
    assert schedule.covers(at(0, 18), PERTH) is False


def test_periods_are_half_open_at_the_close():
    schedule = Schedule.from_dict({"monday": [["08:00", "17:00"]]})
    assert schedule.covers(at(0, 8), PERTH) is True
    assert schedule.covers(at(0, 17), PERTH) is False


def test_a_split_shift_leaves_a_gap():
    schedule = Schedule.from_dict({"monday": [["08:00", "12:00"], ["13:00", "17:00"]]})
    assert schedule.covers(at(0, 11), PERTH) is True
    assert schedule.covers(at(0, 12, 30), PERTH) is False
    assert schedule.covers(at(0, 14), PERTH) is True


def test_a_day_with_no_service_is_never_covered():
    schedule = Schedule.from_dict({"monday": [["08:00", "17:00"]]})
    assert schedule.covers(at(6, 9), PERTH) is False


def test_covers_reads_the_instant_in_the_roster_timezone():
    schedule = Schedule.from_dict({"monday": [["08:00", "17:00"]]})
    # 01:00 UTC Monday is 09:00 in Perth, inside service.
    assert schedule.covers(datetime(2026, 9, 21, 1, tzinfo=timezone.utc), PERTH) is True


def test_a_naive_instant_is_read_as_utc():
    schedule = Schedule.from_dict({"monday": [["08:00", "17:00"]]})
    assert schedule.covers(datetime(2026, 9, 21, 1), PERTH) is True


# ---- AC3: no schedule is non-scheduled, not an error ----


def test_an_empty_schedule_is_valid_and_covers_nothing():
    schedule = Schedule.from_dict({})
    assert schedule.is_empty is True
    assert schedule.covers(at(0, 9), PERTH) is False


def test_a_missing_block_reads_as_empty_rather_than_failing():
    assert Schedule.from_config_block(None).is_empty is True


def test_days_present_but_empty_are_empty():
    assert Schedule.from_dict({day: [] for day in DAYS}).is_empty is True


# ---- Parsing ----


def test_every_day_appears_in_to_dict():
    assert set(Schedule.from_dict({"monday": [["08:00", "17:00"]]}).to_dict()) == set(DAYS)


def test_periods_come_back_sorted():
    schedule = Schedule.from_dict({"monday": [["13:00", "17:00"], ["08:00", "12:00"]]})
    assert [(row["start"], row["end"]) for row in schedule.to_dict()["monday"]] == [
        ("08:00", "12:00"),
        ("13:00", "17:00"),
    ]


def test_legacy_weekday_key_expands_across_the_week():
    schedule = Schedule.from_config_block({"weekday": ["08:00", "17:00"]})
    assert hours(schedule, "monday") == [(time(8), time(17))]
    assert hours(schedule, "friday") == [(time(8), time(17))]
    assert hours(schedule, "saturday") == []


def test_a_bare_pair_under_a_day_is_one_period():
    assert hours(Schedule.from_config_block({"monday": ["08:00", "17:00"]}), "monday") == [(time(8), time(17))]


def test_an_unknown_day_is_rejected():
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"funday": [["08:00", "17:00"]]})


def test_a_malformed_time_is_rejected():
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"monday": [["8 in the morning", "17:00"]]})


def test_a_period_must_end_after_it_starts():
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"monday": [["17:00", "08:00"]]})
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"monday": [["08:00", "08:00"]]})


def test_overlapping_periods_are_rejected():
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"monday": [["08:00", "12:00"], ["11:00", "17:00"]]})


def test_touching_periods_are_allowed():
    schedule = Schedule.from_dict({"monday": [["08:00", "12:00"], ["12:00", "17:00"]]})
    assert len(schedule.for_day("monday")) == 2


def test_a_payload_that_is_not_an_object_is_rejected():
    with pytest.raises(ScheduleError):
        Schedule.from_dict([["08:00", "17:00"]])


# ---- AC2: updated in configuration, no code change ----


def test_load_reads_the_block(app_yaml):
    assert hours(load_schedule(app_yaml), "monday") == [(time(8), time(17))]


def test_save_then_load_round_trips(app_yaml):
    schedule = Schedule.from_dict({"tuesday": [["06:30", "09:45"]], "sunday": [["10:00", "14:00"]]})
    save_schedule(app_yaml, schedule)
    assert load_schedule(app_yaml) == schedule


def test_save_leaves_the_rest_of_the_file_alone(app_yaml):
    save_schedule(app_yaml, Schedule.from_dict({"friday": [["08:00", "15:00"]]}))
    text = app_yaml.read_text()

    assert "# Application configuration." in text
    assert "# a comment that must survive" in text
    assert "stationary_speed_mps: 0.2" in text
    assert "poll_interval_seconds: 30" in text

    document = yaml.safe_load(text)
    assert document["data"]["directory"] == "data/sample"
    assert document["logger"]["poll_interval_seconds"] == 30


def test_save_writes_multiple_periods_for_one_day(app_yaml):
    schedule = Schedule.from_dict({"monday": [["08:00", "12:00"], ["13:00", "17:00"]]})
    save_schedule(app_yaml, schedule)
    assert hours(load_schedule(app_yaml), "monday") == [(time(8), time(12)), (time(13), time(17))]


def test_saving_an_empty_schedule_clears_the_block(app_yaml):
    save_schedule(app_yaml, Schedule())
    assert load_schedule(app_yaml).is_empty is True
    assert yaml.safe_load(app_yaml.read_text())["logger"]["poll_interval_seconds"] == 30


def test_save_creates_the_block_when_it_is_absent(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text("utilisation:\n  stationary_speed_mps: 0.2\n\nlogger:\n  poll_interval_seconds: 30\n")
    save_schedule(path, Schedule.from_dict({"monday": [["08:00", "17:00"]]}))

    assert hours(load_schedule(path), "monday") == [(time(8), time(17))]
    assert yaml.safe_load(path.read_text())["logger"]["poll_interval_seconds"] == 30


def test_save_without_a_utilisation_section_is_refused(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text("data:\n  directory: data/sample\n")
    with pytest.raises(ScheduleError):
        save_schedule(path, Schedule.from_dict({"monday": [["08:00", "17:00"]]}))


def test_repeated_saves_do_not_drift(app_yaml):
    schedule = Schedule.from_dict({"monday": [["08:00", "17:00"]], "saturday": [["09:00", "13:00"]]})
    save_schedule(app_yaml, schedule)
    first = app_yaml.read_text()
    save_schedule(app_yaml, schedule)
    assert app_yaml.read_text() == first


def test_the_projects_own_config_still_reads():
    schedule = load_schedule(Path("config/app.yaml"))
    assert hours(schedule, "monday"), "config/app.yaml should roster a Monday"


# ---- Per vehicle rosters ----


def test_a_period_with_no_vehicles_is_fleet_wide():
    period = Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00"}]}).for_day("monday")[0]
    assert period.is_fleet_wide
    assert period.applies_to("anything")


def test_a_period_applies_only_to_the_vehicles_it_names():
    schedule = Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1", "2"]}]})
    assert hours(schedule, "monday", "1") == [(time(8), time(17))]
    assert hours(schedule, "monday", "3") == []


def test_a_fleet_wide_period_reaches_every_vehicle():
    schedule = Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00"}]})
    assert hours(schedule, "monday", "9") == [(time(8), time(17))]


def test_covers_is_answered_per_vehicle():
    schedule = Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1"]}]})
    assert schedule.covers(at(0, 9), PERTH, "1") is True
    assert schedule.covers(at(0, 9), PERTH, "2") is False
    assert schedule.covers(at(0, 9), PERTH) is True  # anyone at all


def test_periods_for_different_vehicles_may_overlap():
    schedule = Schedule.from_dict({"monday": [
        {"start": "08:00", "end": "17:00", "vehicles": ["1"]},
        {"start": "09:00", "end": "13:00", "vehicles": ["2"]},
    ]})
    assert len(schedule.for_day("monday")) == 2


def test_periods_for_the_same_vehicle_may_not_overlap():
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"monday": [
            {"start": "08:00", "end": "12:00", "vehicles": ["1"]},
            {"start": "11:00", "end": "17:00", "vehicles": ["1", "2"]},
        ]})


def test_a_fleet_wide_period_may_not_overlap_a_named_one():
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"monday": [
            {"start": "08:00", "end": "12:00"},
            {"start": "11:00", "end": "17:00", "vehicles": ["1"]},
        ]})


def test_is_empty_for_is_answered_per_vehicle():
    schedule = Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1"]}]})
    assert schedule.is_empty is False
    assert schedule.is_empty_for("1") is False
    assert schedule.is_empty_for("2") is True


def test_naming_every_vehicle_is_kept_as_given():
    schedule = Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1", "2"]}]})
    assert schedule.to_dict()["monday"][0]["vehicles"] == ["1", "2"]


def test_an_empty_vehicle_list_means_the_whole_fleet():
    period = Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00", "vehicles": []}]}).for_day("monday")[0]
    assert period.is_fleet_wide


def test_vehicle_ids_lists_only_those_singled_out():
    schedule = Schedule.from_dict({"monday": [
        {"start": "08:00", "end": "12:00"},
        {"start": "13:00", "end": "17:00", "vehicles": ["2", "1"]},
    ]})
    assert schedule.vehicle_ids() == ["1", "2"]


def test_a_bad_vehicle_list_is_rejected():
    with pytest.raises(ScheduleError):
        Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00", "vehicles": 7}]})


def test_vehicles_survive_the_yaml_round_trip(app_yaml):
    schedule = Schedule.from_dict({"monday": [
        {"start": "08:00", "end": "12:00", "vehicles": ["1"]},
        {"start": "09:00", "end": "13:00", "vehicles": ["2"]},
        {"start": "18:00", "end": "20:00"},
    ]})
    save_schedule(app_yaml, schedule)
    assert load_schedule(app_yaml) == schedule


def test_a_fleet_wide_period_writes_no_vehicles_key(app_yaml):
    save_schedule(app_yaml, Schedule.from_dict({"monday": [{"start": "08:00", "end": "17:00"}]}))
    block = app_yaml.read_text().split("service_hours:")[1]
    assert "vehicles:" not in block.split("logger:")[0]
