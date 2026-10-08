"""
The admin page on a phone (css/admin.css, "A phone"), in a real browser at
390px wide: every tab fits the screen, the header keeps one row per kind of
thing, fields are large enough that iPhone Safari does not zoom in on them,
and date fields stay inside their cards. And at desktop width, none of it
applies.

Chrome stands in for the phone here. The two iPhone Safari behaviours behind
these fixes (zooming in on a field under 16px, and drawing date fields wider
than their box) only happen on a real iPhone, so these check the CSS rules
that prevent them, not Safari itself.
"""

from __future__ import annotations
import shutil
import threading

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from tests.admin_support import ADMIN_PASSWORD, ADMIN_USERNAME, write_admin_secrets

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1400, "height": 900}
TABS = ("operator", "figures", "downtime", "schedule", "routes", "snapshots", "reviews")

# Every text box and dropdown; checkboxes, radios and sliders have no text.
FIELDS = "input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=hidden]), select, textarea"


@pytest.fixture
def config_dir(tmp_path):
    """
    The real config with storage pointed into this test's directory.
    """
    for name in ("app.yaml", "vehicles.yaml", "stops.json"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    app_config = yaml.safe_load((tmp_path / "app.yaml").read_text(encoding="utf-8"))
    app_config["storage"] = {"directory": str(tmp_path / "admin")}
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")
    write_admin_secrets(tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def browser():
    """
    Chrome if installed, else Playwright's own Chromium. Skips if neither launches.
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


def open_page(browser, server, viewport, signed_in=True):
    context = browser.new_context(viewport=viewport, timezone_id="Australia/Perth")
    page = context.new_page()
    page.goto(f"{server}/admin")
    if signed_in:
        page.fill("#login-username", ADMIN_USERNAME)
        page.fill("#login-password", ADMIN_PASSWORD)
        page.click("#btn-login")
        page.wait_for_url(f"{server}/admin")
    return context, page


@pytest.fixture
def phone(browser, server):
    context, page = open_page(browser, server, PHONE)
    yield page
    context.close()


@pytest.fixture
def desktop(browser, server):
    context, page = open_page(browser, server, DESKTOP)
    yield page
    context.close()


def open_tab(page, tab):
    page.click(f'.app-tab[data-tab="{tab}"]')
    page.wait_for_selector(f"#tab-{tab}:not([hidden])")


def page_width(page):
    return page.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")


def fields_under_16px(page):
    return page.evaluate(f"""() => [...document.querySelectorAll('{FIELDS}')]
        .filter(e => e.offsetParent !== null)
        .filter(e => parseFloat(getComputedStyle(e).fontSize) < 16)
        .map(e => e.id || e.name || e.className)""")


def top(page, selector):
    return page.locator(selector).first.evaluate("e => e.getBoundingClientRect().top")


# ---- Every tab fits the screen ----


def test_no_admin_tab_scrolls_sideways_on_a_phone(phone):
    # The seven tabs used to make the page 628px wide on a 390px screen.
    for tab in TABS:
        open_tab(phone, tab)
        scroll, client = page_width(phone)
        assert scroll == client, f"{tab} tab is {scroll}px wide on a {client}px screen"


def test_the_tab_bar_scrolls_by_itself_with_every_tab_on_one_line(phone):
    tabs = phone.locator("#admin-tabs")
    assert tabs.evaluate("e => getComputedStyle(e).overflowX") == "auto"
    tops = phone.locator("#admin-tabs .app-tab").evaluate_all("els => els.map(e => e.getBoundingClientRect().top)")
    assert max(tops) - min(tops) < 1, "the tabs wrapped onto more than one line"


# ---- The header: one row per kind of thing ----


def test_header_puts_the_exits_beside_the_brand_then_tabs_then_calendar(phone):
    brand = top(phone, ".app-header-brand")
    assert abs(top(phone, 'a.btn-signout') - brand) < 12, "Return to Dashboard is not on the brand's row"
    assert abs(top(phone, "#btn-signout") - brand) < 12, "Sign out is not on the brand's row"
    assert top(phone, "#admin-tabs") > brand + 12, "the tabs are not below the brand"
    assert top(phone, ".period-picker") > top(phone, "#admin-tabs") + 12, "the calendar is not below the tabs"


def test_operator_dropdowns_are_one_per_line_with_labels_above(phone):
    # Side by side, the ROUTE label was left at the end of the vehicle row.
    vehicle = phone.locator("#vehicle-selector").bounding_box()
    route_label = phone.locator('label[for="route-selector"]').bounding_box()
    route = phone.locator("#route-selector").bounding_box()
    assert route_label["y"] >= vehicle["y"] + vehicle["height"], "the ROUTE label is beside the vehicle dropdown"
    assert route["y"] >= route_label["y"] + route_label["height"], "the route dropdown is not below its label"


# ---- No zoom on tapping a field ----


def test_sign_in_fields_are_at_least_16px_on_a_phone(browser, server):
    context, page = open_page(browser, server, PHONE, signed_in=False)
    try:
        assert fields_under_16px(page) == []
    finally:
        context.close()


def test_every_admin_field_is_at_least_16px_on_a_phone(phone):
    small = {}
    for tab in TABS:
        open_tab(phone, tab)
        if found := fields_under_16px(phone):
            small[tab] = found
    assert small == {}


# ---- Date and time fields inside their cards ----


@pytest.mark.parametrize("tab", ["downtime", "figures"])
def test_date_fields_stay_inside_their_card_on_a_phone(phone, tab):
    open_tab(phone, tab)
    # Chrome never draws them wider than their box; iPhone Safari does unless
    # its own styling is off and the field may shrink, so check that rule too.
    rules = phone.evaluate("""() => [...document.querySelectorAll(
            'input[type=date], input[type=time], input[type=datetime-local]')]
        .filter(e => e.offsetParent !== null)
        .map(e => { const c = getComputedStyle(e); return [c.appearance, c.minWidth]; })""")
    assert rules and all(rule == ["none", "0px"] for rule in rules), rules
    sticking_out = phone.evaluate("""() => [...document.querySelectorAll(
            'input[type=date], input[type=time], input[type=datetime-local]')]
        .filter(e => e.offsetParent !== null)
        .filter(e => e.getBoundingClientRect().right > e.closest('.admin-card').getBoundingClientRect().right + 0.5)
        .map(e => e.id || e.className)""")
    assert sticking_out == []


# ---- Desktop is left alone ----


def test_desktop_keeps_its_field_size_and_one_line_header(desktop):
    # The phone rules must not leak: fields keep their 13px, and the brand,
    # tabs and calendar share the first row as before.
    open_tab(desktop, "downtime")
    assert desktop.locator("#dt-reason").evaluate("e => parseFloat(getComputedStyle(e).fontSize)") < 16
    assert abs(top(desktop, "#admin-tabs") - top(desktop, ".app-header-brand")) < 12
    scroll, client = page_width(desktop)
    assert scroll == client
