"""
Rider tab map framing (S11 follow-up): the map always frames the configured
campus stops while on Rider, regardless of the fleet's actual extent -- one
bus runs off campus, and fitting to it (the default, for Fleet) would zoom
the rider's view out to include a point nobody picking a stop needs to see.
Driven in a real browser.

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

# Fremantle: far enough from UWA Crawley that a fit including it is
# unmistakably different from one framing just the campus stops above.
OFF_CAMPUS = (-32.0569, 115.7439)
ON_CAMPUS = (-31.9813, 115.8160)

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

    # config/app.yaml's data.directory is resolved against the real project
    # root, not this tmp config dir, so it is overridden here with an
    # absolute path to data made up for this test (vehicle 1 off campus,
    # vehicle 2 on it) rather than the real, entirely-on-campus sample data.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "positions_1.csv").write_text(POSITIONS_HEADER + position_row(*OFF_CAMPUS), encoding="utf-8")
    (data_dir / "positions_2.csv").write_text(POSITIONS_HEADER + position_row(*ON_CAMPUS), encoding="utf-8")

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
    page.wait_for_timeout(300)  # let the initial fitBounds settle
    yield page
    context.close()


def distance_from_campus(page):
    """
    Degrees between the map's current centre and UWA Crawley: small while
    framing just the campus stops, large while framing the off-campus bus
    too (the two configured stops above are well under 0.01 apart from it).
    """
    centre = page.evaluate("map.getCenter()")
    return ((centre["lat"] + 31.98) ** 2 + (centre["lng"] - 115.816) ** 2) ** 0.5


def go_to_rider(page):
    page.get_by_role("button", name="Rider", exact=True).click()
    page.wait_for_timeout(300)


def go_to_fleet(page):
    page.get_by_role("button", name="Fleet", exact=True).click()
    page.wait_for_timeout(300)


def test_fleet_zooms_out_to_include_the_off_campus_bus(page):
    assert distance_from_campus(page) > 0.01


def test_rider_tab_frames_the_campus_regardless(page):
    go_to_rider(page)
    assert distance_from_campus(page) < 0.01


def test_rider_tab_zoom_is_tighter_than_fleets(page):
    fleet_zoom = page.evaluate("map.getZoom()")
    go_to_rider(page)
    assert page.evaluate("map.getZoom()") > fleet_zoom


def test_leaving_rider_restores_the_fleet_extent(page):
    go_to_rider(page)
    go_to_fleet(page)
    assert distance_from_campus(page) > 0.01
