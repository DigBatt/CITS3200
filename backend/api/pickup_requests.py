"""POST and GET /api/pickup-requests, GET /api/routes/<id>/waiting,
POST /api/stops/<id>/collect.

A rider asking to be collected at a stop, the operator's per-route view of
who is waiting, and the operator clearing a stop once the riders are aboard.
Response shapes and the rider-token cookie decision: docs/api.md.
"""

from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request

from backend.models import PickupRequest, format_timestamp
from backend.pickup_requests import PickupRequestStore, waiting_at_stops
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


def _expire_stale(now: datetime) -> None:
    """
    S10: expire open requests older than `pickup_requests.expire_after_seconds`.
    Run at the start of every request that reads or opens one, so expiry needs
    no background job; the operator view polls often enough to keep it current.
    """
    block = current_app.config["NUWAY_CONFIG"].pickup_requests or {}
    seconds = block.get("expire_after_seconds")
    if seconds:
        _store().expire(now, timedelta(seconds=seconds))


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

    # Expire first, so a rider whose old request has gone stale gets a new one.
    now = datetime.now(timezone.utc)
    _expire_stale(now)
    pickup_request, created = _store().create(stop_id, rider_token, now)

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
    _expire_stale(datetime.now(timezone.utc))
    requests = _store().list(status=request.args.get("status"))
    return jsonify({"requests": [r.to_dict() for r in requests]})


@bp.get("/api/routes/<route_id>/waiting")
def route_waiting(route_id: str):
    """
    Riders waiting along a route, for the operator view (S09.2).

    Returns
    -------
    flask.Response
        `404` `unknown_route` if the route is not configured. Otherwise the
        route's stops in service order, each with the number of open requests
        and the age of the oldest. Requests at stops off the route are left out.
    """
    network = _network()
    found = network.route(route_id)
    if found is None:
        message = f"No route with id '{route_id}'. Known ids: {', '.join(network.routes) or 'none'}."
        return jsonify({"error": {"code": "unknown_route", "message": message}}), 404

    now = datetime.now(timezone.utc)
    _expire_stale(now)
    counts = waiting_at_stops(_store().list(status=PickupRequest.OPEN), found.stop_ids)

    stops = []
    for stop, count in zip(network.stops_on_route(found.id), counts):
        oldest = count.oldest_created_at
        stops.append(
            {
                **stop.to_dict(),
                "waiting": count.waiting,
                "oldest_requested_at": format_timestamp(oldest) if oldest else None,
                "oldest_wait_seconds": round((now - oldest).total_seconds(), 1) if oldest else None,
            }
        )

    body = found.to_dict()
    del body["stop_ids"]
    return jsonify(
        {
            "generated_at": format_timestamp(now),
            "route": body,
            "total_waiting": sum(c.waiting for c in counts),
            "stops": stops,
        }
    )


@bp.post("/api/stops/<stop_id>/collect")
def collect_at_stop(stop_id: str):
    """
    The operator has picked up the riders waiting at a stop (S10).

    Every open request at the stop is closed, whichever route the rider was
    waiting for. The records are kept, marked `collected` with `cleared_at`.

    Returns
    -------
    flask.Response
        `404` `unknown_stop` if the stop is not configured. Otherwise `200`
        with the requests closed, empty if nobody was waiting.
    """
    network = _network()
    if network.stop(stop_id) is None:
        message = f"No stop with id '{stop_id}'. Known ids: {', '.join(network.stops) or 'none'}."
        return jsonify({"error": {"code": "unknown_stop", "message": message}}), 404

    closed = _store().collect(stop_id, datetime.now(timezone.utc))
    return jsonify({"collected": [r.to_dict() for r in closed]})
