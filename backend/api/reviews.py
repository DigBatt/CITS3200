"""POST /api/reviews, GET /api/reviews.

A rider's review of a completed pickup (S15 follow-up). Response shapes:
docs/api.md.
"""

from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from backend.auth import admin_required
from backend.config import ConfigError
from backend.models import PickupRequest, Review
from backend.pickup_requests import PickupRequestStore
from backend.reviews import ReviewStore

bp = Blueprint("reviews", __name__)

#: Duplicated from api/pickup_requests.py rather than imported, since the two
#: modules' only other connection is the PickupRequest a review is attributed
#: to; sharing this one constant was not worth coupling them any closer.
RIDER_TOKEN_COOKIE = "rider_token"

#: body field -> whether it is required. Everything else in Review is
#: optional free text/choice, stored as "" when left out (Review.from_dict).
RATING_FIELDS = ("safety_rating", "app_rating")
OPTIONAL_TEXT_FIELDS = (
    "vehicle_behaviour",
    "obstacle_interaction",
    "punctuality",
    "ride_duration_ok",
    "purpose",
    "stop_quality",
    "ramp_needed",
    "app_comment",
    "role",
    "usage_frequency",
    "comments",
)


def _store() -> ReviewStore:
    store = current_app.config["REVIEW_STORE"]
    if store is None:
        raise ConfigError("storage.directory is not set in config/app.yaml, so reviews cannot be stored.")
    return store


def _rating(body, field: str) -> int:
    """
    Raises
    ------
    ValueError
        If missing or not a whole number from 1 to 5.
    """
    try:
        rating = int(body.get(field))
    except (TypeError, ValueError):
        raise ValueError(f"'{field}' must be a whole number from 1 to 5.") from None
    if not 1 <= rating <= 5:
        raise ValueError(f"'{field}' must be a whole number from 1 to 5.")
    return rating


def _text(body, field: str) -> str:
    value = body.get(field)
    return value.strip() if isinstance(value, str) else ""


@bp.post("/api/reviews")
def create_review():
    """
    Body: `{"pickup_request_id", "safety_rating", "app_rating", ...}` -- the
    rest of Review's fields (docs/api.md), all optional besides the two
    ratings. `vehicle_id`, `route_id` and `wait_minutes` are not read from the
    body: they come from the `PickupRequest` itself, S10's record of which
    vehicle and route actually collected this rider and how long they waited.

    No sign-in: the `rider_token` cookie (S08.2) ties this to the rider's own
    pickup request, the same way the rest of the rider-facing endpoints do.

    Returns
    -------
    flask.Response
        `404` `unknown_request` if `pickup_request_id` is not on record. `403`
        `not_your_request` if it is not this rider's own. `409`
        `request_not_collected` if it was never marked collected -- only a
        completed pickup can be reviewed. `400` `bad_rating` if either rating
        is missing or out of range. Otherwise `201` with the stored review.
    """
    body = request.get_json(silent=True) or {}

    pickup_request_id = body.get("pickup_request_id")
    pickup_store: PickupRequestStore = current_app.config["PICKUP_REQUEST_STORE"]
    pickup_request = pickup_store.get(pickup_request_id) if pickup_request_id else None
    if pickup_request is None:
        message = f"No pickup request with id {pickup_request_id!r}."
        return jsonify({"error": {"code": "unknown_request", "message": message}}), 404

    rider_token = request.cookies.get(RIDER_TOKEN_COOKIE)
    if rider_token is None or pickup_request.rider_token != rider_token:
        message = "This pickup request does not belong to you."
        return jsonify({"error": {"code": "not_your_request", "message": message}}), 403

    if pickup_request.status != PickupRequest.COLLECTED:
        message = "Only a completed pickup can be reviewed."
        return jsonify({"error": {"code": "request_not_collected", "message": message}}), 409

    try:
        safety_rating = _rating(body, "safety_rating")
        app_rating = _rating(body, "app_rating")
    except ValueError as exc:
        return jsonify({"error": {"code": "bad_rating", "message": str(exc)}}), 400

    wait_minutes = None
    if pickup_request.cleared_at is not None:
        wait_minutes = round((pickup_request.cleared_at - pickup_request.created_at).total_seconds() / 60, 1)

    review = Review(
        id=uuid4().hex,
        pickup_request_id=pickup_request.id,
        stop_id=pickup_request.stop_id,
        vehicle_id=pickup_request.vehicle_id,
        route_id=pickup_request.route_id,
        wait_minutes=wait_minutes,
        created_at=datetime.now(timezone.utc),
        safety_rating=safety_rating,
        app_rating=app_rating,
        **{field: _text(body, field) for field in OPTIONAL_TEXT_FIELDS},
    )
    _store().add(review)
    return jsonify({"review": review.to_dict()}), 201


@bp.get("/api/reviews")
@admin_required
def list_reviews():
    """
    Every review, ascending by submission time. Admin only: a review carries
    nothing that identifies the rider, but is still the client's data to
    review, not something to expose publicly.
    """
    return jsonify({"reviews": [r.to_dict() for r in _store().list()]})
