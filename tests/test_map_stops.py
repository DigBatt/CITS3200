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
    # Their names only show on hover, so it is the markers that are waited for.
    page.wait_for_function("stopMarkers.size > 0")
    yield page
    context.close()


def labels(page, selector=".stop-label"):
    return sorted(page.locator(selector).all_text_contents())


def select_route(page, label):
    page.get_by_role("button", name=label, exact=True).click()


def layer_switch(page, label):
    """
    One of the layer chips on the map. Its checkbox is not seen, as it is not
    by a user: the chip is what gets clicked.
    """
    return page.locator("#map-layers label.map-chip", has_text=label)


# ---- S07.1 markers ----


def test_every_configured_stop_is_drawn(page):
    assert page.locator(STOP_PATHS).count() == 4


def test_stops_are_drawn_under_the_vehicles(page):
    panes = page.evaluate(
        "() => ({ stops: getComputedStyle(document.querySelector('.leaflet-stops-pane')).zIndex,"
        " overlay: getComputedStyle(document.querySelector('.leaflet-overlay-pane')).zIndex })"
    )
    assert int(panes["stops"]) < int(panes["overlay"])


def test_layer_chips_are_on_the_map_and_off_by_default(page):
    for label in ("Focus routes", "Full colour"):
        chip = layer_switch(page, label)
        assert chip.is_visible()
        assert not chip.locator("input").is_checked()


def test_a_layer_chip_turns_blue_while_on(page):
    chip = layer_switch(page, "Full colour")
    background = "chip => getComputedStyle(chip).backgroundColor"
    off = chip.evaluate(background)

    chip.click()
    assert chip.locator("input").is_checked()
    assert chip.evaluate(background) == "rgb(0, 48, 135)"  # UWA blue, css/tokens.css

    chip.click()
    assert chip.evaluate(background) == off


def test_layer_chips_are_hidden_in_3d(page):
    page.locator("label.map-mode").click()
    assert page.locator("#map-layers").is_hidden()

    page.locator("label.map-mode").click()
    assert page.locator("#map-layers").is_visible()


def test_layer_chips_are_hidden_on_the_rider_tab(page):
    page.locator("#app-tabs .app-tab", has_text="Rider").click()
    assert page.locator("#map-layers").is_hidden()

    page.locator("#app-tabs .app-tab", has_text="Fleet").click()
    assert page.locator("#map-layers").is_visible()


def test_focus_routes_fades_the_trails_and_shows_the_route_line(page):
    # The panes' own opacity, as set, not as computed: computed, it would read
    # partway through the 200ms fade.
    opacities = (
        "() => Object.fromEntries(['trails', 'stopRings', 'routes', 'stops'].map("
        "name => [name, document.querySelector(`.leaflet-${name}-pane`).style.opacity]))"
    )
    switch = layer_switch(page, "Focus routes")

    # Off by default: trails and rings at full strength, no route line.
    assert page.evaluate(opacities) == {"trails": "", "stopRings": "", "routes": "0", "stops": ""}

    switch.click()
    assert page.evaluate(opacities) == {"trails": "0.65", "stopRings": "0.65", "routes": "", "stops": ""}
    assert page.locator(STOP_PATHS).count() == 4

    switch.click()
    assert page.evaluate(opacities) == {"trails": "", "stopRings": "", "routes": "0", "stops": ""}


def test_focus_shows_the_selected_routes_line_and_keeps_the_stops(page):
    select_route(page, "North Route")
    layer_switch(page, "Focus routes").click()

    assert page.locator(".leaflet-routes-pane path.planned-route-path").count() > 0
    assert page.locator(STOP_PATHS).count() == 4


def test_full_colour_switch_turns_the_basemap_tint_off_and_on(page):
    tint = "() => getComputedStyle(document.querySelector('.leaflet-tile-pane')).filter"
    switch = layer_switch(page, "Full colour")

    assert page.evaluate(tint) != "none"  # muted by default

    switch.click()
    assert page.evaluate(tint) == "none"

    switch.click()
    assert page.evaluate(tint) != "none"


# ---- S07.2 route selector and highlighting ----


def test_route_selector_lists_every_route(page):
    assert labels(page, "#route-filter-chips .chip") == ["All routes", "North Route", "South Route"]


def test_no_route_selected_draws_every_stop_the_same(page):
    fills = page.locator(STOP_PATHS).evaluate_all("paths => paths.map(p => p.getAttribute('fill'))")
    assert set(fills) == {"#ffffff"}
    assert page.locator(".stop-label.is-dimmed").count() == 0


def test_a_stop_on_two_routes_is_highlighted_on_each(page):
    for route in ("North Route", "South Route"):
        select_route(page, route)
        assert "shared" not in labels(page, ".stop-label.is-dimmed")


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
