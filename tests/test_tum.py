"""
The GMG time usage model: backend.metrics.tum.summarise, and the downtime it
takes from the admin page's records (S19).
"""

from __future__ import annotations
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.metrics.tum import BLOCKED_KPIS, DOWNTIME_KPIS, Settings, summarise
from backend.models import Position
from backend.schedule import Schedule
from tests.admin_support import sign_in, write_admin_secrets

T0 = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)  # Thursday 09:00 in Perth
HOUR = 3600
CLOSING = 8 * HOUR  # 17:00 in Perth, when the roster ends
DEPOT = (-31.98133, 115.81597)
AWAY = (-31.98000, 115.82000)  # a few hundred metres from the depot

SETTINGS = Settings(
    stationary_speed_mps=0.2,
    max_gap_seconds=30,
    min_standby_seconds=120,
    depot_centre=DEPOT,
    depot_radius_m=40,
    schedule=Schedule.from_config_block({"weekday": ["08:00", "17:00"]}),
    timezone="Australia/Perth",
)



def at(seconds):
    return T0 + timedelta(seconds=seconds)


def sample(seconds, speed, where):
    return Position("1", at(seconds), latitude=where[0], longitude=where[1], speed_mps=speed, gps_status=1)


@pytest.fixture
def track():
    """
    One hour inside service hours, sampled every 10 s: moving away from the
    depot for the first half hour, then parked at the depot for the second.
    """
    return [sample(s, 5.0, AWAY) for s in range(0, 1800, 10)] + [
        sample(s, 0.0, DEPOT) for s in range(1800, HOUR, 10)
    ]


# ---- S19 step 1: summarise() takes downtime, and None changes nothing ----


def test_figures_without_downtime(track):
    result = summarise("1", track, at(0), at(HOUR), SETTINGS)
    assert result.buckets["calendar_seconds"] == HOUR
    assert result.buckets["working_seconds"] == 1800
    assert result.buckets["standby_seconds"] == 1800
    assert result.buckets["operating_delay_seconds"] == 0
    assert result.buckets["not_reporting_seconds"] == 0
    assert result.buckets["scheduled_seconds"] == HOUR
    assert result.kpis["asset_utilisation"] == 0.5
    assert result.kpis["operating_efficiency"] == 1.0
    assert result.kpis["effective_utilisation"] == 0.5


def test_omitted_downtime_is_the_same_as_none(track):
    omitted = summarise("1", track, at(0), at(HOUR), SETTINGS)
    explicit = summarise("1", track, at(0), at(HOUR), SETTINGS, downtime=None)
    assert omitted.to_dict() == explicit.to_dict()


def test_no_downtime_log_keeps_the_downtime_kpis_blocked(track):
    result = summarise("1", track, at(0), at(HOUR), SETTINGS, downtime=None)
    for name in DOWNTIME_KPIS:
        assert result.kpis[name] is None
        assert result.unavailable[name] == BLOCKED_KPIS[name]
    assert result.buckets["downtime_seconds"] is None
    assert result.buckets["available_seconds"] is None


# ---- S19 step 2: only downtime inside the vehicle's roster counts ----


def downtime_seconds(track, downtime, start=0, end=11 * HOUR, settings=SETTINGS, vehicle_id="1"):
    """
    The downtime bucket over 09:00-20:00 Perth, by default.
    """
    result = summarise(vehicle_id, track, at(start), at(end), settings, downtime=downtime)
    return result.buckets["downtime_seconds"]


def test_downtime_inside_the_roster_is_counted(track):
    assert downtime_seconds(track, [(at(2 * HOUR), at(3 * HOUR))]) == HOUR


def test_downtime_outside_the_roster_is_not_counted(track):
    assert downtime_seconds(track, [(at(CLOSING + HOUR), at(CLOSING + 2 * HOUR))]) == 0


def test_downtime_across_closing_time_counts_only_the_part_before_it(track):
    assert downtime_seconds(track, [(at(CLOSING - 1800), at(CLOSING + 1800))]) == 1800


def test_several_downtime_periods_are_added_up(track):
    periods = [(at(1 * HOUR), at(2 * HOUR)), (at(4 * HOUR), at(4 * HOUR + 1800))]
    assert downtime_seconds(track, periods) == HOUR + 1800


def test_downtime_on_an_unrostered_weekend_is_not_counted():
    saturday = 2 * 24 * HOUR
    assert downtime_seconds([], [(at(saturday), at(saturday + HOUR))], saturday, saturday + HOUR) == 0


def test_downtime_is_counted_against_that_vehicles_own_roster(track):
    only_bus_2 = replace(SETTINGS, schedule=Schedule.from_dict(
        {"thursday": [{"start": "08:00", "end": "17:00", "vehicles": ["2"]}]}
    ))
    downtime = [(at(2 * HOUR), at(3 * HOUR))]
    assert downtime_seconds(track, downtime, settings=only_bus_2, vehicle_id="2") == HOUR
    assert downtime_seconds(track, downtime, settings=only_bus_2, vehicle_id="1") == 0


def test_an_empty_downtime_log_counts_zero(track):
    result = summarise("1", track, at(0), at(HOUR), SETTINGS, downtime=[])
    assert result.buckets["downtime_seconds"] == 0
    assert "downtime_seconds" not in result.unavailable


def test_downtime_with_nothing_rostered_is_zero_with_a_note(track):
    no_roster = replace(SETTINGS, schedule=Schedule())
    result = summarise("1", track, at(0), at(HOUR), no_roster, downtime=[(at(0), at(1800))])
    assert result.buckets["downtime_seconds"] == 0
    assert "outside service hours left out" in result.notes["downtime_seconds"]


def test_downtime_without_a_timezone_is_unknown(track):
    no_timezone = replace(SETTINGS, timezone=None)
    result = summarise("1", track, at(0), at(HOUR), no_timezone, downtime=[(at(0), at(1800))])
    assert result.buckets["downtime_seconds"] is None
    assert "timezone" in result.unavailable["downtime_seconds"]


# ---- S19 step 3: downtime replaces the telemetry buckets it covers ----
# summarise() runs check() itself, so each of these also proves the buckets
# and downtime still add up to calendar time.


def buckets(track, downtime, end=HOUR):
    return summarise("1", track, at(0), at(end), SETTINGS, downtime=downtime).buckets


def test_downtime_while_parked_comes_out_of_standby(track):
    result = buckets(track, [(at(2700), at(HOUR))])
    assert result["downtime_seconds"] == 900
    assert result["standby_seconds"] == 900
    assert result["working_seconds"] == 1800


def test_downtime_while_moving_comes_out_of_working(track):
    result = buckets(track, [(at(0), at(900))])
    assert result["working_seconds"] == 900
    assert result["operating_seconds"] == 900
    assert result["scheduled_working_seconds"] == 900
    assert result["standby_seconds"] == 1800


def test_downtime_across_two_states_comes_out_of_both(track):
    result = buckets(track, [(at(1500), at(2100))])
    assert result["working_seconds"] == 1500
    assert result["standby_seconds"] == 1500
    assert result["downtime_seconds"] == 600


def test_downtime_while_not_reporting_comes_out_of_not_reporting(track):
    result = buckets(track, [(at(HOUR), at(2 * HOUR))], end=2 * HOUR)
    before = buckets(track, None, end=2 * HOUR)
    assert result["not_reporting_seconds"] == before["not_reporting_seconds"] - HOUR
    assert result["downtime_seconds"] == HOUR


def test_downtime_outside_the_roster_leaves_the_buckets_alone(track):
    evening = [(at(CLOSING + HOUR), at(CLOSING + 2 * HOUR))]
    with_downtime = buckets(track, evening, end=11 * HOUR)
    without_downtime = buckets(track, None, end=11 * HOUR)
    for name in ("working_seconds", "standby_seconds", "operating_delay_seconds", "not_reporting_seconds"):
        assert with_downtime[name] == without_downtime[name]


def test_an_empty_downtime_log_leaves_the_buckets_alone(track):
    empty = buckets(track, [])
    none = buckets(track, None)
    assert {**empty, "downtime_seconds": None, "available_seconds": None} == none


# ---- S19 step 4: a downtime log unblocks the availability KPIs ----
# Over the one-hour track: 30 min working, then 30 min parked at the depot,
# all of it inside the roster, so scheduled time is the full hour.


def figures(track, downtime, start=0, end=HOUR, settings=SETTINGS):
    return summarise("1", track, at(start), at(end), settings, downtime=downtime)


def unexplained(result):
    """Every bucket or KPI that is None without a reason."""
    return [
        key
        for group in (result.buckets, result.kpis)
        for key, value in group.items()
        if value is None and not result.unavailable.get(key)
    ]


def test_the_kpis_with_downtime_while_parked(track):
    # 15 min down at the end: AT = 60 - 15 = 45 min, OT = 30 min.
    result = figures(track, [(at(2700), at(HOUR))])
    assert result.buckets["available_seconds"] == 2700
    assert result.buckets["scheduled_operating_seconds"] == 1800
    assert result.kpis["uptime"] == pytest.approx(2700 / 3600)
    assert result.kpis["mechanical_availability"] == pytest.approx(1800 / (1800 + 900))
    assert result.kpis["physical_availability"] == pytest.approx(2700 / 3600)
    assert result.kpis["use_of_availability"] == pytest.approx(1800 / 2700)
    for name in DOWNTIME_KPIS + ("downtime_seconds", "available_seconds"):
        assert name not in result.unavailable


def test_the_kpis_with_an_empty_downtime_log(track):
    result = figures(track, [])
    assert result.kpis["uptime"] == 1.0
    assert result.kpis["mechanical_availability"] == 1.0
    assert result.kpis["physical_availability"] == 1.0
    assert result.kpis["use_of_availability"] == 0.5


def test_down_for_the_whole_roster_leaves_use_of_availability_unavailable(track):
    result = figures(track, [(at(0), at(HOUR))])
    assert result.kpis["uptime"] == 0
    assert result.kpis["physical_availability"] == 0
    assert result.kpis["mechanical_availability"] == 0
    assert result.kpis["use_of_availability"] is None
    assert result.unavailable["use_of_availability"] == "no available time in this window"


def test_operating_time_outside_the_roster_does_not_count_towards_availability():
    # Driving 17:00-18:00, after the roster ends: scheduled operating time is 0.
    driving = [sample(s, 5.0, AWAY) for s in range(CLOSING, CLOSING + HOUR, 10)]
    result = figures(driving, [], end=CLOSING + HOUR)
    assert result.buckets["operating_seconds"] == HOUR
    assert result.buckets["scheduled_operating_seconds"] == 0
    assert result.kpis["use_of_availability"] == 0


def test_a_day_with_no_service_leaves_the_ratios_unavailable_not_zero():
    saturday = 2 * 24 * HOUR
    result = figures([], [], saturday, saturday + HOUR)
    assert result.kpis["uptime"] == 0
    for name in ("mechanical_availability", "physical_availability", "use_of_availability"):
        assert result.kpis[name] is None
        assert result.unavailable[name]


def test_nothing_rostered_gives_a_noted_zero_uptime(track):
    result = figures(track, [], settings=replace(SETTINGS, schedule=Schedule()))
    assert result.kpis["uptime"] == 0
    assert result.notes["uptime"]
    assert result.notes["available_seconds"]


def test_without_a_timezone_the_downtime_kpis_say_why(track):
    result = figures(track, [], settings=replace(SETTINGS, timezone=None))
    for name in DOWNTIME_KPIS:
        assert result.kpis[name] is None
        assert "timezone" in result.unavailable[name]


@pytest.mark.parametrize("downtime", [None, [], [(at(2700), at(HOUR))], [(at(0), at(HOUR))]])
def test_every_missing_figure_has_a_reason(track, downtime):
    assert unexplained(figures(track, downtime)) == []


# ---- S19 step 5: say how much downtime was recorded and how it was treated ----


def test_no_downtime_log_has_no_downtime_block(track):
    assert figures(track, None).to_dict()["downtime"] is None


def test_an_empty_log_records_nothing(track):
    block = figures(track, []).downtime
    assert block["recorded_seconds"] == 0
    assert block["counted_seconds"] == 0
    assert block["replaced_seconds"] == {}
    assert "downtime_seconds" not in figures(track, []).notes


def test_downtime_inside_and_outside_the_roster_is_split(track):
    # 16:00-18:00 Perth: one hour before closing counts, one after is left out.
    result = figures(track, [(at(CLOSING - HOUR), at(CLOSING + HOUR))], end=11 * HOUR)
    assert result.downtime["recorded_seconds"] == 2 * HOUR
    assert result.downtime["counted_seconds"] == HOUR
    assert result.downtime["outside_roster_seconds"] == HOUR


def test_the_block_says_what_the_downtime_replaced(track):
    result = figures(track, [(at(1500), at(2100))])
    assert result.downtime["replaced_seconds"] == {"working_seconds": 300, "standby_seconds": 300}


def test_the_summary_is_also_a_note_on_the_downtime_figure(track):
    result = figures(track, [(at(CLOSING - HOUR), at(CLOSING + 1800))], end=11 * HOUR)
    assert result.downtime["summary"] == (
        "1 h 30 min of downtime recorded: 1 h in service hours counted as downtime, in place of "
        "1 h not reporting; 30 min outside service hours left out, since the bus was not rostered then."
    )
    assert result.notes["downtime_seconds"] == result.downtime["summary"]


# ---- S19 step 6: /api/metrics applies the admin page's downtime log ----

SAMPLE_DAY = {"from": "2025-09-04", "to": "2025-09-04"}  # a Thursday in the sample data


def make_config(tmp_path, storage=True):
    """
    The real config, with storage in this test's directory or switched off.
    """
    config_dir = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config_dir)
    app_yaml = config_dir / "app.yaml"
    config = yaml.safe_load(app_yaml.read_text(encoding="utf-8"))
    if storage:
        config["storage"] = {"directory": str(tmp_path / "admin")}
    else:
        config.pop("storage", None)
    app_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    write_admin_secrets(config_dir)
    return config_dir


def metrics_by_vehicle(client):
    response = client.get("/api/metrics", query_string=SAMPLE_DAY)
    assert response.status_code == 200
    return {entry["vehicle_id"]: entry for entry in response.get_json()["vehicles"]}


def test_metrics_use_downtime_entered_on_the_admin_page(tmp_path):
    client = sign_in(create_app(make_config(tmp_path)).test_client())
    created = client.post("/api/downtime", json={
        "vehicle_id": "1",
        "start": "2025-09-04T02:00:00Z",  # 10:00-11:00 in Perth, inside the roster
        "end": "2025-09-04T03:00:00Z",
        "reason": "Brake inspection",
    })
    assert created.status_code == 201

    bus_1 = metrics_by_vehicle(client)["1"]
    assert bus_1["buckets"]["downtime_seconds"] == HOUR
    assert bus_1["downtime"]["recorded_seconds"] == HOUR
    assert bus_1["notes"]["downtime_seconds"] == bus_1["downtime"]["summary"]
    for name in DOWNTIME_KPIS:
        assert bus_1["kpis"][name] is not None, name
    assert "Brake inspection" not in str(bus_1)  # only durations leave the admin page


def test_a_bus_with_no_records_has_no_downtime(tmp_path):
    client = create_app(make_config(tmp_path)).test_client()
    for entry in metrics_by_vehicle(client).values():
        assert entry["buckets"]["downtime_seconds"] == 0
        assert entry["kpis"]["uptime"] is not None


def test_without_storage_the_downtime_kpis_stay_unavailable(tmp_path):
    client = create_app(make_config(tmp_path, storage=False)).test_client()
    for entry in metrics_by_vehicle(client).values():
        assert entry["downtime"] is None
        for name in DOWNTIME_KPIS:
            assert entry["kpis"][name] is None
            assert entry["unavailable"][name] == BLOCKED_KPIS[name]
