"""
Rider view (S08, S15): the stop picker, waiting for pickup, and the review
prompt once collected — driven in a real browser.

Playwright cannot download its own Chromium on macOS 13, so these run against
the Google Chrome already installed, or a Playwright-managed Chromium if one
is available. Without either, the whole module skips and the rest of the
suite is unaffected.
"""

from __future__ import annotations
import shutil
import threading
from datetime import datetime, timezone

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.models import Review

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

STOP_PATHS = ".leaflet-pane.leaflet-stops-pane path"


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

    # Reviews (S15 follow-up) are written here; point it at this test's own
    # directory rather than the real storage.directory the copied app.yaml
    # names, same as tests/test_downtime.py.
    app_config = yaml.safe_load((tmp_path / "app.yaml").read_text(encoding="utf-8"))
    app_config["storage"] = {"directory": str(tmp_path / "admin")}
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")

    return tmp_path


@pytest.fixture
def app(config_dir):
    return create_app(config_dir)


@pytest.fixture
def server(app):
    httpd = werkzeug_serving.make_server("127.0.0.1", 0, app, threaded=True)
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
    # The stops are drawn once fetched; their names only show on hover.
    page.wait_for_function("stopMarkers.size > 0")
    page.get_by_role("button", name="Rider", exact=True).click()
    page.wait_for_selector("#rider-stop-select:not([disabled])")
    yield page
    context.close()


def pick_stop(page, stop_id):
    page.select_option("#rider-stop-select", stop_id)


# ---- S15.1: the picker shows stop ids, not names ----


def test_picker_options_are_stop_ids(page):
    options = page.locator("#rider-stop-select option").all_inner_texts()
    assert "reid-library" in options
    assert "civ-mech" in options
    assert "Reid Library" not in options


# ---- S15.2: picking a stop declutters the map and opens its popup ----


def test_picking_a_stop_hides_every_other_stop(page):
    assert page.locator(STOP_PATHS).count() == 2

    pick_stop(page, "reid-library")

    assert page.locator(f"{STOP_PATHS}.is-hidden-stop").count() == 1
    assert page.locator(f"{STOP_PATHS}:not(.is-hidden-stop)").count() == 1


def test_picking_a_stop_opens_its_popup(page):
    pick_stop(page, "civ-mech")
    page.wait_for_selector(".stop-popup")
    assert "civ-mech" in page.locator(".stop-popup").text_content()


def test_leaving_the_rider_tab_restores_every_stop(page):
    pick_stop(page, "reid-library")
    assert page.locator(f"{STOP_PATHS}.is-hidden-stop").count() == 1

    page.get_by_role("button", name="Fleet", exact=True).click()
    assert page.locator(f"{STOP_PATHS}.is-hidden-stop").count() == 0


# ---- S08.4/S15.3: request, wait, cancel ----


def test_requesting_pickup_shows_the_waiting_view(page):
    pick_stop(page, "reid-library")
    page.click("#rider-request-button")

    page.wait_for_selector("#rider-waiting:not([hidden])")
    assert page.locator("#rider-waiting-stop").text_content() == "reid-library"
    assert page.locator("#rider-picker").is_hidden()


def test_cancelling_returns_to_the_picker(page):
    pick_stop(page, "reid-library")
    page.click("#rider-request-button")
    page.wait_for_selector("#rider-waiting:not([hidden])")

    page.click("#rider-cancel-button")

    page.wait_for_selector("#rider-picker:not([hidden])")
    assert page.locator("#rider-waiting").is_hidden()
    assert "Cancelled" in page.locator("#rider-status").text_content()


# ---- S15.4: the review prompt appears once the operator collects the stop ----


def collect(app, stop_id):
    # Simulate the operator's "picked up" action (S10) directly on the same
    # in-process store the running server reads, rather than needing an admin
    # sign-in just to drive this browser test.
    app.config["PICKUP_REQUEST_STORE"].collect(stop_id, "1", "campus-loop", datetime.now(timezone.utc))


def request_and_collect(page, app, stop_id="reid-library"):
    pick_stop(page, stop_id)
    page.click("#rider-request-button")
    page.wait_for_selector("#rider-waiting:not([hidden])")
    collect(app, stop_id)
    page.wait_for_selector("#rider-collected:not([hidden])", timeout=10_000)


def test_review_button_appears_once_collected(page, app):
    request_and_collect(page, app)
    assert page.locator("#rider-waiting").is_hidden()


def test_waiting_message_is_cleared_once_collected(page, app):
    pick_stop(page, "reid-library")
    page.click("#rider-request-button")
    page.wait_for_selector("#rider-waiting:not([hidden])")
    assert "waiting" in page.locator("#rider-status").text_content()

    collect(app, "reid-library")
    page.wait_for_selector("#rider-collected:not([hidden])", timeout=10_000)
    assert page.locator("#rider-status").is_hidden()


def test_review_button_reveals_the_form(page, app):
    request_and_collect(page, app)

    page.click("#rider-review-button")

    assert page.locator("#rider-review-button").is_hidden()
    assert page.locator("#rider-review-form").is_visible()


def test_skipping_the_review_returns_to_the_picker(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")

    page.click("#rider-review-skip")

    page.wait_for_selector("#rider-picker:not([hidden])")
    assert page.locator("#rider-collected").is_hidden()


def rate(page, field, value):
    page.check(f'.review-rating[data-rating-for="{field}"] input[value="{value}"]')


def test_submitting_a_review_returns_to_the_picker(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")

    rate(page, "safety_rating", 5)
    rate(page, "app_rating", 4)
    page.click("#rider-review-submit")

    page.wait_for_selector("#rider-picker:not([hidden])", timeout=5_000)
    assert page.locator("#rider-collected").is_hidden()
    assert "Thanks" in page.locator("#rider-status").text_content()


# ---- Missing ratings are shown in red under each one ----


def rating_error(page, field):
    return page.locator(f'.review-rating[data-rating-for="{field}"] + .review-error')


def test_submitting_without_ratings_marks_both_and_sends_nothing(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/api/reviews" in r.url else None)

    page.click("#rider-review-submit")

    assert rating_error(page, "safety_rating").is_visible()
    assert rating_error(page, "app_rating").is_visible()
    assert page.locator("#rider-review-form").is_visible()
    assert sent == []


def test_choosing_a_rating_clears_its_error_only(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    page.click("#rider-review-submit")

    rate(page, "safety_rating", 4)

    assert rating_error(page, "safety_rating").is_hidden()
    assert rating_error(page, "app_rating").is_visible()


def test_review_submits_once_both_ratings_are_chosen_after_an_error(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    page.click("#rider-review-submit")

    rate(page, "safety_rating", 4)
    rate(page, "app_rating", 5)
    page.click("#rider-review-submit")

    page.wait_for_selector("#rider-picker:not([hidden])", timeout=5_000)
    assert "Thanks" in page.locator("#rider-status").text_content()


# ---- "Not today", and not asking again on reload ----


def reload_rider_view(page):
    # Reload and wait for the view's own check of the rider's latest request,
    # which is what decides whether the review is offered again.
    with page.expect_response("**/api/pickup-requests/mine"):
        page.reload()
    page.get_by_role("button", name="Rider", exact=True).click()
    page.wait_for_timeout(300)  # let the response be acted on


def test_not_today_returns_to_the_picker(page, app):
    request_and_collect(page, app)

    page.click("#rider-review-decline")

    page.wait_for_selector("#rider-picker:not([hidden])")
    assert page.locator("#rider-collected").is_hidden()


def test_opening_the_form_hides_not_today(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    assert page.locator("#rider-review-decline").is_hidden()


def test_review_is_offered_again_on_reload_if_neither_reviewed_nor_declined(page, app):
    request_and_collect(page, app)
    page.reload()
    page.get_by_role("button", name="Rider", exact=True).click()
    page.wait_for_selector("#rider-collected:not([hidden])", timeout=10_000)


def test_declined_review_is_not_offered_again_on_reload(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-decline")

    reload_rider_view(page)
    assert page.locator("#rider-collected").is_hidden()
    assert page.locator("#rider-picker").is_visible()


def test_submitted_review_is_not_offered_again_on_reload(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    rate(page, "safety_rating", 5)
    rate(page, "app_rating", 4)
    page.click("#rider-review-submit")
    page.wait_for_selector("#rider-picker:not([hidden])", timeout=5_000)

    reload_rider_view(page)
    assert page.locator("#rider-collected").is_hidden()


# ---- The comment boxes: 1000 characters, with a counter ----

COMMENT_BOXES = ("vehicle_behaviour", "obstacle_interaction", "app_comment", "comments")


def counter(page, field):
    return page.locator(f'textarea[name="{field}"] + .review-count')


def test_every_comment_box_is_limited_to_1000_characters(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    for field in COMMENT_BOXES:
        assert page.locator(f'textarea[name="{field}"]').get_attribute("maxlength") == "1000"
        assert counter(page, field).inner_text() == "0 / 1000"


def test_the_counter_counts_and_turns_red_at_the_limit(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    box = page.locator('textarea[name="comments"]')

    box.fill("hello")
    assert counter(page, "comments").inner_text() == "5 / 1000"
    assert "is-full" not in counter(page, "comments").get_attribute("class")

    box.fill("a" * 1000)
    assert counter(page, "comments").inner_text() == "1000 character limit reached"
    assert "is-full" in counter(page, "comments").get_attribute("class")


def test_the_counter_starts_again_at_0_for_the_next_review(page, app):
    request_and_collect(page, app)
    page.click("#rider-review-button")
    page.locator('textarea[name="comments"]').fill("first trip")
    rate(page, "safety_rating", 5)
    rate(page, "app_rating", 5)
    page.click("#rider-review-submit")
    page.wait_for_selector("#rider-picker:not([hidden])", timeout=5_000)

    request_and_collect(page, app)
    page.click("#rider-review-button")
    assert counter(page, "comments").inner_text() == "0 / 1000"


# ---- A pickup already reviewed elsewhere (another tab or device) ----


def test_a_second_review_of_the_same_pickup_shows_why_it_was_refused(page, app):
    request_and_collect(page, app)
    pickup_id = page.evaluate("fetch('/api/pickup-requests/mine').then(r => r.json()).then(b => b.request.id)")
    # The same pickup reviewed from another tab in the meantime.
    app.config["REVIEW_STORE"].add(Review.from_dict({
        "id": "from-another-tab", "pickup_request_id": pickup_id, "stop_id": "reid-library",
        "created_at": "2026-10-01T00:00:00Z", "safety_rating": 5, "app_rating": 5,
    }))

    page.click("#rider-review-button")
    rate(page, "safety_rating", 3)
    rate(page, "app_rating", 3)
    page.click("#rider-review-submit")

    page.wait_for_selector("#rider-status:has-text('already been reviewed')", timeout=5_000)
    assert page.locator("#rider-review-form").is_visible()  # nothing typed is lost
    assert [r.id for r in app.config["REVIEW_STORE"].list()] == ["from-another-tab"]
