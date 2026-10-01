"""
Downtime (S18-S20): backend.downtime.DowntimeStore and merged_intervals, the
/api/downtime endpoints, and the admin page's Downtime tab in a real browser.
"""

from __future__ import annotations
import json
import shutil
import threading
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.downtime import DowntimeStore, merged_intervals
from backend.models import Downtime
from backend.repository.base import RepositoryError
from tests.admin_support import ADMIN_PASSWORD, ADMIN_USERNAME, sign_in, write_admin_secrets

T0 = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)  # 09:00 in Perth


def at(hours):
    return T0 + timedelta(hours=hours)


def iso(hours):
    return at(hours).isoformat()


@pytest.fixture
def config_dir(tmp_path):
    """
    The real config with storage pointed into this test's directory.
    """
    for name in ("vehicles.yaml", "stops.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    app_config = yaml.safe_load((DEFAULT_CONFIG_DIR / "app.yaml").read_text(encoding="utf-8"))
    app_config["storage"] = {"directory": str(tmp_path / "admin")}
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")
    write_admin_secrets(tmp_path)
    return tmp_path


@pytest.fixture
def downtime_file(config_dir):
    return config_dir / "admin" / "downtime.json"


@pytest.fixture
def client(config_dir):
    return sign_in(create_app(config_dir).test_client())


def post(client, vehicle_id="1", start=0, end=2, reason="Scheduled maintenance", **extra):
    body = {"vehicle_id": vehicle_id, "start": iso(start), "end": iso(end), "reason": reason, **extra}
    return client.post("/api/downtime", json=body)


def error_code(response):
    return response.get_json()["error"]["code"]


# ---- DowntimeStore ----


def test_missing_file_means_no_records(tmp_path):
    assert DowntimeStore(tmp_path / "downtime.json").list() == []


def test_records_survive_a_new_store_on_the_same_file(tmp_path):
    """
    S18.2: still present after a restart.
    """
    path = tmp_path / "downtime.json"
    added = DowntimeStore(path).add("1", at(0), at(2), "Tyre", T0)
    assert DowntimeStore(path).list() == [added]


def test_store_rejects_end_not_after_start(tmp_path):
    with pytest.raises(ValueError):
        DowntimeStore(tmp_path / "downtime.json").add("1", at(2), at(2), "Tyre", T0)


def test_list_filters_by_vehicle_and_window_and_sorts_by_start(tmp_path):
    store = DowntimeStore(tmp_path / "downtime.json")
    late = store.add("1", at(5), at(6), "b", T0)
    early = store.add("1", at(0), at(1), "a", T0)
    store.add("2", at(0), at(1), "other vehicle", T0)

    assert store.list(["1"]) == [early, late]
    # Touching the window's edge is not overlapping it.
    assert store.list(["1"], start=at(1), end=at(5)) == []
    assert store.list(["1"], start=at(0.5), end=at(5.5)) == [early, late]


def test_update_keeps_created_at_and_moves_updated_at(tmp_path):
    store = DowntimeStore(tmp_path / "downtime.json")
    added = store.add("1", at(0), at(2), "Tyre", T0)
    updated = store.update(added.id, "2", at(1), at(3), "Battery", at(10))
    assert updated == Downtime(added.id, "2", at(1), at(3), "Battery", T0, at(10))
    assert store.get(added.id) == updated


def test_update_and_delete_unknown_id(tmp_path):
    store = DowntimeStore(tmp_path / "downtime.json")
    assert store.update("nope", "1", at(0), at(1), "x", T0) is None
    assert store.delete("nope") is False


def test_delete_removes_only_that_record(tmp_path):
    store = DowntimeStore(tmp_path / "downtime.json")
    gone = store.add("1", at(0), at(1), "a", T0)
    kept = store.add("1", at(2), at(3), "b", T0)
    assert store.delete(gone.id) is True
    assert store.list() == [kept]


def test_overlapping_excludes_the_record_being_edited_and_touching_periods(tmp_path):
    store = DowntimeStore(tmp_path / "downtime.json")
    record = store.add("1", at(0), at(2), "a", T0)
    assert store.overlapping("1", at(1), at(3)) == [record]
    assert store.overlapping("1", at(1), at(3), exclude_id=record.id) == []
    assert store.overlapping("1", at(2), at(3)) == []
    assert store.overlapping("2", at(1), at(3)) == []


def test_corrupt_file_is_a_repository_error(tmp_path):
    path = tmp_path / "downtime.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RepositoryError, match="not a valid downtime file"):
        DowntimeStore(path).list()


def test_unknown_file_version_is_a_repository_error(tmp_path):
    path = tmp_path / "downtime.json"
    path.write_text(json.dumps({"version": 99, "records": []}), encoding="utf-8")
    with pytest.raises(RepositoryError, match="unsupported version"):
        DowntimeStore(path).list()


def test_file_holds_utc_timestamps_in_the_canonical_form(tmp_path):
    path = tmp_path / "downtime.json"
    DowntimeStore(path).add("1", at(0), at(2), "Tyre", T0)
    record = json.loads(path.read_text(encoding="utf-8"))["records"][0]
    assert record["start"] == "2026-10-01T01:00:00.000000Z"
    assert record["end"] == "2026-10-01T03:00:00.000000Z"


# ---- merged_intervals ----


def record(start, end):
    return Downtime("id", "1", at(start), at(end), "r", T0, T0)


def test_merged_intervals_joins_overlapping_and_touching_records():
    records = [record(4, 5), record(0, 2), record(1, 3), record(3, 3.5)]
    assert merged_intervals(records) == [(at(0), at(3.5)), (at(4), at(5))]


def test_merged_intervals_clips_to_the_window_and_drops_what_falls_outside():
    records = [record(0, 2), record(5, 6)]
    assert merged_intervals(records, start=at(1), end=at(4)) == [(at(1), at(2))]


# ---- S18-S20: the endpoints ----


def test_signed_out_is_401(config_dir):
    client = create_app(config_dir).test_client()
    assert client.get("/api/downtime").status_code == 401
    assert post(client).status_code == 401


def test_create_then_list(client):
    response = post(client)
    assert response.status_code == 201
    created = response.get_json()["record"]
    assert created["vehicle_id"] == "1"
    assert created["start"] == "2026-10-01T01:00:00.000000Z"
    assert created["reason"] == "Scheduled maintenance"

    assert client.get("/api/downtime").get_json() == {"records": [created]}


def test_record_survives_a_restart(config_dir, client):
    """
    S18.2: a new app on the same config still has the record.
    """
    created = post(client).get_json()["record"]
    restarted = sign_in(create_app(config_dir).test_client())
    assert restarted.get("/api/downtime").get_json()["records"] == [created]


def test_offset_timestamps_are_stored_as_utc(client):
    body = {"vehicle_id": "1", "start": "2026-10-01T09:00:00+08:00", "end": "2026-10-01T11:00:00+08:00", "reason": "x"}
    created = client.post("/api/downtime", json=body).get_json()["record"]
    assert created["start"] == "2026-10-01T01:00:00.000000Z"


def test_end_before_start_is_rejected_and_not_stored(client):
    """
    S18.3.
    """
    response = post(client, start=2, end=1)
    assert response.status_code == 400
    assert error_code(response) == "bad_range"
    assert client.get("/api/downtime").get_json()["records"] == []


@pytest.mark.parametrize(
    "body, code",
    [
        ({"start": iso(0), "end": iso(1), "reason": "x"}, "missing_field"),
        ({"vehicle_id": "1", "end": iso(1), "reason": "x"}, "missing_field"),
        ({"vehicle_id": "1", "start": iso(0), "end": iso(1)}, "missing_field"),
        ({"vehicle_id": "1", "start": iso(0), "end": iso(1), "reason": "   "}, "missing_field"),
        ({"vehicle_id": "9", "start": iso(0), "end": iso(1), "reason": "x"}, "unknown_vehicle"),
        ({"vehicle_id": "1", "start": "yesterday", "end": iso(1), "reason": "x"}, "bad_timestamp"),
        ({"vehicle_id": "1", "start": "2026-10-01T09:00:00", "end": iso(1), "reason": "x"}, "bad_timestamp"),
    ],
)
def test_invalid_bodies_are_400(client, body, code):
    response = client.post("/api/downtime", json=body)
    assert response.status_code == 400
    assert error_code(response) == code


def test_overlap_warns_before_storing_then_confirm_stores(client):
    """
    S18.4: warned before it is stored.
    """
    first = post(client, start=0, end=2).get_json()["record"]

    warned = post(client, start=1, end=3)
    assert warned.status_code == 409
    assert error_code(warned) == "overlap"
    assert warned.get_json()["overlaps"] == [first]
    assert len(client.get("/api/downtime").get_json()["records"]) == 1

    assert post(client, start=1, end=3, confirm=True).status_code == 201
    assert len(client.get("/api/downtime").get_json()["records"]) == 2


def test_overlap_is_per_vehicle_and_touching_is_not_overlap(client):
    post(client, vehicle_id="1", start=0, end=2)
    assert post(client, vehicle_id="2", start=0, end=2).status_code == 201
    assert post(client, vehicle_id="1", start=2, end=3).status_code == 201


def test_list_filters_by_vehicle_and_window(client):
    post(client, vehicle_id="1", start=0, end=1)
    post(client, vehicle_id="2", start=0, end=1)
    later = post(client, vehicle_id="1", start=48, end=49).get_json()["record"]

    assert len(client.get("/api/downtime?vehicles=1").get_json()["records"]) == 2
    assert client.get(f"/api/downtime?vehicles=1&from={at(24).isoformat().replace('+', '%2B')}").get_json()[
        "records"
    ] == [later]


def test_list_bad_parameters_are_400(client):
    assert error_code(client.get("/api/downtime?vehicles=9")) == "unknown_vehicle"
    assert error_code(client.get("/api/downtime?from=nonsense")) == "bad_timestamp"
    assert error_code(client.get("/api/downtime?from=2026-10-02&to=2026-10-01")) == "bad_range"


def test_patch_changes_only_the_fields_sent(client):
    """
    S20.1.
    """
    created = post(client).get_json()["record"]
    response = client.patch(f"/api/downtime/{created['id']}", json={"reason": "Battery swap"})
    assert response.status_code == 200
    updated = response.get_json()["record"]
    assert updated["reason"] == "Battery swap"
    assert (updated["start"], updated["end"], updated["vehicle_id"]) == (
        created["start"],
        created["end"],
        created["vehicle_id"],
    )
    assert client.get("/api/downtime").get_json()["records"] == [updated]


def test_patch_does_not_clash_with_itself_but_does_with_others(client):
    first = post(client, start=0, end=2).get_json()["record"]
    second = post(client, start=3, end=4).get_json()["record"]

    assert client.patch(f"/api/downtime/{first['id']}", json={"end": iso(2.5)}).status_code == 200

    clash = client.patch(f"/api/downtime/{second['id']}", json={"start": iso(1)})
    assert clash.status_code == 409
    assert [r["id"] for r in clash.get_json()["overlaps"]] == [first["id"]]

    confirmed = client.patch(f"/api/downtime/{second['id']}", json={"start": iso(1), "confirm": True})
    assert confirmed.status_code == 200


def test_patch_of_only_the_reason_does_not_warn_again(client):
    first = post(client, start=0, end=2).get_json()["record"]
    post(client, start=1, end=3, confirm=True)
    assert client.patch(f"/api/downtime/{first['id']}", json={"reason": "Battery"}).status_code == 200


def test_patch_end_before_start_is_400(client):
    created = post(client, start=0, end=2).get_json()["record"]
    response = client.patch(f"/api/downtime/{created['id']}", json={"end": iso(-1)})
    assert error_code(response) == "bad_range"


def test_delete_then_gone(client):
    """
    S20.2.
    """
    created = post(client).get_json()["record"]
    assert client.delete(f"/api/downtime/{created['id']}").status_code == 204
    assert client.get("/api/downtime").get_json()["records"] == []


def test_unknown_id_is_404(client):
    assert error_code(client.patch("/api/downtime/nope", json={"reason": "x"})) == "unknown_downtime"
    assert client.delete("/api/downtime/nope").status_code == 404


def test_unset_storage_directory_is_data_unavailable(config_dir):
    app_config = yaml.safe_load((config_dir / "app.yaml").read_text(encoding="utf-8"))
    del app_config["storage"]
    (config_dir / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")
    client = sign_in(create_app(config_dir).test_client())

    response = client.get("/api/downtime")
    assert response.status_code == 500
    assert error_code(response) == "data_unavailable"
    assert "storage.directory" in response.get_json()["error"]["message"]


def test_corrupt_file_is_data_unavailable(client, downtime_file):
    downtime_file.parent.mkdir(parents=True)
    downtime_file.write_text("{not json", encoding="utf-8")
    response = client.get("/api/downtime")
    assert response.status_code == 500
    assert error_code(response) == "data_unavailable"


# ---- The Downtime tab in a browser ----


@pytest.fixture(scope="module")
def browser():
    """
    Google Chrome if installed, else the Chromium from `playwright install
    chromium`. Skips if neither launches.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as playwright:
        launched, failures = None, []
        for channel in ("chrome", None):
            try:
                launched = playwright.chromium.launch(channel=channel)
                break
            except Exception as exc:  # noqa: BLE001 - any launch failure means try the next browser
                failures.append(f"{channel or 'chromium'}: {str(exc).splitlines()[0]}")
        if launched is None:
            pytest.skip("No browser to test in (" + "; ".join(failures) + ")")
        yield launched
        launched.close()


@pytest.fixture
def server(config_dir):
    werkzeug_serving = pytest.importorskip("werkzeug.serving")
    httpd = werkzeug_serving.make_server("127.0.0.1", 0, create_app(config_dir), threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def page(browser, server):
    context = browser.new_context(timezone_id="Australia/Perth")
    page = context.new_page()
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(f"{server}/admin")
    page.fill("#login-username", ADMIN_USERNAME)
    page.fill("#login-password", ADMIN_PASSWORD)
    page.click("#btn-login")
    page.wait_for_url(f"{server}/admin")
    page.click('.app-tab[data-tab="downtime"]')
    page.wait_for_selector('#dt-vehicle option[value="1"]', state="attached")
    yield page
    context.close()


def fill_form(page, start, end, reason, vehicle="1"):
    page.select_option("#dt-vehicle", vehicle)
    page.fill("#dt-start", start)
    page.fill("#dt-end", end)
    page.fill("#dt-reason", reason)


def rows(page):
    return page.locator("#downtime-tbody tr[data-id]")


def test_tab_adds_warns_edits_and_deletes(page, downtime_file):
    fill_form(page, "2026-10-01T09:00", "2026-10-01T11:00", "Tyre change")
    page.click("#btn-downtime-save")
    rows(page).first.wait_for()
    stored = json.loads(downtime_file.read_text(encoding="utf-8"))["records"]
    # Entered in Perth time, stored as UTC.
    assert [(r["start"], r["end"]) for r in stored] == [("2026-10-01T01:00:00.000000Z", "2026-10-01T03:00:00.000000Z")]

    # An overlap warns and stores nothing until "Save anyway".
    fill_form(page, "2026-10-01T10:00", "2026-10-01T12:00", "Battery")
    page.click("#btn-downtime-save")
    page.locator("#downtime-overlap-warning.visible").wait_for()
    assert page.inner_text("#btn-downtime-save") == "Save anyway"
    assert rows(page).count() == 1
    page.click("#btn-downtime-save")
    page.wait_for_function("document.querySelectorAll('#downtime-tbody tr[data-id]').length === 2")
    assert page.locator("#downtime-overlap-warning").is_hidden()

    # Edit fills the form with the local times and saves in place.
    rows(page).first.locator("text=Edit").click()
    assert page.input_value("#dt-start") == "2026-10-01T09:00"
    page.fill("#dt-reason", "Tyre change and alignment")
    page.click("#btn-downtime-save")
    page.locator("#downtime-tbody", has_text="Tyre change and alignment").wait_for()
    assert rows(page).count() == 2

    # Still there after a reload, then deleted.
    page.reload()
    page.click('.app-tab[data-tab="downtime"]')
    page.wait_for_function("document.querySelectorAll('#downtime-tbody tr[data-id]').length === 2")
    rows(page).first.locator("text=Delete").click()
    page.wait_for_function("document.querySelectorAll('#downtime-tbody tr[data-id]').length === 1")
    assert len(json.loads(downtime_file.read_text(encoding="utf-8"))["records"]) == 1
