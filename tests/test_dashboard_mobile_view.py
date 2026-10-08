"""
The dashboard on a phone (css/dashboard.css, "A phone"), in a real browser at
390px wide: the header keeps one row per kind of thing, and the rider's
fields are large enough that iPhone Safari does not zoom in on them. At
desktop width, neither applies.

Chrome stands in for the phone here. iPhone Safari zooming in on a field
under 16px only happens on a real iPhone, so this checks the CSS rule that
prevents it, not Safari itself.
"""

from __future__ import annotations
import shutil
import threading

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1400, "height": 900}

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


def open_dashboard(browser, server, viewport):
    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    page.goto(server)
    page.wait_for_function("stopMarkers.size > 0")  # the stops have loaded
    return context, page


@pytest.fixture
def phone(browser, server):
    context, page = open_dashboard(browser, server, PHONE)
    yield page
    context.close()


@pytest.fixture
def desktop(browser, server):
    context, page = open_dashboard(browser, server, DESKTOP)
    yield page
    context.close()


def top(page, selector):
    return page.locator(selector).first.evaluate("e => e.getBoundingClientRect().top")


def show_review_form(page):
    """
    The review form sits in the "You're on board!" panel, shown only after a
    pickup; show both so every review field can be measured.
    """
    page.get_by_role("button", name="Rider", exact=True).click()
    page.evaluate("""() => {
        document.getElementById('rider-collected').hidden = false;
        document.getElementById('rider-review-form').hidden = false;
    }""")
    assert page.locator("textarea[name=comments]").is_visible()


def field_sizes(page):
    return page.evaluate(f"""() => [...document.querySelectorAll('{FIELDS}')]
        .filter(e => e.offsetParent !== null)
        .map(e => [e.id || e.name, parseFloat(getComputedStyle(e).fontSize)])""")


# ---- The header: one row per kind of thing ----


def test_phone_header_puts_admin_beside_the_brand_then_tabs_then_calendar(phone):
    # Before, Admin wrapped onto the calendar's row.
    brand = top(phone, ".app-header-brand")
    assert abs(top(phone, ".admin-link") - brand) < 12, "Admin is not on the brand's row"
    assert top(phone, "#app-tabs") > brand + 12, "the tabs are not below the brand"
    assert top(phone, ".period-picker") > top(phone, "#app-tabs") + 12, "the calendar is not below the tabs"


def test_phone_header_does_not_widen_the_page(phone):
    width = phone.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert width[0] == width[1]


# ---- No zoom on tapping a rider field ----


def test_rider_fields_are_at_least_16px_on_a_phone(phone):
    # Under 16px, iPhone Safari zooms the page in when a field is tapped.
    show_review_form(phone)
    assert [name for name, size in field_sizes(phone) if size < 16] == []


# ---- Desktop is left alone ----


def test_desktop_keeps_its_field_size_and_header(desktop):
    show_review_form(desktop)
    sizes = dict(field_sizes(desktop))
    assert sizes["comments"] < 16, "the phone's 16px rule leaked onto desktop"
    assert abs(top(desktop, "#app-tabs") - top(desktop, ".app-header-brand")) < 12, "the desktop header no longer has the tabs beside the brand"
