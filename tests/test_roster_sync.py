"""
Roster sync: reading drives off the calendar.online events, keeping the last
good copy, and adding them to the schedule, the calendar and the figures.

No test touches the network: the calendar's answer is a fixture in the shape
its API sends, and the fetch is swapped for one that returns it.
"""

from __future__ import annotations
import re
import shutil
from datetime import date, datetime, time, timezone

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR, load_config
from backend.ingest.fetch import FetchError
from backend.roster_sync import (
    Drive,
    RosterSync,
    SyncError,
    SyncSettings,
    SyncStore,
    coalesce,
    drive_period,
    events_url,
    fetch_events,
    load_calendar_id,
    merge,
    to_drives,
)
from backend.schedule import Schedule
from tests.admin_support import sign_in, write_admin_secrets

DRIVES = 4921495
EVENTS = 4778786
LEAVE = 4778785
CALENDAR_ID = "abcdef0123456789abcd"

SETTINGS = SyncSettings(
    calendar_id=CALENDAR_ID,
    vehicles=("4",),
    sub_calendars=frozenset({DRIVES}),
    title_pattern=re.compile("nUWAy", re.IGNORECASE),
    timezone="Australia/Perth",
)
FLEET = ("1", "2", "3", "4")


def event(start, end, title="Weekly Drive", who="Alex", sub=DRIVES, whole_day=False, id="1"):
    """
    One event as the calendar's API sends it.
    """
    return {
        "id": id, "start_date": start, "end_date": end, "title": title, "text": "", "who": who,
        "where": "", "subCalendars": [sub], "wholeDay": whole_day, "repeatSeriesId": None,
        "repeatInterval": 0, "imported": False, "hasReminder": False, "hasRegistration": False,
    }


# A Monday to Wednesday of drives, leave, and an unrelated event.
CALENDAR = [
    event("2026-10-05 12:00:00", "2026-10-05 14:00:00", "Weekly Driving", "Alex", id="a"),
    event("2026-10-06 13:00:00", "2026-10-06 15:00:00", "Weekly Drive", "Sam", id="b"),
    event("2026-10-02 00:00:00", "2026-10-12 00:00:00", "Someone Leave", "", LEAVE, True, id="c"),
    event("2026-10-07 09:00:00", "2026-10-07 10:00:00", "Team meeting", "", EVENTS, id="d"),
    event("2026-10-09 10:00:00", "2026-10-09 11:00:00", "nUWAy demo", "Lee, Zheng", EVENTS, id="e"),
]


# ---- Which events are drives ----


def test_timed_events_on_the_drive_sub_calendar_are_drives():
    drives = to_drives(CALENDAR, SETTINGS, FLEET)
    assert [(d.id, d.operator) for d in drives] == [("a", "Alex"), ("b", "Sam"), ("e", "Lee, Zheng")]


def test_whole_day_events_and_unrelated_ones_are_not():
    ids = {d.id for d in to_drives(CALENDAR, SETTINGS, FLEET)}
    assert "c" not in ids and "d" not in ids


def test_a_drive_is_for_the_default_bus_unless_its_title_names_one():
    events = [
        event("2026-10-05 12:00:00", "2026-10-05 14:00:00", "Weekly Drive", id="a"),
        event("2026-10-05 12:00:00", "2026-10-05 14:00:00", "nUWAy 2 test run", id="b"),
        event("2026-10-05 12:00:00", "2026-10-05 14:00:00", "nUWAy 9 test run", id="c"),
    ]
    assert [d.vehicles for d in to_drives(events, SETTINGS, FLEET)] == [("4",), ("2",), ("4",)]


def test_operator_names_are_tidied_and_blank_is_none():
    events = [
        event("2026-10-05 12:00:00", "2026-10-05 14:00:00", who="  Tom   Kitchin ", id="a"),
        event("2026-10-06 12:00:00", "2026-10-06 14:00:00", who="", id="b"),
    ]
    assert [d.operator for d in to_drives(events, SETTINGS, FLEET)] == ["Tom Kitchin", None]


def test_events_that_cannot_be_rostered_are_skipped_not_fatal():
    events = [
        event("2026-10-05 14:00:00", "2026-10-05 12:00:00", id="backwards"),
        event("2026-10-05 22:00:00", "2026-10-06 02:00:00", id="overnight"),
        {"id": "broken", "subCalendars": [DRIVES]},
        "not an event",
        event("2026-10-06 13:00:00", "2026-10-06 15:00:00", id="good"),
    ]
    assert [d.id for d in to_drives(events, SETTINGS, FLEET)] == ["good"]


def test_a_drive_becomes_a_one_day_period_on_its_weekday():
    drive = to_drives(CALENDAR, SETTINGS, FLEET)[1]
    day, period = drive_period(drive)
    assert day == "tuesday"
    assert (period.start, period.end) == (time(13), time(15))
    assert (period.starts_on, period.ends_on) == (date(2026, 10, 6), date(2026, 10, 7))
    assert period.vehicles == frozenset({"4"}) and period.operator == "Sam"


# ---- Merging into the schedule ----


def drive(start, end, operator, id, vehicles=("4",)):
    return Drive(id, datetime.fromisoformat(start), datetime.fromisoformat(end), "Weekly Drive", operator, vehicles)


def test_overlapping_drives_of_one_bus_are_joined_with_both_names():
    joined = coalesce([
        drive("2026-10-07 13:00", "2026-10-07 15:00", "Punit", "a"),
        drive("2026-10-07 14:00", "2026-10-07 16:00", "Yuki", "b"),
    ])
    assert len(joined) == 1
    assert (joined[0].start.hour, joined[0].end.hour, joined[0].operator) == (13, 16, "Punit, Yuki")


def test_drives_that_only_touch_or_are_on_other_buses_stay_apart():
    joined = coalesce([
        drive("2026-10-07 13:00", "2026-10-07 15:00", "A", "a"),
        drive("2026-10-07 15:00", "2026-10-07 16:00", "B", "b"),
        drive("2026-10-07 13:00", "2026-10-07 15:00", "C", "c", vehicles=("2",)),
    ])
    assert len(joined) == 3


def test_drives_are_added_beside_the_hand_kept_roster():
    base = Schedule.from_config_block({"tuesday": [{"hours": ["08:00", "17:00"], "vehicles": ["1"]}]})
    merged = merge(base, to_drives(CALENDAR, SETTINGS, FLEET))
    assert not merged.conflicts
    assert [p.operator for p in merged.schedule.for_day("tuesday", "4")] == ["Sam"]
    assert merged.schedule.for_day("tuesday", "1")[0].operator is None
    assert [p.operator for p in merged.synced["tuesday"]] == ["Sam"]


def test_the_hand_kept_roster_wins_an_overlap():
    base = Schedule.from_config_block({"tuesday": [{"hours": ["08:00", "17:00"]}]})
    merged = merge(base, to_drives(CALENDAR, SETTINGS, FLEET))
    assert [d.operator for d in merged.conflicts] == ["Sam"]
    assert merged.schedule.for_day("tuesday", "4") == base.for_day("tuesday", "4")


def test_a_synced_drive_counts_as_scheduled_on_its_date_only():
    merged = merge(Schedule(), to_drives(CALENDAR, SETTINGS, FLEET))
    tz = "Australia/Perth"
    from zoneinfo import ZoneInfo

    perth = ZoneInfo(tz)
    assert merged.schedule.covers(datetime(2026, 10, 6, 14, tzinfo=perth), tz, "4")
    assert not merged.schedule.covers(datetime(2026, 10, 13, 14, tzinfo=perth), tz, "4")
    assert not merged.schedule.covers(datetime(2026, 10, 6, 14, tzinfo=perth), tz, "1")


# ---- The last good copy ----


NOW = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)


def test_a_sync_replaces_its_window_and_keeps_older_drives(tmp_path):
    store = SyncStore(tmp_path / "roster_sync.json")
    old = drive("2026-08-03 12:00", "2026-08-03 14:00", "Old", "old")
    cancelled = drive("2026-10-05 12:00", "2026-10-05 14:00", "Gone", "gone")
    store.record([old, cancelled], (date(2026, 7, 1), date(2026, 11, 1)), NOW)

    fresh = drive("2026-10-06 13:00", "2026-10-06 15:00", "Sam", "b")
    state = store.record([fresh], (date(2026, 9, 1), date(2026, 12, 1)), NOW)
    assert [d.id for d in state.drives] == ["old", "b"]
    assert store.load().drives == state.drives


def test_a_failed_sync_keeps_the_last_good_drives(tmp_path):
    store = SyncStore(tmp_path / "roster_sync.json")
    store.record([drive("2026-10-06 13:00", "2026-10-06 15:00", "Sam", "b")], (date(2026, 9, 1), date(2026, 12, 1)), NOW)
    state = store.record_error("Could not read the calendar: timed out", NOW)
    assert [d.operator for d in state.drives] == ["Sam"]
    assert state.error and state.synced_at == NOW


def test_an_unreadable_file_reads_as_nothing_synced(tmp_path):
    path = tmp_path / "roster_sync.json"
    path.write_text("{not json")
    assert SyncStore(path).load().drives == []


def test_sync_once_stores_what_the_calendar_says(tmp_path):
    store = SyncStore(tmp_path / "roster_sync.json")
    asked = []

    def fake_fetch(settings, start, end):
        asked.append((start, end))
        return CALENDAR

    state = RosterSync(SETTINGS, store, FLEET, fetch=fake_fetch).sync_once()
    assert [d.operator for d in state.drives] == ["Alex", "Sam", "Lee, Zheng"]
    (start, end), = asked
    assert (end - start).days == SETTINGS.days_back + SETTINGS.days_ahead


def test_sync_once_records_a_failure_without_raising(tmp_path):
    store = SyncStore(tmp_path / "roster_sync.json")

    def failing(settings, start, end):
        raise SyncError("Could not read the calendar: HTTP 503")

    state = RosterSync(SETTINGS, store, FLEET, fetch=failing).sync_once()
    assert state.error == "Could not read the calendar: HTTP 503"


# ---- Fetching ----


def test_the_url_is_the_one_the_calendar_page_loads():
    url = events_url(CALENDAR_ID, "Australia/Perth", date(2026, 9, 28), date(2026, 11, 2))
    assert url.startswith("https://api.calendar.online/event?")
    assert "timeZone=Australia%2FPerth" in url
    assert "startDate=2026-09-28+00%3A00%3A00" in url
    assert f"capabilityId={CALENDAR_ID}" in url


def test_a_fetch_failure_never_reveals_the_calendar_id(monkeypatch):
    def failing(url, user_agent, timeout, max_bytes):
        raise FetchError(f"{url}: HTTP 500")

    monkeypatch.setattr("backend.roster_sync.fetch_json", failing)
    with pytest.raises(SyncError) as caught:
        fetch_events(SETTINGS, date(2026, 10, 1), date(2026, 11, 1))
    assert CALENDAR_ID not in str(caught.value)
    assert "HTTP 500" in str(caught.value)


def test_an_answer_that_is_not_a_list_is_an_error(monkeypatch):
    monkeypatch.setattr("backend.roster_sync.fetch_json", lambda *a, **k: {"error": "nope"})
    with pytest.raises(SyncError):
        fetch_events(SETTINGS, date(2026, 10, 1), date(2026, 11, 1))


# ---- Settings ----


@pytest.fixture
def config_dir(tmp_path):
    target = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, target)
    write_admin_secrets(target)
    return target


def add_secret(config_dir, value):
    path = config_dir / "secrets.yaml"
    secrets = yaml.safe_load(path.read_text())
    secrets["calendar_online_id"] = value
    path.write_text(yaml.safe_dump(secrets))


def test_sync_is_off_without_a_calendar_id(config_dir):
    assert load_calendar_id(config_dir) is None
    assert SyncSettings.load(load_config(config_dir), config_dir) is None


def test_sync_is_on_with_a_calendar_id_and_the_block(config_dir):
    add_secret(config_dir, CALENDAR_ID)
    settings = SyncSettings.load(load_config(config_dir), config_dir)
    assert settings.calendar_id == CALENDAR_ID
    assert settings.vehicles == ("4",)
    assert settings.timezone == "Australia/Perth"


def test_a_malformed_calendar_id_is_refused_without_echoing_it(config_dir):
    add_secret(config_dir, "not an id/../x")
    with pytest.raises(SyncError) as caught:
        load_calendar_id(config_dir)
    assert "not an id" not in str(caught.value)


def test_a_block_naming_an_unknown_bus_stops_startup(config_dir):
    add_secret(config_dir, CALENDAR_ID)
    path = config_dir / "app.yaml"
    path.write_text(path.read_text().replace('  vehicles: ["4"]\n  # Every timed', '  vehicles: ["9"]\n  # Every timed'))
    from backend.config import ConfigError

    with pytest.raises(ConfigError, match="roster_sync.vehicles"):
        create_app(config_dir=config_dir)


# ---- Through the API ----


@pytest.fixture
def synced(config_dir, tmp_path):
    """
    A signed in client whose roster syncs from the CALENDAR fixture.
    """
    app = create_app(config_dir=config_dir)
    app.config.update(TESTING=True)
    store = SyncStore(tmp_path / "roster_sync.json")
    sync = RosterSync(SETTINGS, store, FLEET, fetch=lambda settings, start, end: CALENDAR)
    app.config.update(ROSTER_SYNC=sync, ROSTER_SYNC_STORE=store)
    with app.test_client() as client:
        yield sign_in(client), sync


def test_the_schedule_reports_synced_drives_apart_from_the_roster(synced):
    client, sync = synced
    sync.sync_once()
    body = client.get("/api/schedule").get_json()
    assert [p["operator"] for p in body["synced"]["tuesday"]] == ["Sam"]
    assert all(p["operator"] is None for p in body["schedule"]["tuesday"])
    assert body["sync"]["drives"] == 3
    assert body["sync"]["error"] is None


def test_saving_the_roster_never_writes_synced_drives(synced):
    client, sync = synced
    sync.sync_once()
    body = client.get("/api/schedule").get_json()
    client.put("/api/schedule", json=body["schedule"])
    assert "Sam" not in (client.application.config["NUWAY_CONFIG_PATH"]).read_text()


def test_sync_now_reads_the_calendar_again(synced):
    client, _ = synced
    response = client.post("/api/schedule/sync")
    assert response.status_code == 200
    assert response.get_json()["sync"]["synced_at"] is not None


def test_sync_now_is_admin_only(config_dir):
    app = create_app(config_dir=config_dir)
    with app.test_client() as client:
        assert client.post("/api/schedule/sync").status_code == 401


def test_sync_now_without_a_calendar_says_so(config_dir):
    app = create_app(config_dir=config_dir)
    with app.test_client() as client:
        response = sign_in(client).post("/api/schedule/sync")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "sync_off"
    assert app.config["ROSTER_SYNC"] is None


def test_metrics_count_a_synced_drive_as_scheduled(synced):
    client, sync = synced
    query = "?vehicles=4&from=2026-10-06&to=2026-10-06T23:59:59%2B08:00"
    before = client.get("/api/metrics" + query).get_json()["vehicles"][0]["buckets"]["scheduled_seconds"]
    sync.sync_once()
    after = client.get("/api/metrics" + query).get_json()["vehicles"][0]["buckets"]["scheduled_seconds"]
    assert after - before == 2 * 3600
