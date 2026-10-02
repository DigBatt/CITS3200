"""
Reviews (S15 follow-up): backend.reviews.ReviewStore and the
POST/GET /api/reviews endpoints.
"""

from __future__ import annotations
import shutil

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR
from backend.models import Review
from backend.reviews import ReviewStore
from tests.admin_support import sign_in, write_admin_secrets


def stop(stop_id, latitude=-31.98, longitude=115.82, name=None):
    name = str(stop_id).title() if name is None else name
    return {"id": stop_id, "name": name, "latitude": latitude, "longitude": longitude}


NETWORK = {
    "stops": [stop("reid-library"), stop("civ-mech")],
    "routes": [{"id": "campus-loop", "name": "Campus loop", "stops": ["reid-library", "civ-mech"]}],
}


@pytest.fixture
def config_dir(tmp_path):
    for name in ("app.yaml", "vehicles.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    (tmp_path / "stops.yaml").write_text(yaml.safe_dump(NETWORK, sort_keys=False), encoding="utf-8")

    # Reviews are written here; point it at this test's own directory rather
    # than the real storage.directory the copied app.yaml names.
    app_config = yaml.safe_load((tmp_path / "app.yaml").read_text(encoding="utf-8"))
    app_config["storage"] = {"directory": str(tmp_path / "admin")}
    (tmp_path / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")

    write_admin_secrets(tmp_path)
    return tmp_path


@pytest.fixture
def app(config_dir):
    return create_app(config_dir)


@pytest.fixture
def client(app):
    return app.test_client()


def collected_request(client, stop_id="reid-library", vehicle_id="1", route_id="campus-loop"):
    """
    A rider's request, collected by the operator, on the rider's own test
    client cookie jar -- the shape every review needs behind it.
    """
    client.post("/api/pickup-requests", json={"stop_id": stop_id})
    sign_in(client.application.test_client()).post(
        f"/api/stops/{stop_id}/collect", json={"vehicle_id": vehicle_id, "route_id": route_id}
    )
    return client.get("/api/pickup-requests/mine").get_json()["request"]


def minimal_review_body(pickup_request_id, **overrides):
    return {"pickup_request_id": pickup_request_id, "safety_rating": 5, "app_rating": 4, **overrides}


# ---- The store ----


def test_missing_file_means_no_reviews(tmp_path):
    assert ReviewStore(tmp_path / "reviews.json").list() == []


def test_reviews_survive_a_new_store_on_the_same_file(tmp_path):
    path = tmp_path / "reviews.json"
    from datetime import datetime, timezone

    review = Review(
        id="r1",
        pickup_request_id="p1",
        stop_id="reid-library",
        vehicle_id="1",
        route_id="campus-loop",
        wait_minutes=4.5,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        safety_rating=5,
        vehicle_behaviour="smooth",
        obstacle_interaction="",
        punctuality="on_time",
        ride_duration_ok="yes",
        purpose="class",
        stop_quality="good",
        ramp_needed="no",
        app_rating=4,
        app_comment="",
        role="undergrad",
        usage_frequency="weekly",
        comments="",
    )
    ReviewStore(path).add(review)

    (reloaded,) = ReviewStore(path).list()
    assert reloaded == review


def test_corrupt_file_is_a_repository_error(tmp_path):
    from backend.repository.base import RepositoryError

    path = tmp_path / "reviews.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(RepositoryError):
        ReviewStore(path).list()


# ---- POST /api/reviews ----


def test_submitting_a_review_needs_no_login(client):
    pickup_request = collected_request(client)
    response = client.post("/api/reviews", json=minimal_review_body(pickup_request["id"]))
    assert response.status_code == 201


def test_review_is_attributed_to_the_pickups_vehicle_and_route(client):
    pickup_request = collected_request(client, vehicle_id="2", route_id="campus-loop")
    review = client.post("/api/reviews", json=minimal_review_body(pickup_request["id"])).get_json()["review"]

    assert review["stop_id"] == "reid-library"
    assert review["vehicle_id"] == "2"
    assert review["route_id"] == "campus-loop"
    assert review["wait_minutes"] is not None


def test_optional_fields_default_to_empty_string(client):
    pickup_request = collected_request(client)
    review = client.post("/api/reviews", json=minimal_review_body(pickup_request["id"])).get_json()["review"]

    assert review["vehicle_behaviour"] == ""
    assert review["comments"] == ""
    assert review["role"] == ""


def test_optional_fields_are_saved_when_given(client):
    pickup_request = collected_request(client)
    body = minimal_review_body(
        pickup_request["id"],
        vehicle_behaviour="A bit jerky braking",
        comments="More shade at the stop would help",
        role="staff",
        usage_frequency="daily",
    )
    review = client.post("/api/reviews", json=body).get_json()["review"]

    assert review["vehicle_behaviour"] == "A bit jerky braking"
    assert review["comments"] == "More shade at the stop would help"
    assert review["role"] == "staff"
    assert review["usage_frequency"] == "daily"


@pytest.mark.parametrize("overrides", [{"safety_rating": 0}, {"safety_rating": 6}, {"safety_rating": "many"}])
def test_bad_safety_rating_is_400(client, overrides):
    pickup_request = collected_request(client)
    response = client.post("/api/reviews", json=minimal_review_body(pickup_request["id"], **overrides))
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_rating"


def test_missing_app_rating_is_400(client):
    pickup_request = collected_request(client)
    body = {"pickup_request_id": pickup_request["id"], "safety_rating": 3}
    response = client.post("/api/reviews", json=body)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_rating"


def test_unknown_pickup_request_is_404(client):
    response = client.post("/api/reviews", json=minimal_review_body("does-not-exist"))
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "unknown_request"


def test_someone_elses_pickup_request_is_403(app):
    rider_a = app.test_client()
    rider_b = app.test_client()
    pickup_request = collected_request(rider_a)

    response = rider_b.post("/api/reviews", json=minimal_review_body(pickup_request["id"]))
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "not_your_request"


def test_reviewing_a_request_that_was_never_collected_is_409(client):
    created = client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]
    response = client.post("/api/reviews", json=minimal_review_body(created["id"]))
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "request_not_collected"


def test_reviewing_a_cancelled_request_is_409(client):
    created = client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).get_json()["request"]
    client.post(f"/api/pickup-requests/{created['id']}/cancel")

    response = client.post("/api/reviews", json=minimal_review_body(created["id"]))
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "request_not_collected"


# ---- GET /api/reviews ----


def test_list_reviews_needs_sign_in(client):
    pickup_request = collected_request(client)
    client.post("/api/reviews", json=minimal_review_body(pickup_request["id"]))

    assert client.get("/api/reviews").status_code == 401
    assert sign_in(client).get("/api/reviews").status_code == 200


def test_list_reviews_returns_what_was_submitted(client):
    pickup_request = collected_request(client)
    client.post("/api/reviews", json=minimal_review_body(pickup_request["id"]))

    reviews = sign_in(client).get("/api/reviews").get_json()["reviews"]
    assert len(reviews) == 1
    assert reviews[0]["pickup_request_id"] == pickup_request["id"]


def test_reviews_are_actually_written_to_disk(client, config_dir):
    pickup_request = collected_request(client)
    client.post("/api/reviews", json=minimal_review_body(pickup_request["id"]))

    on_disk = ReviewStore(config_dir / "admin" / "reviews.json").list()
    assert len(on_disk) == 1
    assert on_disk[0].pickup_request_id == pickup_request["id"]
