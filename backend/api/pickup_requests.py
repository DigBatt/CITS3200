"""POST and GET /api/pickup-requests.

A rider asking to be collected at a stop. Response shapes
and the rider-token cookie decision: docs/api.md.
"""

from __future__ import annotations
import secrets
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from backend.pickup_requests import PickupRequestStore
from backend.stops import StopNetwork

bp = Blueprint("pickup_requests", __name__)

#: S08.2: identifies an anonymous rider so "no duplicate at the same stop"
#: is enforceable without an account for further dev
RIDER_TOKEN_COOKIE = "rider_token"
RIDER_TOKEN_MAX_AGE = 60 * 60 * 24 * 365  # ~1 year


def _network() -> StopNetwork:
    return current_app.config["NUWAY_CONFIG"].stops


def _store() -> PickupRequestStore:
    return current_app.config["PICKUP_REQUEST_STORE"]


@bp.post("/api/pickup-requests")
def create_pickup_request():
    """
    Open a pickup request at a stop.

    Body: `{"stop_id": "<id>"}`.

    Returns
    -------
    flask.Response
        `400` `unknown_stop` if the stop is not configured. Otherwise `201`
        with the new request, or `200` with the rider's existing open request
        at that stop if they already have one (no-duplicate rule)
        A `rider_token` cookie is set on the rider's first request
    """
    body = request.get_json(silent=True) or {}
    stop_id = body.get("stop_id")

    network = _network()
    if not isinstance(stop_id, str) or network.stop(stop_id) is None:
        message = f"No stop with id {stop_id!r}. Known ids: {', '.join(network.stops) or 'none'}."
        return jsonify({"error": {"code": "unknown_stop", "message": message}}), 400

    rider_token = request.cookies.get(RIDER_TOKEN_COOKIE)
    is_new_rider = rider_token is None
    if is_new_rider:
        rider_token = secrets.token_urlsafe(24)

    pickup_request, created = _store().create(stop_id, rider_token, datetime.now(timezone.utc))

    response = jsonify({"request": pickup_request.to_dict()})
    response.status_code = 201 if created else 200
    if is_new_rider:
        response.set_cookie(
            RIDER_TOKEN_COOKIE,
            rider_token,
            max_age=RIDER_TOKEN_MAX_AGE,
            httponly=True,
            samesite="Lax",
        )
    return response


@bp.get("/api/pickup-requests")
def list_pickup_requests():
    """
    Every pickup request, ascending by `created_at`. For the operator view.

    Query params:
        status  optional; one of `open`, `collected`, `expired`.
    """
    requests = _store().list(status=request.args.get("status"))
    return jsonify({"requests": [r.to_dict() for r in requests]})
