"""
Stops on the map (S07), driven in a real browser.

Playwright cannot download its own Chromium on macOS 13, so these run against
the Google Chrome already installed. Without either, the whole module skips
and the rest of the suite is unaffected.
"""

from __future__ import annotations
import shutil
import threading

import pytest

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
werkzeug_serving = pytest.importorskip("werkzeug.serving")

# north and south share 'shared'; 'orphan' is on neither.
STOPS_YAML = """
stops:
  - id: north-end
    name: North End
    latitude: -31.9790
    longitude: 115.8183
  - id: shared
    name: Shared Stop
    latitude: -31.9807
    longitude: 115.8172
  - id: south-end
    name: South End
    latitude: -31.9855
    longitude: 115.8208
  - id: orphan
    name: Orphan Stop
    latitude: -31.9830
    longitude: 115.8187

routes:
  - id: north
    name: North Route
    colour: "#d4741f"
    stops: [north-end, shared]
  - id: south
    name: South Route
    colour: "#2f7d8f"
    stops: [shared, south-end]
"""

ON_ROUTE_COLOUR = "#d4741f"
STOP_PATHS = ".leaflet-pane.leaflet-stops-pane path"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(channel="chrome")
        except Exception as exc:  # noqa: BLE001 - any launch failure means no browser to test in
            pytest.skip(f"Google Chrome unavailable: {exc}")
        yield launched
        launched.close()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """
    The real app on a spare port, with a stops.yaml the tests control.
    """
    config_dir = tmp_path_factory.mktemp("config")
    for name in ("app.yaml", "vehicles.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, config_dir / name)
    (config_dir / "stops.yaml").write_text(STOPS_YAML, encoding="utf-8")

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
    # The stops are fetched after load, so wait for them rather than sleeping.
    page.wait_for_selector(".stop-label")
    yield page
    context.close()


def labels(page, selector=".stop-label"):
    return sorted(page.locator(selector).all_text_contents())


def select_route(page, label):
    page.get_by_role("button", name=label, exact=True).click()


# ---- S07.1 markers ----


def test_every_configured_stop_is_drawn(page):
    assert page.locator(STOP_PATHS).count() == 4


def test_each_stop_shows_its_name(page):
    assert labels(page) == ["North End", "Orphan Stop", "Shared Stop", "South End"]


def test_stops_are_drawn_under_the_vehicles(page):
    panes = page.evaluate(
        "() => ({ stops: getComputedStyle(document.querySelector('.leaflet-stops-pane')).zIndex,"
        " overlay: getComputedStyle(document.querySelector('.leaflet-overlay-pane')).zIndex })"
    )
    assert int(panes["stops"]) < int(panes["overlay"])


def test_labels_hide_when_zoomed_out(page):
    page.evaluate("() => map.setZoom(13)")
    page.wait_for_selector(".stop-label", state="hidden")
    page.evaluate("() => map.setZoom(16)")
    page.wait_for_selector(".stop-label", state="visible")


def test_toggle_hides_and_restores_the_stops(page):
    # The checkbox itself is covered by the switch graphic, as it is for a
    # user: the label is what gets clicked.
    switch = page.locator("label.layer-toggle-row", has_text="Stops")

    switch.click()
    assert page.locator(STOP_PATHS).count() == 0

    switch.click()
    assert page.locator(STOP_PATHS).count() == 4


# ---- S07.2 route selector and highlighting ----


def test_route_selector_lists_every_route(page):
    assert labels(page, "#route-filter-chips .chip") == ["All routes", "North Route", "South Route"]


def test_no_route_selected_draws_every_stop_the_same(page):
    fills = page.locator(STOP_PATHS).evaluate_all("paths => paths.map(p => p.getAttribute('fill'))")
    assert set(fills) == {"#ffffff"}
    assert page.locator(".stop-label.is-dimmed").count() == 0


def test_selected_route_stops_are_distinct_from_the_rest(page):
    select_route(page, "North Route")

    highlighted = page.locator(f'{STOP_PATHS}[fill="{ON_ROUTE_COLOUR}"]')
    assert highlighted.count() == 2  # north-end and shared

    assert labels(page, ".stop-label.is-dimmed") == ["Orphan Stop", "South End"]


def test_a_stop_on_two_routes_is_highlighted_on_each(page):
    for route in ("North Route", "South Route"):
        select_route(page, route)
        assert "Shared Stop" not in labels(page, ".stop-label.is-dimmed")


def test_all_routes_clears_the_highlighting(page):
    select_route(page, "South Route")
    assert page.locator(".stop-label.is-dimmed").count() > 0

    select_route(page, "All routes")
    assert page.locator(".stop-label.is-dimmed").count() == 0


def test_selection_survives_a_reload(page, server):
    select_route(page, "South Route")
    page.reload()
    page.wait_for_selector(".stop-label")
    assert page.locator("#route-filter-chips .chip.is-active").text_content() == "South Route"


# ---- S07.3 popup ----


def open_popup(page, index):
    page.locator(STOP_PATHS).nth(index).click()
    page.wait_for_selector(".stop-popup")
    return page.locator(".stop-popup").text_content()


def test_popup_shows_the_stop_name_and_its_routes(page):
    text = open_popup(page, 1)  # shared, in file order
    assert "Shared Stop" in text
    assert "North Route" in text and "South Route" in text


def test_popup_for_a_stop_on_one_route(page):
    text = open_popup(page, 0)  # north-end
    assert "North End" in text
    assert "North Route" in text and "South Route" not in text


def test_popup_says_when_a_stop_is_on_no_route(page):
    assert "Not on any route" in open_popup(page, 3)  # orphan
