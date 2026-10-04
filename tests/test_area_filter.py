"""
Area filter chips (S11 follow-up): pin the map to a named area (UWA Campus,
Eglinton) instead of fitting to every visible vehicle, and the "All areas"
chip that puts that back. Driven in a real browser.

As in test_rider_mobile_view.py, these run against the installed Google
Chrome, or a Playwright-managed Chromium if one is available, and the module
skips without either.
"""

from __future__ import annotations
import shutil
import threading
from datetime import datetime, timedelta, timezone

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
"""

ON_CAMPUS = (-31.9813, 115.8160)
# A real point along nUWAy 2's Eglinton route (therevproject.com/tracking/nuway2.php).
IN_EGLINTON = (-31.594105, 115.671642)

POSITIONS_HEADER = "timestamp,timestamp_unix,latitude,longitude,altitude,heading,speed_mps,gps_status,position_covariance_type,battery_percent\n"


def position_row(lat, lon, seconds_ago=30):
    when = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return f"{when.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z,0,{lat},{lon},0,0,0,0,2,\n"


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
def server(tmp_path):
    for name in ("app.yaml", "vehicles.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    (tmp_path / "stops.yaml").write_text(STOPS_YAML, encoding="utf-8")

    # One vehicle on campus, one in Eglinton -- a deterministic stand-in for
    # the real fleet (config/app.yaml's data.directory resolves against the
    # real project root, not this tmp config dir, so it is overridden here).
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "positions_1.csv").write_text(POSITIONS_HEADER + position_row(*ON_CAMPUS), encoding="utf-8")
    (data_dir / "positions_2.csv").write_text(POSITIONS_HEADER + position_row(*IN_EGLINTON), encoding="utf-8")

    app_yaml = (tmp_path / "app.yaml").read_text(encoding="utf-8")
    app_yaml = app_yaml.replace("directory: data/sample", f"directory: {data_dir}")
    (tmp_path / "app.yaml").write_text(app_yaml, encoding="utf-8")

    httpd = werkzeug_serving.make_server("127.0.0.1", 0, create_app(tmp_path), threaded=True)
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
    page.wait_for_selector(".bus-marker")
    page.wait_for_timeout(300)
    yield page
    context.close()


def distance(page, lat, lng):
    centre = page.evaluate("map.getCenter()")
    return ((centre["lat"] - lat) ** 2 + (centre["lng"] - lng) ** 2) ** 0.5


def select_area(page, area_id):
    page.click(f'#area-filter-chips .chip[data-area="{area_id}"]')
    page.wait_for_timeout(300)


def active_area(page):
    return page.locator("#area-filter-chips .chip.is-active").get_attribute("data-area")


def test_area_chips_are_offered(page):
    assert page.locator("#area-filter-chips .chip").all_inner_texts() == ["All areas", "UWA Campus", "Eglinton"]
    assert active_area(page) == "all"


def test_fleet_default_spans_both_vehicles(page):
    # On campus and in Eglinton are ~45km apart; fit to both sits well away
    # from either -- unlike a pin to just one of them, checked below.
    assert distance(page, *ON_CAMPUS) > 0.05
    assert distance(page, *IN_EGLINTON) > 0.05


def test_uwa_campus_pins_to_the_configured_stops(page):
    select_area(page, "uwa")
    assert distance(page, -31.9797, 115.8178) < 0.01  # midpoint of the two configured stops
    assert distance(page, *IN_EGLINTON) > 0.05


def test_eglinton_pins_to_eglinton(page):
    select_area(page, "eglinton")
    assert distance(page, *IN_EGLINTON) < 0.02
    assert distance(page, -31.9797, 115.8178) > 0.05


def test_all_areas_restores_the_fleet_view_immediately(page):
    """
    The bug this guards: unpinning used to leave the map exactly where the
    pin had it until some unrelated later poll happened to trigger a fit.
    """
    select_area(page, "eglinton")
    eglinton_zoom = page.evaluate("map.getZoom()")

    select_area(page, "all")

    assert active_area(page) == "all"
    assert page.evaluate("map.getZoom()") != eglinton_zoom
    assert distance(page, *ON_CAMPUS) > 0.05
    assert distance(page, *IN_EGLINTON) > 0.05


def test_area_selection_is_remembered_across_a_reload(page):
    select_area(page, "eglinton")
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".bus-marker")
    page.wait_for_timeout(300)
    assert active_area(page) == "eglinton"
    assert distance(page, *IN_EGLINTON) < 0.02


def test_area_filter_is_collapsible(page):
    page.click("#area-filter .filter-bar-label")
    assert page.locator("#area-filter-chips").is_hidden()
    page.click("#area-filter .filter-bar-label")
    assert page.locator("#area-filter-chips").is_visible()


# ---- Interaction with the Rider tab and Utilisation ----


def test_rider_tab_hides_area_chips_and_forces_campus(page):
    select_area(page, "eglinton")
    page.get_by_role("button", name="Rider", exact=True).click()
    page.wait_for_timeout(300)

    assert page.locator("#area-filter").is_hidden()
    assert distance(page, -31.9797, 115.8178) < 0.01  # campus, not Eglinton


def test_leaving_rider_restores_the_area_pin(page):
    select_area(page, "eglinton")
    page.get_by_role("button", name="Rider", exact=True).click()
    page.wait_for_timeout(300)
    page.get_by_role("button", name="Fleet", exact=True).click()
    page.wait_for_timeout(300)

    assert active_area(page) == "eglinton"
    assert distance(page, *IN_EGLINTON) < 0.02


def test_leaving_rider_with_no_area_selected_does_not_stay_pinned_to_campus(page):
    """
    The bug this guards: Area's select() treated "still null" as nothing to
    do, so the Rider tab's forced campus pin was never actually cleared when
    there had been no area pin to put back.
    """
    assert active_area(page) == "all"  # the default; nothing selected yet

    page.get_by_role("button", name="Rider", exact=True).click()
    page.wait_for_timeout(300)
    page.get_by_role("button", name="Fleet", exact=True).click()
    page.wait_for_timeout(300)

    assert active_area(page) == "all"
    assert distance(page, -31.9797, 115.8178) > 0.01  # not still pinned to campus


def test_utilisation_has_no_area_filter(page):
    page.get_by_role("button", name="Utilisation", exact=True).click()
    assert page.locator("#area-filter").is_hidden()
