"""GET and POST /api/downtime, PATCH and DELETE /api/downtime/<id>.

Response shapes: docs/api.md.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Blueprint, current_app, jsonify, request

from backend.api.params import parse_time_bound, parse_vehicle_ids
from backend.auth import admin_required
from backend.config import ConfigError
from backend.downtime import DowntimeStore
from backend.models import Downtime

bp = Blueprint("downtime", __name__)


class _BadRequest(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def response(self):
        return jsonify({"error": {"code": self.code, "message": self.message}}), 400


def _store() -> DowntimeStore:
    store = current_app.config["DOWNTIME_STORE"]
    if store is None:
        raise ConfigError("storage.directory is not set in config/app.yaml, so downtime cannot be stored.")
    return store


def _known_ids() -> list[str]:
    return [vehicle.id for vehicle in current_app.config["NUWAY_CONFIG"].vehicles]


def _instant(body: dict[str, Any], field: str) -> datetime:
    """
    A body field as a UTC datetime. The timezone is required, as for `from`
    and `to` elsewhere, since a bare time is ambiguous.
    """
    value = body.get(field)
    if value is None or value == "":
        raise _BadRequest("missing_field", f"'{field}' is required.")
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise _BadRequest("bad_timestamp", f"Could not parse '{field}' as an ISO 8601 timestamp.") from None
    if parsed.tzinfo is None:
        raise _BadRequest("bad_timestamp", f"'{field}' must include a timezone, e.g. 2026-10-01T09:00:00+08:00.")
    return parsed.astimezone(timezone.utc)


def _fields(body: dict[str, Any], existing: Optional[Downtime] = None) -> tuple[str, datetime, datetime, str]:
    """
    The vehicle, start, end and reason from a request body. For an edit,
    `existing` supplies any field the body leaves out.

    Raises
    ------
    _BadRequest
        `missing_field`, `unknown_vehicle`, `bad_timestamp`, or `bad_range`
        for an end not after its start (S18).
    """
    merged = {**(existing.to_dict() if existing else {}), **body}

    vehicle_id = merged.get("vehicle_id")
    if vehicle_id is None or vehicle_id == "":
        raise _BadRequest("missing_field", "'vehicle_id' is required.")
    known_ids = _known_ids()
    if vehicle_id not in known_ids:
        message = f"No vehicle with id {vehicle_id!r}. Known ids: {', '.join(known_ids)}."
        raise _BadRequest("unknown_vehicle", message)

    start = _instant(merged, "start")
    end = _instant(merged, "end")
    if end <= start:
        raise _BadRequest("bad_range", "End time must be after start time.")

    reason = merged.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise _BadRequest("missing_field", "'reason' is required.")

    return vehicle_id, start, end, reason.strip()


def _overlap_response(vehicle_id: str, clashes: list[Downtime]):
    """
    Warn before storing a period that overlaps this vehicle's existing
    downtime. The client resends with `"confirm": true` to store it anyway.
    """
    count = len(clashes)
    message = (
        f"This period overlaps {count} existing downtime record{'' if count == 1 else 's'} "
        f"for vehicle {vehicle_id}. Resend with \"confirm\": true to save it anyway."
    )
    body = {"error": {"code": "overlap", "message": message}, "overlaps": [r.to_dict() for r in clashes]}
    return jsonify(body), 409


def _unknown(record_id: str):
    message = f"No downtime record with id '{record_id}'."
    return jsonify({"error": {"code": "unknown_downtime", "message": message}}), 404


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@bp.get("/api/downtime")
@admin_required
def list_downtime():
    """
    Recorded downtime, ascending by start.

    Query params:
        vehicles  optional; as for /api/positions. Default: every record,
                  including any for a vehicle no longer configured.
        from, to  optional; only records overlapping this window.
    """
    from_value = request.args.get("from")
    to_value = request.args.get("to")
    vehicles = request.args.get("vehicles")

    try:
        vehicle_ids = parse_vehicle_ids(vehicles, _known_ids()) if vehicles else None
        start = parse_time_bound(from_value, True) if from_value else None
        end = parse_time_bound(to_value, False) if to_value else None
        if start and end and start > end:
            raise ValueError("bad_range")
    except ValueError as code:
        message = {
            "bad_timestamp": "Could not parse 'from' or 'to' as a date or timestamp.",
            "bad_range": "'from' must not be after 'to'.",
            "unknown_vehicle": f"No vehicle with that id. Known ids: {', '.join(_known_ids())}.",
        }.get(str(code), "Invalid request.")
        return jsonify({"error": {"code": str(code), "message": message}}), 400

    records = _store().list(vehicle_ids, start, end)
    return jsonify({"records": [r.to_dict() for r in records]})


@bp.post("/api/downtime")
@admin_required
def create_downtime():
    """
    Record downtime.

    Body: `{"vehicle_id", "start", "end", "reason", "confirm"?}`.

    Returns
    -------
    flask.Response
        `201` with the record. `400` for a missing or invalid field. `409`
        `overlap` with the clashing records if it overlaps this vehicle's
        existing downtime and `confirm` is not true.
    """
    body = _body()
    try:
        vehicle_id, start, end, reason = _fields(body)
    except _BadRequest as exc:
        return exc.response()

    store = _store()
    clashes = store.overlapping(vehicle_id, start, end)
    if clashes and body.get("confirm") is not True:
        return _overlap_response(vehicle_id, clashes)

    record = store.add(vehicle_id, start, end, reason, datetime.now(timezone.utc))
    return jsonify({"record": record.to_dict()}), 201


@bp.patch("/api/downtime/<record_id>")
@admin_required
def update_downtime(record_id: str):
    """
    Correct a record (S20). The body is as for POST; fields left out keep
    their current values.

    Returns
    -------
    flask.Response
        `200` with the record. `404` `unknown_downtime`. Otherwise as POST,
        with the record itself left out of the overlap check, and no check
        at all if the vehicle and times are unchanged.
    """
    store = _store()
    existing = store.get(record_id)
    if existing is None:
        return _unknown(record_id)

    body = _body()
    try:
        vehicle_id, start, end, reason = _fields(body, existing)
    except _BadRequest as exc:
        return exc.response()

    # An overlap already confirmed is not warned about again when only the
    # reason changes.
    period_changed = (vehicle_id, start, end) != (existing.vehicle_id, existing.start, existing.end)
    clashes = store.overlapping(vehicle_id, start, end, exclude_id=record_id) if period_changed else []
    if clashes and body.get("confirm") is not True:
        return _overlap_response(vehicle_id, clashes)

    record = store.update(record_id, vehicle_id, start, end, reason, datetime.now(timezone.utc))
    if record is None:
        return _unknown(record_id)
    return jsonify({"record": record.to_dict()})


@bp.delete("/api/downtime/<record_id>")
@admin_required
def delete_downtime(record_id: str):
    """
    Remove a record entered in error (S20). `204`, or `404` `unknown_downtime`.
    """
    if not _store().delete(record_id):
        return _unknown(record_id)
    return "", 204
