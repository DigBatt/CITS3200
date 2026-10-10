"""
Rider view, outside shuttle hours (S15 follow-up): visiting the Rider tab
shows a "closed" message in place of the stop picker, in a real browser.
backend logic and the API gate: tests/test_operating_hours.py.
"""

from __future__ import annotations
import shutil
import threading

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.operating_hours import DAYS

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
werkzeug_serving = pytest.importorskip("werkzeug.serving")

STOPS_YAML = """
stops:
  - id: reid-library
    name: Reid Library
    latitude: -31.97901221771226
    longitude: 115.8183554056777

routes:
  - id: campus-loop
    name: Campus loop
    colour: "#d4741f"
    stops: [reid-library]
"""

ALL_DAY = {day: ["00:00", "23:59"] for day in DAYS}
ALL_CLOSED = {day: None for day in DAYS}


@pytest.fixture(scope="module")
def browser():
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


def _app(tmp_path, operating_hours):
    shutil.copy(DEFAULT_CONFIG_DIR / "vehicles.yaml", tmp_path / "vehicles.yaml")
    (tmp_path / "stops.yaml").write_text(STOPS_YAML, encoding="utf-8")

    app_config = yaml.safe_load((DEFAULT_CONFIG_DIR / "app.yaml").read_text(encoding="utf-8"))
    app_config.setdefault("pickup_requests", {})["operating_hours"] = operating_hours
    app_config["storage"] = {"directory": str(tmp_path / "admin")}
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")

    return create_app(tmp_path)


def _rider_page(browser, app):
    httpd = werkzeug_serving.make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    context = browser.new_context()
    page = context.new_page()
    page.goto(f"http://127.0.0.1:{httpd.server_port}")
    page.wait_for_function("stopMarkers.size > 0")
    page.get_by_role("button", name="Rider", exact=True).click()

    yield page

    context.close()
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def closed_page(browser, tmp_path):
    yield from _rider_page(browser, _app(tmp_path, ALL_CLOSED))


@pytest.fixture
def open_page(browser, tmp_path):
    yield from _rider_page(browser, _app(tmp_path, ALL_DAY))


def test_outside_hours_the_closed_message_replaces_the_picker(closed_page):
    page = closed_page
    page.wait_for_selector("#rider-closed:not([hidden])")
    assert page.locator("#rider-picker").is_hidden()
    assert "No shuttle service today" in page.locator("#rider-closed-note").inner_text()


def test_within_hours_the_picker_shows_not_the_closed_message(open_page):
    page = open_page
    page.wait_for_selector("#rider-stop-select:not([disabled])")
    assert page.locator("#rider-closed").is_hidden()


def test_a_request_within_hours_still_succeeds(open_page):
    page = open_page
    page.wait_for_selector("#rider-stop-select:not([disabled])")
    page.select_option("#rider-stop-select", "reid-library")

    with page.expect_response(lambda r: "/api/pickup-requests" in r.url and r.request.method == "POST") as resp:
        page.click("#rider-request-button")
    assert resp.value.status == 201
    page.wait_for_selector("#rider-waiting:not([hidden])")
