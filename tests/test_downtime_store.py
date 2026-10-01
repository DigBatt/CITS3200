"""
DowntimeStore: the round trip, editing, deleting, and the overlap rule.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import Downtime, Vehicle
from backend.repository.base import RepositoryError
from backend.repository.downtime_store import DowntimeStore

T0 = datetime(2026, 9, 17, 1, 0, 0, 123456, tzinfo=timezone.utc)


def make_store(tmp_path, ids=("1", "2")) -> DowntimeStore:
    return DowntimeStore(tmp_path / "downtime.json", [Vehicle(id=i) for i in ids])


def add(store, vehicle_id="1", start_h=0.0, hours=1.0, reason="Brake fault") -> Downtime:
    start = T0 + timedelta(hours=start_h)
    return store.add(vehicle_id, start, start + timedelta(hours=hours), reason)


def test_round_trip_keeps_values_and_microseconds(tmp_path):
    store = make_store(tmp_path)
    stored = add(store, reason="Scheduled service")

    read = store.get(stored.id)
    assert read == stored
    assert read.start == T0
    assert read.end == T0 + timedelta(hours=1)
    assert read.reason == "Scheduled service"
    assert read.duration_seconds == 3600


def test_records_survive_reopening_the_file(tmp_path):
    stored = add(make_store(tmp_path))
    assert make_store(tmp_path).get(stored.id) == stored


def test_creates_missing_directory(tmp_path):
    store = DowntimeStore(tmp_path / "live" / "downtime.json", [Vehicle(id="1")])
    add(store)
    assert (tmp_path / "live" / "downtime.json").exists()


def test_ids_are_assigned_and_unique(tmp_path):
    store = make_store(tmp_path)
    ids = {add(store, start_h=h).id for h in range(5)}
    assert len(ids) == 5
    assert all(ids)


def test_created_and_updated_set_on_write(tmp_path):
    stored = add(make_store(tmp_path))
    assert stored.created_at is not None
    assert stored.updated_at == stored.created_at


def test_list_is_ascending_by_start(tmp_path):
    store = make_store(tmp_path)
    for hour in (5, 1, 3):
        add(store, start_h=hour)
    assert [r.start for r in store.list()] == [T0 + timedelta(hours=h) for h in (1, 3, 5)]


def test_list_filters_by_vehicle(tmp_path):
    store = make_store(tmp_path)
    add(store, "1", start_h=0)
    add(store, "2", start_h=2)
    assert [r.vehicle_id for r in store.list(["2"])] == ["2"]
    assert len(store.list(["1", "2"])) == 2
    assert len(store.list([])) == 2


def test_list_returns_records_overlapping_the_window(tmp_path):
    store = make_store(tmp_path)
    spanning = add(store, start_h=0, hours=10)
    add(store, start_h=20, hours=1)

    window = (T0 + timedelta(hours=4), T0 + timedelta(hours=6))
    assert [r.id for r in store.list(None, *window)] == [spanning.id]


def test_list_excludes_records_that_only_touch_the_window(tmp_path):
    store = make_store(tmp_path)
    add(store, start_h=0, hours=2)
    assert store.list(None, T0 + timedelta(hours=2), T0 + timedelta(hours=3)) == []


def test_update_changes_only_the_fields_given(tmp_path):
    store = make_store(tmp_path)
    stored = add(store, reason="Brake fault")

    updated = store.update(stored.id, reason="Brake fault, parts on order")
    assert updated.reason == "Brake fault, parts on order"
    assert updated.start == stored.start
    assert updated.end == stored.end
    assert updated.vehicle_id == stored.vehicle_id
    assert updated.created_at == stored.created_at


def test_update_can_move_the_period(tmp_path):
    store = make_store(tmp_path)
    stored = add(store)
    moved = store.update(stored.id, end=T0 + timedelta(hours=4))
    assert moved.end == T0 + timedelta(hours=4)
    assert store.get(stored.id).duration_seconds == 4 * 3600


def test_update_rejects_an_end_before_its_new_start(tmp_path):
    store = make_store(tmp_path)
    stored = add(store)
    with pytest.raises(ValueError):
        store.update(stored.id, start=stored.end + timedelta(hours=1))
    assert store.get(stored.id) == stored


def test_update_and_delete_report_a_missing_record(tmp_path):
    store = make_store(tmp_path)
    assert store.update("nope", reason="x") is None
    assert store.delete("nope") is False


def test_delete_removes_only_its_own_record(tmp_path):
    store = make_store(tmp_path)
    first, second = add(store, start_h=0), add(store, start_h=5)
    assert store.delete(first.id) is True
    assert [r.id for r in store.list()] == [second.id]


def test_end_must_be_after_start(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.add("1", T0, T0 - timedelta(hours=1), "Backwards")
    with pytest.raises(ValueError):
        store.add("1", T0, T0, "Zero length")
    assert store.list() == []


def test_reason_is_required_and_stripped(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.add("1", T0, T0 + timedelta(hours=1), "   ")
    assert add(store, reason="  Flat battery  ").reason == "Flat battery"


def test_naive_times_are_read_as_utc(tmp_path):
    store = make_store(tmp_path)
    stored = store.add("1", datetime(2026, 9, 17, 1), datetime(2026, 9, 17, 2), "No timezone")
    assert stored.start == datetime(2026, 9, 17, 1, tzinfo=timezone.utc)


def test_unknown_vehicle_rejected_before_any_write(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(RepositoryError):
        add(store, "99")
    assert store.list() == []


def test_unknown_vehicle_allowed_when_no_fleet_given(tmp_path):
    store = DowntimeStore(tmp_path / "downtime.json")
    assert add(store, "99").vehicle_id == "99"


def test_reads_are_not_filtered_by_the_configured_fleet(tmp_path):
    stored = add(DowntimeStore(tmp_path / "downtime.json"), "retired")
    assert make_store(tmp_path).get(stored.id) == stored


def test_overlapping_finds_a_clash_on_the_same_vehicle(tmp_path):
    store = make_store(tmp_path)
    existing = add(store, "1", start_h=0, hours=4)
    clash = store.overlapping("1", T0 + timedelta(hours=3), T0 + timedelta(hours=6))
    assert [r.id for r in clash] == [existing.id]


def test_overlapping_ignores_other_vehicles_and_touching_periods(tmp_path):
    store = make_store(tmp_path)
    add(store, "1", start_h=0, hours=2)
    assert store.overlapping("2", T0, T0 + timedelta(hours=2)) == []
    assert store.overlapping("1", T0 + timedelta(hours=2), T0 + timedelta(hours=3)) == []


def test_overlapping_can_exclude_the_record_being_edited(tmp_path):
    store = make_store(tmp_path)
    stored = add(store, hours=4)
    assert store.overlapping("1", stored.start, stored.end) != []
    assert store.overlapping("1", stored.start, stored.end, exclude_id=stored.id) == []


def test_overlap_is_allowed_but_reported(tmp_path):
    store = make_store(tmp_path)
    add(store, start_h=0, hours=4)
    add(store, start_h=2, hours=4)
    assert len(store.list()) == 2


def test_to_dict_uses_the_canonical_timestamp_form(tmp_path):
    payload = add(make_store(tmp_path)).to_dict()
    assert payload["start"] == "2026-09-17T01:00:00.123456Z"
    assert payload["vehicle_id"] == "1"
    assert set(payload) == {"id", "vehicle_id", "start", "end", "reason", "created_at", "updated_at"}


def test_from_config_needs_the_database_path(tmp_path):
    from backend.config import Config

    blank = Config(
        vehicles=[], data_directory=None, live_directory=None, downtime_file=None,
        inactivity_threshold_seconds=None, expected_poll_interval_seconds=None, timezone=None,
        utc_offset_hours=None, map_centre=None, map_zoom=None, refresh_interval_seconds=None,
        utilisation=None, logger=None,
    )
    with pytest.raises(RepositoryError):
        DowntimeStore.from_config(blank)


def test_from_config_builds_a_usable_store(tmp_path):
    from backend.config import load_config

    config = load_config()
    assert config.downtime_file is not None

    store = DowntimeStore(tmp_path / "downtime.json", config.vehicles)
    first = config.vehicles[0].id
    assert store.add(first, T0, T0 + timedelta(hours=1), "From config").vehicle_id == first


# ---- The JSON file itself ----


def test_the_file_is_readable_json_in_time_order(tmp_path):
    import json

    store = make_store(tmp_path)
    later = add(store, start_h=5, reason="Later")
    earlier = add(store, start_h=1, reason="Earlier")

    data = json.loads((tmp_path / "downtime.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert [r["id"] for r in data["records"]] == [earlier.id, later.id]
    assert data["records"][0]["start"] == "2026-09-17T02:00:00.123456Z"
    assert set(data["records"][0]) == {"id", "vehicle_id", "start", "end", "reason", "created_at", "updated_at"}


def test_a_new_store_starts_an_empty_file(tmp_path):
    import json

    make_store(tmp_path)
    assert json.loads((tmp_path / "downtime.json").read_text()) == {"version": 1, "records": []}


@pytest.mark.parametrize(
    "content",
    ["{not json", '{"version": 2, "records": []}', '[]', '{"version": 1, "records": [{"id": "x"}]}'],
    ids=["not-json", "unknown-version", "not-an-object", "incomplete-record"],
)
def test_a_damaged_file_is_refused_and_left_alone(tmp_path, content):
    path = tmp_path / "downtime.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(RepositoryError):
        DowntimeStore(path, [Vehicle(id="1")])
    assert path.read_text(encoding="utf-8") == content


def test_a_write_by_another_process_is_seen(tmp_path):
    # Two stores on one file stand in for two server processes.
    first, second = make_store(tmp_path), make_store(tmp_path)
    stored = add(first, reason="From the other process")

    assert second.get(stored.id) == stored
    assert second.delete(stored.id)
    assert first.get(stored.id) is None


def test_writes_leave_no_temporary_files(tmp_path):
    store = make_store(tmp_path)
    record = add(store)
    store.update(record.id, reason="Changed")
    store.delete(record.id)

    assert [p.name for p in tmp_path.iterdir()] == ["downtime.json"]


def test_a_write_returns_what_a_read_gives_back(tmp_path):
    store = make_store(tmp_path)
    stored = add(store)
    updated = store.update(stored.id, reason="Changed")

    reopened = make_store(tmp_path)
    assert reopened.get(stored.id) == updated
