"""
Rider view chrome (S11): hiding the vehicle/route chips and the date-range
picker while on the Rider tab, forcing "today, live, every vehicle" while
there, and restoring whatever was selected before on leaving -- driven in a
real browser.

Playwright cannot download its own Chromium on macOS 13, so these run against
the Google Chrome already installed, or a Playwright-managed Chromium if one
is available. Without either, the whole module skips and the rest of the
suite is unaffected.
"""

from __future__ import annotations
import shutil
import threading

import pytest

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
werkzeug_serving = pytest.importorskip("werkzeug.serving")

STOPS_YAML = """
stops:
  - id: reid-library
    name: Reid Library
    latitude: -31.97901221771226
    longitude: 115.8183554056777
  - id: civ-mech
    name: Outside Civil and Mechanical Engineering
    latitude: -31.980743857374474
    longitude: 115.81720535774184

routes:
  - id: campus-loop
    name: Campus loop
    colour: "#d4741f"
    stops: [reid-library, civ-mech]
"""


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


@pytest.fixture
def config_dir(tmp_path):
    for name in ("app.yaml", "vehicles.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    (tmp_path / "stops.yaml").write_text(STOPS_YAML, encoding="utf-8")
    return tmp_path


@pytest.fixture
def server(config_dir):
    httpd = werkzeug_serving.make_server("127.0.0.1", 0, create_app(config_dir), threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def page(browser, server):
    context = browser.new_context()
    page = context.new_page()
    page.goto(server)
    page.wait_for_selector(".stop-label")
    yield page
    context.close()


def go_to_rider(page):
    page.get_by_role("button", name="Rider", exact=True).click()


def go_to_fleet(page):
    page.get_by_role("button", name="Fleet", exact=True).click()


# ---- S11: the chips and date picker are hidden on the Rider tab ----


def test_chrome_visible_by_default_on_fleet(page):
    assert page.locator("#vehicle-filter").is_visible()
    assert page.locator("#route-filter").is_visible()
    assert page.locator("#timeline-container").is_visible()


def test_rider_tab_hides_the_chips_and_date_picker(page):
    go_to_rider(page)
    assert page.locator("#vehicle-filter").is_hidden()
    assert page.locator("#route-filter").is_hidden()
    assert page.locator("#timeline-container").is_hidden()


def test_leaving_rider_restores_the_chrome(page):
    go_to_rider(page)
    go_to_fleet(page)
    assert page.locator("#vehicle-filter").is_visible()
    assert page.locator("#route-filter").is_visible()
    assert page.locator("#timeline-container").is_visible()


# ---- S11: riders default to today, live, every vehicle ----


def test_rider_tab_forces_today_live(page):
    go_to_rider(page)
    assert page.is_checked("#timeline-live")
    today = page.evaluate("new Date().toLocaleDateString('en-CA', {timeZone: 'Australia/Perth'})")
    assert page.input_value("#timeline-start-date") == today


def test_rider_tab_forces_every_vehicle(page):
    page.click('#vehicle-filter-chips .chip[data-vehicle="2"]')
    go_to_rider(page)
    # The chip row is hidden, but the underlying selection is what matters,
    # and the markup is still kept in sync underneath it.
    assert page.locator('#vehicle-filter-chips .chip[data-vehicle="all"]').get_attribute("class") == "chip is-active"


def test_leaving_rider_restores_the_previous_vehicle_selection(page):
    page.click('#vehicle-filter-chips .chip[data-vehicle="2"]')
    go_to_rider(page)
    go_to_fleet(page)
    assert page.locator('#vehicle-filter-chips .chip[data-vehicle="2"]').get_attribute("class") == "chip is-active"


# ---- S11: the rider's own period/vehicle choice is restored afterwards ----


def test_previous_period_and_vehicle_are_restored_after_rider(page):
    page.click('#vehicle-filter-chips .chip[data-vehicle="2"]')
    page.click("#timeline-live", force=True)  # switch Live off
    page.fill("#timeline-start-date", "2024-01-01")

    go_to_rider(page)
    go_to_fleet(page)

    assert page.input_value("#timeline-start-date") == "2024-01-01"
    assert not page.is_checked("#timeline-live")
    assert page.locator('#vehicle-filter-chips .chip[data-vehicle="2"]').get_attribute("class") == "chip is-active"


def test_clicking_rider_twice_does_not_lose_the_original_selection(page):
    """
    enterRiderDefaults() must not overwrite its saved state on a second,
    no-op entry (e.g. clicking the already-active Rider tab again).
    """
    page.click('#vehicle-filter-chips .chip[data-vehicle="3"]')
    go_to_rider(page)
    go_to_rider(page)  # already there; must be a no-op
    go_to_fleet(page)

    assert page.locator('#vehicle-filter-chips .chip[data-vehicle="3"]').get_attribute("class") == "chip is-active"


# ---- S11: leaving for Utilisation (not just Fleet/Operator) also restores ----


def test_leaving_rider_for_utilisation_restores_the_chrome(page):
    go_to_rider(page)
    page.get_by_role("button", name="Utilisation", exact=True).click()
    assert page.locator("#vehicle-filter").is_visible()


# ---- S11.1: no horizontal scroll on a phone, confirmed still true ----


def test_no_horizontal_scroll_on_a_phone(page):
    page.set_viewport_size({"width": 390, "height": 844})
    go_to_rider(page)
    assert page.evaluate("document.documentElement.scrollWidth") == page.evaluate("document.documentElement.clientWidth")
