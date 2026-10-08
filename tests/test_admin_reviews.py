"""
The admin Reviews tab (S15 follow-up) in a real browser: each review
collapsed to its ratings, Expand all, Refresh and reopening the tab, the
filters and paging.
"""

from __future__ import annotations
import shutil
import threading
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.models import Review
from backend.reviews import ReviewStore
from tests.admin_support import ADMIN_PASSWORD, ADMIN_USERNAME, write_admin_secrets


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


@pytest.fixture
def store(config_dir):
    return ReviewStore(config_dir / "admin" / "reviews.json")


def review(n, stop_id="civ-mech", safety=5, app=4, **answers):
    return Review.from_dict(
        {
            "id": f"r{n}",
            "pickup_request_id": f"p{n}",
            "stop_id": stop_id,
            "vehicle_id": "1",
            "route_id": "full-campus-loop",
            "wait_minutes": 2,
            "created_at": f"2026-10-01T{n % 24:02d}:00:00Z",
            "safety_rating": safety,
            "app_rating": app,
            **answers,
        }
    )


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


@pytest.fixture
def signed_in(browser, server):
    context = browser.new_context(timezone_id="Australia/Perth")
    page = context.new_page()
    page.goto(f"{server}/admin")
    page.fill("#login-username", ADMIN_USERNAME)
    page.fill("#login-password", ADMIN_PASSWORD)
    page.click("#btn-login")
    page.wait_for_url(f"{server}/admin")
    yield page
    context.close()


def open_reviews(page):
    page.click('.app-tab[data-tab="reviews"]')
    page.wait_for_selector("#review-updated:has-text('Updated')")


# ---- Collapsed to the ratings ----


def test_a_review_shows_its_ratings_with_the_answers_collapsed(signed_in, store):
    store.add(review(1, vehicle_behaviour="Smooth", punctuality="late"))
    open_reviews(signed_in)

    item = signed_in.locator(".review-item")
    assert "Safety 5/5" in item.locator(".review-scores").inner_text()
    assert item.locator(".review-details summary").inner_text().startswith("2 answers")
    assert item.locator(".review-answers").is_hidden()


def test_opening_a_review_shows_its_answers(signed_in, store):
    store.add(review(1, vehicle_behaviour="Smooth", punctuality="late"))
    open_reviews(signed_in)

    signed_in.click(".review-details summary")

    answers = signed_in.locator(".review-answers")
    assert answers.is_visible()
    assert "Smooth" in answers.inner_text()
    assert "Late" in answers.inner_text()  # the form's wording, not "late"


def test_a_ratings_only_review_has_nothing_to_open(signed_in, store):
    store.add(review(1))
    open_reviews(signed_in)

    assert signed_in.locator(".review-details").count() == 0
    assert signed_in.locator(".review-no-answers").inner_text() == "Ratings only"


def test_expand_all_opens_every_review_and_collapse_all_closes_them(signed_in, store):
    for n in range(3):
        store.add(review(n, comments=f"comment {n}"))
    open_reviews(signed_in)

    signed_in.click("#btn-reviews-expand")
    assert signed_in.locator(".review-details[open]").count() == 3
    assert signed_in.locator("#btn-reviews-expand").inner_text() == "Collapse all"

    signed_in.click("#btn-reviews-expand")
    assert signed_in.locator(".review-details[open]").count() == 0
    assert signed_in.locator("#btn-reviews-expand").inner_text() == "Expand all"


# ---- Refresh, and reloading each time the tab is opened ----


def test_refresh_shows_a_review_submitted_since_the_tab_was_opened(signed_in, store):
    store.add(review(1))
    open_reviews(signed_in)
    assert signed_in.locator(".review-item").count() == 1

    store.add(review(2))
    with signed_in.expect_response("**/api/reviews"):
        signed_in.click("#btn-reviews-refresh")
    # Shown long enough to see, beside a button that keeps its label (and width).
    signed_in.wait_for_selector("#review-updated:has-text('Refreshing')", timeout=1_000)
    assert signed_in.locator("#btn-reviews-refresh").inner_text() == "Refresh"
    signed_in.wait_for_function("document.querySelectorAll('.review-item').length === 2")
    assert signed_in.locator("#btn-reviews-refresh").inner_text() == "Refresh"
    assert signed_in.locator("#review-updated").inner_text().startswith("Updated ")


def test_reopening_the_tab_shows_a_review_submitted_since(signed_in, store):
    store.add(review(1))
    open_reviews(signed_in)
    assert signed_in.locator(".review-item").count() == 1

    store.add(review(2))
    with signed_in.expect_response("**/api/reviews"):
        signed_in.click('.app-tab[data-tab="reviews"]')
    signed_in.wait_for_function("document.querySelectorAll('.review-item').length === 2")
    assert signed_in.locator("#review-updated").inner_text().startswith("Updated ")


# ---- Filters and paging ----


def test_the_stop_filter_narrows_the_list_and_summary(signed_in, store):
    store.add(review(1, stop_id="civ-mech"))
    store.add(review(2, stop_id="business-school"))
    store.add(review(3, stop_id="business-school"))
    open_reviews(signed_in)

    signed_in.select_option("#review-filter-stop", "business-school")

    assert signed_in.locator(".review-item").count() == 2
    assert "2 OF 3" in signed_in.locator("#review-summary-title").inner_text()


def days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_the_date_filter_keeps_only_recent_reviews(signed_in, store):
    store.add(review(1, created_at=days_ago(0)))
    store.add(review(2, created_at=days_ago(3)))
    store.add(review(3, created_at=days_ago(20)))
    store.add(review(4, created_at=days_ago(60)))
    open_reviews(signed_in)
    assert signed_in.locator(".review-item").count() == 4

    counts = {}
    for option in ("7", "30", ""):
        signed_in.select_option("#review-filter-when", option)
        counts[option] = signed_in.locator(".review-item").count()
    assert counts == {"7": 2, "30": 3, "": 4}

    signed_in.select_option("#review-filter-when", "30")
    assert "3 OF 4" in signed_in.locator("#review-summary-title").inner_text()


def test_today_starts_at_midnight(signed_in, store):
    store.add(review(1, created_at=days_ago(0)))
    store.add(review(2, created_at=days_ago(1.5)))  # always before today's midnight
    open_reviews(signed_in)

    signed_in.select_option("#review-filter-when", "today")

    assert signed_in.locator(".review-item").count() == 1


def test_more_than_a_page_of_reviews_is_paged(signed_in, store):
    total = 23  # more than one page at any sensible REVIEW_PAGE_SIZE
    for n in range(total):
        store.add(review(n))
    open_reviews(signed_in)

    pager = signed_in.locator("#review-pager-label")
    page_size = signed_in.locator(".review-item").count()
    assert 0 < page_size < total
    assert pager.inner_text().startswith(f"1–{page_size} of {total}")
    assert signed_in.locator("#btn-reviews-prev").is_disabled()

    signed_in.click("#btn-reviews-next")
    assert pager.inner_text().startswith(f"{page_size + 1}–")
    assert not signed_in.locator("#btn-reviews-prev").is_disabled()


# ---- Rider text is shown as text, never run as HTML ----


def test_rider_text_cannot_inject_html_or_script(signed_in, store):
    store.add(review(
        1,
        vehicle_behaviour='<img src="x" onerror="window.__injected = true">',
        comments="<script>window.__injected = true</script><b>bold?</b>",
    ))
    open_reviews(signed_in)
    signed_in.click(".review-details summary")

    answers = signed_in.locator(".review-answers")
    assert '<img src="x"' in answers.inner_text()
    assert "<script>" in answers.inner_text()
    assert answers.locator("img, script, b").count() == 0
    assert signed_in.evaluate("window.__injected") is None


# ---- Low ratings ----


def test_a_rating_of_2_or_lower_is_marked_and_can_be_filtered_to(signed_in, store):
    store.add(review(1, safety=5, app=5))
    store.add(review(2, safety=2, app=4))
    store.add(review(3, safety=4, app=1))
    open_reviews(signed_in)

    low_badges = signed_in.locator(".review-score.is-low").all_inner_texts()
    assert sorted(t.replace(" ", "") for t in low_badges) == ["App1/5", "Safety2/5"]

    signed_in.check("#review-filter-low")
    assert signed_in.locator(".review-item").count() == 2
    assert "2 OF 3" in signed_in.locator("#review-summary-title").inner_text()


# ---- The vehicle filter ----


def test_the_vehicle_filter_lists_reviewed_vehicles_by_name_and_narrows_the_list(signed_in, store):
    store.add(review(1, vehicle_id="1"))
    store.add(review(2, vehicle_id="2"))
    store.add(review(3, vehicle_id="2"))
    open_reviews(signed_in)

    options = signed_in.locator("#review-filter-vehicle option").all_inner_texts()
    assert options == ["All vehicles", "nUWAy 1", "nUWAy 2"]

    signed_in.select_option("#review-filter-vehicle", "2")
    assert signed_in.locator(".review-item").count() == 2


# ---- The summary's numbers ----


def stat(page, label):
    tile = page.locator(".review-stat", has=page.locator(".review-stat-label", has_text=label))
    return tile.locator(".review-stat-value").inner_text()


def test_the_summary_averages_and_counts_what_is_shown(signed_in, store):
    store.add(review(1, safety=5, app=4, wait_minutes=1))
    store.add(review(2, safety=3, app=2, wait_minutes=2))
    store.add(review(3, safety=4, app=4, wait_minutes=6))
    open_reviews(signed_in)

    assert stat(signed_in, "Reviews") == "3"
    assert stat(signed_in, "Average safety") == "4.0 / 5"
    assert stat(signed_in, "Average app") == "3.3 / 5"
    assert stat(signed_in, "Average wait") == "3.0 min"
    assert stat(signed_in, "Rated 2 or lower") == "1"


# ---- Long answers ----


def test_a_long_answer_is_cut_short_until_read_more(signed_in, store):
    store.add(review(1, comments="word " * 100, vehicle_behaviour="Short answer"))
    open_reviews(signed_in)
    signed_in.click(".review-details summary")

    long_answer = signed_in.locator(".review-long")
    button = long_answer.locator(".review-read-more")
    assert signed_in.locator(".review-read-more").count() == 1  # only the long one
    assert button.inner_text() == "Read more"

    button.click()
    assert "is-open" in long_answer.get_attribute("class")
    assert button.inner_text() == "Show less"
    assert button.get_attribute("aria-expanded") == "true"

    button.click()
    assert button.inner_text() == "Read more"
