"""
Each bus's latest position is drawn as its number in a circle of its colour,
driven in a real browser against the sample data (buses 1 and 2 report on
the day the page opens on).

As in test_rider_mobile_view.py, these run against the installed Google
Chrome, or a Playwright-managed Chromium if one is available, and the module
skips without either.
"""

from __future__ import annotations
import shutil
import threading

import pytest

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
werkzeug_serving = pytest.importorskip("werkzeug.serving")


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
    for name in ("app.yaml", "vehicles.yaml", "stops.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
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
    yield page
    context.close()


def marker_numbers(page):
    return page.locator(".bus-marker").all_text_contents()


def test_one_numbered_marker_per_bus_with_positions(page):
    assert sorted(marker_numbers(page)) == ["1", "2"]


def test_marker_is_the_buses_colour(page):
    # nUWAy 1 is #d4741f in config/vehicles.yaml.
    colour = page.locator(".bus-marker span", has_text="1").evaluate("span => getComputedStyle(span).backgroundColor")
    assert colour == "rgb(212, 116, 31)"


def test_markers_are_drawn_above_the_stop_labels(page):
    z_index = lambda pane: int(page.locator(f".leaflet-{pane}-pane").evaluate("pane => getComputedStyle(pane).zIndex"))
    assert z_index("buses") > z_index("tooltip")


def test_selecting_a_bus_leaves_only_its_marker(page):
    with page.expect_response(lambda response: "/api/positions" in response.url and "vehicles=2" in response.url):
        page.click('#vehicle-filter-chips .chip[data-vehicle="2"]')
    page.wait_for_function("document.querySelectorAll('.bus-marker').length === 1")
    assert marker_numbers(page) == ["2"]


def test_clicking_a_marker_still_opens_its_popup(page):
    page.locator(".bus-marker", has_text="2").click()
    assert page.locator(".leaflet-popup-content").text_content().startswith("nUWAy 2 — ")
