"""
Operator view (S09): backend.pickup_requests.waiting_at_stops, the
/api/routes/<id>/waiting endpoint, and the page itself in a real browser.
"""

from __future__ import annotations
import json
import re
import shutil
import threading
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from backend.app import FRONTEND, create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.models import PickupRequest
from backend.pickup_requests import waiting_at_stops


def stop(stop_id, latitude=-31.98, longitude=115.82):
    return {"id": stop_id, "name": stop_id.replace("-", " ").title(), "latitude": latitude, "longitude": longitude}


# 'off-route' is on the other route only; the loop runs north-end, shared, south-end.
NETWORK = {
    "stops": [stop("north-end"), stop("shared"), stop("south-end"), stop("off-route")],
    "routes": [
        {"id": "loop", "name": "Campus loop", "loop": True, "stops": ["north-end", "shared", "south-end"]},
        {"id": "spur", "name": "Spur", "stops": ["shared", "off-route"]},
    ],
}

NOW = datetime(2025, 9, 4, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def config_dir(tmp_path):
    for name in ("app.yaml", "vehicles.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    (tmp_path / "stops.yaml").write_text(yaml.safe_dump(NETWORK, sort_keys=False), encoding="utf-8")
    return tmp_path


@pytest.fixture
def app(config_dir):
    return create_app(config_dir)


@pytest.fixture
def client(app):
    return app.test_client()


def open_request(app, stop_id, rider, minutes_ago):
    """
    A request opened `minutes_ago` before the real now, straight into the store.
    """
    created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return app.config["PICKUP_REQUEST_STORE"].create(stop_id, rider, created)[0]


def by_id(body):
    return {s["id"]: s for s in body["stops"]}


# ---- waiting_at_stops ----


def request(stop_id, minutes_ago, status=PickupRequest.OPEN):
    return PickupRequest(
        id=f"{stop_id}-{minutes_ago}",
        stop_id=stop_id,
        rider_token="t",
        status=status,
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


def test_counts_follow_the_given_stop_order():
    result = waiting_at_stops([request("b", 1), request("a", 2), request("b", 5)], ["a", "b", "c"])
    assert [(w.stop_id, w.waiting) for w in result] == [("a", 1), ("b", 2), ("c", 0)]


def test_oldest_is_the_earliest_open_request():
    result = waiting_at_stops([request("a", 1), request("a", 9), request("a", 4)], ["a"])
    assert result[0].oldest_created_at == NOW - timedelta(minutes=9)


def test_stops_off_the_list_and_closed_requests_are_ignored():
    requests = [request("x", 1), request("a", 30, status=PickupRequest.COLLECTED), request("a", 2)]
    result = waiting_at_stops(requests, ["a"])
    assert result[0].waiting == 1
    assert result[0].oldest_created_at == NOW - timedelta(minutes=2)


# ---- S09.2: GET /api/routes/<id>/waiting ----


def test_unknown_route_is_404(client):
    response = client.get("/api/routes/nope/waiting")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "unknown_route"


def test_stops_are_in_service_order(client):
    body = client.get("/api/routes/loop/waiting").get_json()
    assert [s["id"] for s in body["stops"]] == ["north-end", "shared", "south-end"]
    assert body["route"]["id"] == "loop"
    assert body["route"]["loop"] is True


def test_no_riders_waiting(client):
    body = client.get("/api/routes/loop/waiting").get_json()
    assert body["total_waiting"] == 0
    for s in body["stops"]:
        assert s["waiting"] == 0
        assert s["oldest_requested_at"] is None
        assert s["oldest_wait_seconds"] is None


def test_counts_and_oldest_age_are_correct(app, client):
    open_request(app, "shared", "rider-a", minutes_ago=2)
    open_request(app, "shared", "rider-b", minutes_ago=7)
    open_request(app, "south-end", "rider-a", minutes_ago=1)

    body = client.get("/api/routes/loop/waiting").get_json()
    stops = by_id(body)

    assert body["total_waiting"] == 3
    assert stops["north-end"]["waiting"] == 0
    assert stops["shared"]["waiting"] == 2
    assert stops["south-end"]["waiting"] == 1
    assert stops["shared"]["oldest_wait_seconds"] == pytest.approx(7 * 60, abs=5)
    assert stops["south-end"]["oldest_wait_seconds"] == pytest.approx(60, abs=5)


def test_off_route_request_is_not_shown(app, client):
    open_request(app, "off-route", "rider-a", minutes_ago=3)

    body = client.get("/api/routes/loop/waiting").get_json()
    assert "off-route" not in by_id(body)
    assert body["total_waiting"] == 0

    # The same request does count on the route that serves that stop.
    spur = by_id(client.get("/api/routes/spur/waiting").get_json())
    assert spur["off-route"]["waiting"] == 1


def test_request_posted_by_a_rider_shows_on_the_next_poll(client):
    client.post("/api/pickup-requests", json={"stop_id": "north-end"})
    stops = by_id(client.get("/api/routes/loop/waiting").get_json())
    assert stops["north-end"]["waiting"] == 1
    assert stops["north-end"]["oldest_wait_seconds"] < 5


# ---- S09.3 to S09.6: the page, in a real browser ----


def test_page_refreshes_within_30_seconds():
    """
    S09.5 without a browser: the page's poll interval is inside the 30 s the
    story allows. The browser test below checks the page actually updates.
    """
    source = (FRONTEND / "js" / "operator.js").read_text(encoding="utf-8")
    match = re.search(r"const OPERATOR_REFRESH_MS = (\d+);", source)
    assert match, "OPERATOR_REFRESH_MS not found in operator.js"
    assert 0 < int(match.group(1)) <= 30_000


@pytest.fixture(scope="module")
def browser():
    """
    Google Chrome if installed, else the Chromium from `playwright install
    chromium` (the easy option under WSL). Skips if neither launches.
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


def post_request(server, stop_id):
    data = json.dumps({"stop_id": stop_id}).encode()
    req = urllib.request.Request(
        f"{server}/api/pickup-requests", data=data, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req).close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{server}/admin?route=loop&vehicle=1")
    page.wait_for_selector("#operator-stops .operator-stop")
    yield page
    context.close()


def test_page_shows_stops_in_order_with_empty_state(page):
    names = page.locator(".operator-stop-name").all_inner_texts()
    assert [n.split("VEHICLE HERE")[0].strip() for n in names] == ["North End", "Shared", "South End"]
    assert page.locator("#operator-empty").is_visible()


def test_new_request_appears_within_30_seconds_without_reload(page, server):
    page.evaluate("window.__notReloaded = true")

    post_request(server, "shared")
    post_request(server, "off-route")

    shared = page.locator('.operator-stop[data-stop-id="shared"] .operator-stop-waiting')
    shared.filter(has_text="1").wait_for(timeout=30_000)

    assert page.evaluate("window.__notReloaded") is True
    assert page.locator('.operator-stop[data-stop-id="off-route"]').count() == 0
    assert page.locator("#operator-empty").is_hidden()
