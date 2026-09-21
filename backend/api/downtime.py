"""
/api/downtime, operator reported out of service periods (S18).

Downtime is the one bucket of the time usage model the telemetry cannot
answer (backend/metrics/tum.py), so these records are entered by hand on the
admin page and stored by backend.repository.downtime_store.

Unlike the read endpoints, `from` and `to` are not defaulted to today: the
admin page lists the whole log, and a window is applied only if asked for.

Overlapping records are stored, not refused. A write answers with the records
its period clashes with so the page can warn, which keeps the overlap rule in
one place instead of restating it in JavaScript.

NOTE: these are the first write endpoints in the app and they are unprotected,
because admin auth (S13) does not exist yet. /api/admin/login is still a stub,
so anyone who can reach the server can edit the log. S13 must guard the three
write methods below before this is exposed beyond a local run.
"""

from __future__ import annotations
from flask import Blueprint, current_app, jsonify, request

from backend.api.params import parse_time_bound, parse_vehicle_ids
from backend.models import format_timestamp
from backend.repository.base import RepositoryError
from backend.repository.downtime_store import END_BEFORE_START

bp = Blueprint("downtime", __name__)

MESSAGES = {
    "bad_timestamp": "Could not parse 'start' or 'end' as a date or timestamp.",
    "bad_range": "'start' must be before 'end'.",
}


def _error(code: str, message: str, status: int):
    """
    An error in the shape of docs/api.md.
    """
    return jsonify({"error": {"code": code, "message": message}}), status


def _field_error(exc: ValueError) -> str:
    """
    The docs/api.md code for a field the store refused.
    """
    return "bad_range" if str(exc) == END_BEFORE_START else "invalid_record"


def _store():
    return current_app.config["DOWNTIME_STORE"]


def _known_ids() -> list[str]:
    return [vehicle.id for vehicle in current_app.config["NUWAY_CONFIG"].vehicles]


def _read_body() -> tuple[str, object, object, str]:
    """
    Pull the four fields of a write out of the request body.

    Returns
    -------
    tuple
        `vehicle_id`, `start`, `end`, `reason`. A field the body omits comes
        back None, which `update` reads as "leave alone" and `create` rejects.

    Raises
    ------
    ValueError
        With a docs/api.md code, if the body is not an object or a timestamp
        cannot be parsed.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("bad_request")

    start = body.get("start")
    end = body.get("end")

    # Same rules as ?from= and ?to=: an instant, or a bare Perth day.
    if start is not None:
        start = parse_time_bound(str(start), True)
    if end is not None:
        end = parse_time_bound(str(end), False)

    vehicle_id = body.get("vehicle_id")
    reason = body.get("reason")
    return (
        None if vehicle_id is None else str(vehicle_id),
        start,
        end,
        None if reason is None else str(reason),
    )


def _written(record, status: int):
    """
    A stored record, with any periods it clashes with.

    Parameters
    ----------
    record : backend.models.Downtime
    status : int
        201 for a new record, 200 for an edit.

    Returns
    -------
    flask.Response
        JSON: `record`, and `overlaps`, the other records for that vehicle
        whose period it intersects. A non empty `overlaps` is a warning, not
        a rejection; the record is already stored.
    """
    overlaps = _store().overlapping(record.vehicle_id, record.start, record.end, exclude_id=record.id)
    return jsonify({"record": record.to_dict(), "overlaps": [o.to_dict() for o in overlaps]}), status


@bp.get("/api/downtime")
def list_downtime():
    """
    The downtime log, oldest first.

    Query params (all optional):
        vehicles  comma-separated ids; absent/empty means the whole fleet
        from, to  ISO 8601 instant or bare date; absent means unbounded, so
                  the default is the whole log rather than today

    Returns
    -------
    flask.Response
        JSON: the resolved `from` and `to` (null where unbounded) and
        `records`, one flat list ascending by start. A record is included
        when it overlaps the window, so one still open at `from` counts.
    """
    from_value = request.args.get("from")
    to_value = request.args.get("to")

    try:
        vehicle_ids = parse_vehicle_ids(request.args.get("vehicles"), _known_ids())
        start = parse_time_bound(from_value, True) if from_value else None
        end = parse_time_bound(to_value, False) if to_value else None
    except ValueError as code:
        message = {
            "bad_timestamp": "Could not parse 'from' or 'to' as a date or timestamp.",
            "unknown_vehicle": f"No vehicle with that id. Known ids: {', '.join(_known_ids())}.",
        }.get(str(code), "Invalid request.")
        return _error(str(code), message, 400)

    if start is not None and end is not None and start > end:
        return _error("bad_range", "'from' must not be after 'to'.", 400)

    records = _store().list(vehicle_ids, start, end)
    return jsonify(
        {
            "from": format_timestamp(start) if start else None,
            "to": format_timestamp(end) if end else None,
            "records": [record.to_dict() for record in records],
        }
    )


@bp.post("/api/downtime")
def create_downtime():
    """
    Store a new record.

    Body: `vehicle_id`, `start`, `end`, `reason`, all required.

    Returns
    -------
    flask.Response
        201 and the shape of `_written`. 400 in the documented shape if a
        field is missing, unparseable, ends before it starts, or names a
        vehicle outside the fleet.
    """
    try:
        vehicle_id, start, end, reason = _read_body()
    except ValueError as code:
        return _error(str(code), MESSAGES.get(str(code), "Invalid request body."), 400)

    missing = [
        name
        for name, value in (("vehicle_id", vehicle_id), ("start", start), ("end", end), ("reason", reason))
        if value is None
    ]
    if missing:
        return _error("bad_request", f"Missing required field(s): {', '.join(missing)}.", 400)

    try:
        record = _store().add(vehicle_id, start, end, reason)
    except ValueError as exc:
        return _error(_field_error(exc), str(exc), 400)
    except RepositoryError as exc:
        return _error("unknown_vehicle", str(exc), 400)

    return _written(record, 201)


@bp.patch("/api/downtime/<record_id>")
def update_downtime(record_id: str):
    """
    Change a stored record.

    Body: any of `vehicle_id`, `start`, `end`, `reason`. Fields the body
    omits are left as they are.

    Returns
    -------
    flask.Response
        200 and the shape of `_written`, 404 if no record has that id, or
        400 in the documented shape for a bad field.
    """
    try:
        vehicle_id, start, end, reason = _read_body()
    except ValueError as code:
        return _error(str(code), MESSAGES.get(str(code), "Invalid request body."), 400)

    try:
        record = _store().update(record_id, vehicle_id=vehicle_id, start=start, end=end, reason=reason)
    except ValueError as exc:
        return _error(_field_error(exc), str(exc), 400)
    except RepositoryError as exc:
        return _error("unknown_vehicle", str(exc), 400)

    if record is None:
        return _error("not_found", f"No downtime record with id {record_id!r}.", 404)
    return _written(record, 200)


@bp.delete("/api/downtime/<record_id>")
def delete_downtime(record_id: str):
    """
    Remove a record.

    Returns
    -------
    flask.Response
        204 with no body, or 404 in the documented shape if no record has
        that id. Deleting twice is a 404, not a silent success, so the page
        can tell a stale row from a removed one.
    """
    if not _store().delete(record_id):
        return _error("not_found", f"No downtime record with id {record_id!r}.", 404)
    return "", 204
