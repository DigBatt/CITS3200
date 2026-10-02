"""
Selecting several vehicles at once (e.g. 1 + 2) from the vehicle chips or the
fleet panel rows, driven in a real browser.

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

ALL_IDS = ["1", "2", "3", "4"]  # config/vehicles.yaml


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
    page.wait_for_selector('#vehicle-filter-chips .chip[data-vehicle="1"]')
    yield page
    context.close()


def click_chip(page, vehicle_id):
    page.click(f'#vehicle-filter-chips .chip[data-vehicle="{vehicle_id}"]')


def active_chips(page):
    return page.locator("#vehicle-filter-chips .chip.is-active").evaluate_all(
        "chips => chips.map(chip => chip.dataset.vehicle)"
    )


def positions_request_after(page, action):
    """The /api/positions URL that `action` sets off."""
    with page.expect_request(lambda request: "/api/positions" in request.url) as request:
        action()
    return request.value.url


def test_two_chips_select_both(page):
    click_chip(page, "1")
    click_chip(page, "2")
    assert active_chips(page) == ["1", "2"]


def test_both_vehicles_are_asked_for(page):
    click_chip(page, "1")
    url = positions_request_after(page, lambda: click_chip(page, "2"))
    assert "vehicles=1%2C2" in url


def test_the_order_picked_does_not_change_the_request(page):
    click_chip(page, "2")
    url = positions_request_after(page, lambda: click_chip(page, "1"))
    assert "vehicles=1%2C2" in url


def test_clicking_a_selected_chip_again_takes_it_out(page):
    click_chip(page, "1")
    click_chip(page, "2")
    click_chip(page, "2")
    assert active_chips(page) == ["1"]


def test_taking_out_the_last_one_is_the_whole_fleet(page):
    click_chip(page, "1")
    click_chip(page, "1")
    assert active_chips(page) == ["all"]


def test_picking_every_vehicle_is_the_whole_fleet(page):
    for vehicle_id in ALL_IDS[:-1]:
        click_chip(page, vehicle_id)
    url = positions_request_after(page, lambda: click_chip(page, ALL_IDS[-1]))
    assert active_chips(page) == ["all"]
    assert "vehicles=" not in url


def test_all_vehicles_clears_a_selection(page):
    click_chip(page, "1")
    click_chip(page, "2")
    click_chip(page, "all")
    assert active_chips(page) == ["all"]


def test_fleet_rows_add_and_take_out_vehicles_too(page):
    page.click('#vehicle-list [data-vehicle-row="1"]')
    page.click('#vehicle-list [data-vehicle-row="3"]')
    assert active_chips(page) == ["1", "3"]
    assert page.locator("#vehicle-list .vehicle-row.is-selected").count() == 2

    page.click('#vehicle-list [data-vehicle-row="1"]')
    assert active_chips(page) == ["3"]


def test_leaving_rider_restores_several_vehicles(page):
    click_chip(page, "1")
    click_chip(page, "2")
    page.get_by_role("button", name="Rider", exact=True).click()
    assert active_chips(page) == ["all"]
    page.get_by_role("button", name="Fleet", exact=True).click()
    assert active_chips(page) == ["1", "2"]


def test_utilisation_names_the_vehicles_it_pooled(page):
    click_chip(page, "1")
    with page.expect_response(lambda response: "/api/metrics" in response.url and "vehicles=1%2C2" in response.url):
        click_chip(page, "2")
    page.get_by_role("button", name="Utilisation", exact=True).click()
    assert page.text_content("#util-scope").startswith("nUWAy 1 + nUWAy 2 · combined")
    assert page.text_content("#util-table .util-table-average .util-table-name") == "Selection total"
