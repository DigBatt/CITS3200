"""POST and GET /api/pickup-requests, GET /api/pickup-requests/mine,
GET /api/pickup-requests/hours, POST /api/pickup-requests/<id>/cancel,
GET /api/routes/<id>/waiting, POST /api/stops/<id>/collect.

A rider asking to be collected at a stop (and checking on or cancelling that
request themselves), the operator's per-route view of who is waiting, and the
operator clearing a stop once the riders are aboard. Response shapes and the
rider-token cookie decision: docs/api.md.
"""

from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request

from backend.auth import admin_required
from backend.models import PickupRequest, format_timestamp
from backend.operating_hours import OperatingHours, local_day_and_time
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


def _operating_hours() -> OperatingHours:
    return current_app.config["OPERATING_HOURS"]


def _hours_payload(now: datetime) -> dict:
    """
    Whether riders may request a pickup right now, and the week's hours
    (S15 follow-up). Backs GET /api/pickup-requests/hours, which the rider
    page reads to show a "closed" message instead of the stop picker.
    """
    hours = _operating_hours()
    tz = current_app.config["NUWAY_CONFIG"].timezone
    by_day = hours.to_dict()
    today = local_day_and_time(now, tz)[0] if tz else None
    return {
        "configured": hours.configured,
        "timezone": tz,
        "open_now": hours.covers(now, tz),
        "today": today,
        "today_hours": by_day.get(today) if today else None,
        "hours": by_day,
    }


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


@bp.get("/api/pickup-requests/hours")
def pickup_request_hours():
    """
    When riders may request a pickup at all (S15 follow-up).

    Public, same as the rest of the rider-facing endpoints here: the rider
    page reads this to show a "closed" message instead of the stop picker
    outside the shuttle's hours, defined in `pickup_requests.operating_hours`
    of config/app.yaml (docs/api.md).

    Returns
    -------
    flask.Response
        `200` with `configured` (false if the block is not set at all, so the
        feature is off and `open_now` is always true), `timezone`, `open_now`,
        `today` and `today_hours` (local to `timezone`, null if it is not
        set), and `hours` for the whole week.
    """
    return jsonify(_hours_payload(datetime.now(timezone.utc)))


@bp.post("/api/pickup-requests")
def create_pickup_request():
    """
    Open a pickup request at a stop.

    Body: `{"stop_id": "<id>"}`.

    Returns
    -------
    flask.Response
        `400` `unknown_stop` if the stop is not configured. `403`
        `outside_operating_hours` if the shuttle is not currently taking
        requests (S15 follow-up; GET /api/pickup-requests/hours says when it
        is). Otherwise `201` with the new request, or `200` with the rider's
        existing open request at that stop if they already have one
        (no-duplicate rule). A `rider_token` cookie is set on the rider's
        first request.
    """
    body = request.get_json(silent=True) or {}
    stop_id = body.get("stop_id")

    network = _network()
    if not isinstance(stop_id, str) or network.stop(stop_id) is None:
        message = f"No stop with id {stop_id!r}. Known ids: {', '.join(network.stops) or 'none'}."
        return jsonify({"error": {"code": "unknown_stop", "message": message}}), 400

    now = datetime.now(timezone.utc)
    tz = current_app.config["NUWAY_CONFIG"].timezone
    if not _operating_hours().covers(now, tz):
        message = "The shuttle is not taking pickup requests right now. See GET /api/pickup-requests/hours for when it is."
        return jsonify({"error": {"code": "outside_operating_hours", "message": message}}), 403

    rider_token = request.cookies.get(RIDER_TOKEN_COOKIE)
    is_new_rider = rider_token is None
    if is_new_rider:
        rider_token = secrets.token_urlsafe(24)

    # Expire first, so a rider whose old request has gone stale gets a new one.
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
@admin_required
def list_pickup_requests():
    """
    Every pickup request, ascending by `created_at`. For the operator view
    and the admin's review of the day, so signed in only.

    Query params:
        status  optional; one of `open`, `collected`, `expired`.
    """
    _expire_stale(datetime.now(timezone.utc))
    requests = _store().list(status=request.args.get("status"))
    return jsonify({"requests": [r.to_dict() for r in requests]})


@bp.get("/api/pickup-requests/mine")
def my_pickup_request():
    """
    The calling rider's own most recent pickup request, any status (S15).

    Identified by the `rider_token` cookie (S08.2) — no sign-in needed, and
    this is not admin-only, unlike GET /api/pickup-requests: it only ever
    answers with the caller's own request, never anyone else's, so it carries
    nothing the rider does not already know. Backs the rider view polling for
    its own request going `collected`, `expired` or `cancelled`.

    Returns
    -------
    flask.Response
        `{"request": null}` if this rider has no `rider_token` cookie yet, or
        has never made a request. Otherwise the same shape POST returns.
    """
    _expire_stale(datetime.now(timezone.utc))
    rider_token = request.cookies.get(RIDER_TOKEN_COOKIE)
    found = _store().most_recent_for_rider(rider_token) if rider_token else None
    return jsonify({"request": found.to_dict() if found else None})


@bp.post("/api/pickup-requests/<request_id>/cancel")
def cancel_pickup_request(request_id: str):
    """
    The rider withdraws their own open request (S15).

    Ownership is the `rider_token` cookie matching the request's — the same
    identity POST /api/pickup-requests uses, so a rider needs no sign-in to
    cancel, but also cannot cancel someone else's.

    Returns
    -------
    flask.Response
        `404` `unknown_request` if the id is not on record. `403`
        `not_your_request` if the caller's `rider_token` (or the lack of one)
        does not match. `409` `request_not_open` if it has already been
        collected, expired, or cancelled. Otherwise `200` with the request,
        now `cancelled` and `cleared_at` set.
    """
    store = _store()
    existing = store.get(request_id)
    if existing is None:
        message = f"No pickup request with id '{request_id}'."
        return jsonify({"error": {"code": "unknown_request", "message": message}}), 404

    rider_token = request.cookies.get(RIDER_TOKEN_COOKIE)
    if rider_token is None or existing.rider_token != rider_token:
        message = "This pickup request does not belong to you."
        return jsonify({"error": {"code": "not_your_request", "message": message}}), 403

    cancelled = store.cancel(request_id, datetime.now(timezone.utc))
    if cancelled is None:
        message = "This request is no longer open, so it cannot be cancelled."
        return jsonify({"error": {"code": "request_not_open", "message": message}}), 409

    return jsonify({"request": cancelled.to_dict()})


@bp.get("/api/routes/<route_id>/waiting")
@admin_required
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
@admin_required
def collect_at_stop(stop_id: str):
    """
    The operator has picked up the riders waiting at a stop (S10).

    Body: `{"vehicle_id", "route_id"}`, both required (S15 follow-up) -- a
    review attaches to whichever vehicle and route the operator says they are
    running, since there is no published schedule yet to look that up from
    instead (PickupRequest.vehicle_id/route_id, docs/api.md). The admin page
    enforces picking both before this is ever called; this is the check that
    actually matters, since nothing stops a direct API call skipping it.

    Every open request at the stop is closed, whichever route the rider was
    waiting for. The records are kept, marked `collected` with `cleared_at`.

    Returns
    -------
    flask.Response
        `404` `unknown_stop` if the stop is not configured. `400`
        `missing_field` if either body field is left out, `unknown_vehicle`
        or `unknown_route` if either is not configured. Otherwise `200` with
        the requests closed, empty if nobody was waiting.
    """
    network = _network()
    if network.stop(stop_id) is None:
        message = f"No stop with id '{stop_id}'. Known ids: {', '.join(network.stops) or 'none'}."
        return jsonify({"error": {"code": "unknown_stop", "message": message}}), 404

    body = request.get_json(silent=True) or {}
    vehicle_id = body.get("vehicle_id")
    route_id = body.get("route_id")
    if not vehicle_id or not route_id:
        message = "Both 'vehicle_id' and 'route_id' are required to mark a stop picked up."
        return jsonify({"error": {"code": "missing_field", "message": message}}), 400

    config = current_app.config["NUWAY_CONFIG"]
    if config.vehicle(vehicle_id) is None:
        known = ", ".join(v.id for v in config.vehicles)
        message = f"No vehicle with id '{vehicle_id}'. Known ids: {known or 'none'}."
        return jsonify({"error": {"code": "unknown_vehicle", "message": message}}), 400
    if network.route(route_id) is None:
        message = f"No route with id '{route_id}'. Known ids: {', '.join(network.routes) or 'none'}."
        return jsonify({"error": {"code": "unknown_route", "message": message}}), 400

    closed = _store().collect(stop_id, vehicle_id, route_id, datetime.now(timezone.utc))
    return jsonify({"collected": [r.to_dict() for r in closed]})
