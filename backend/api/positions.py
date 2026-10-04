"""
GET /api/positions, and GET /api/positions/extent for just the first and last
timestamp in a period.
"""

from __future__ import annotations
from datetime import datetime
from flask import Blueprint, current_app, jsonify, request

from backend.models import format_timestamp
from backend.api.params import parse_time_range, parse_vehicle_ids, PERTH_TZ, UTC_TZ

bp = Blueprint("positions", __name__)


def _selection():
    """
    Parse the shared `vehicles`/`from`/`to` query params and fetch the tracks.

    Returns
    -------
    tuple
        `(None, (vehicle_ids, start, end, tracks))` on success, or
        `(response, None)` with a 400 error response to return as is.
    """
    config = current_app.config["NUWAY_CONFIG"]
    repo = current_app.config["REPOSITORY"]
    known_ids = [vehicle.id for vehicle in config.vehicles]

    from_value = request.args.get("from") or datetime.now(PERTH_TZ).date().isoformat()
    to_value = request.args.get("to") or datetime.now(UTC_TZ).isoformat()

    try:
        vehicle_ids = parse_vehicle_ids(request.args.get("vehicles"), known_ids)
        start, end = parse_time_range(from_value, to_value)
    except ValueError as code:
        message = {
            "bad_timestamp": "Could not parse 'from' or 'to' as a date or timestamp.",
            "bad_range": "'from' must not be after 'to'.",
            "unknown_vehicle": f"No vehicle with that id. Known ids: {', '.join(known_ids)}.",
        }.get(str(code), "Invalid request.")
        return (jsonify({"error": {"code": str(code), "message": message}}), 400), None

    return None, (vehicle_ids, start, end, repo.get_positions(vehicle_ids, start, end))


@bp.get("/api/positions")
def positions():
    """
    Stored positions for a selection and a period.

    Query params (all optional, per docs/api.md):
        vehicles  comma-separated ids; absent/empty means the whole fleet
        from      ISO 8601 instant or bare date; default: start of today, Perth
        to        ISO 8601 instant or bare date; default: now

    Returns
    -------
    flask.Response
        JSON: `from`, `to` (the resolved bounds actually applied) and
        `vehicles`, one entry per configured vehicle with its name, colour,
        count and positions ascending by timestamp. A vehicle with no data
        in range is present with `count` 0.
    """
    error, selection = _selection()
    if error:
        return error
    vehicle_ids, start, end, tracks = selection
    config = current_app.config["NUWAY_CONFIG"]

    return jsonify(
        {
            "from": format_timestamp(start),
            "to": format_timestamp(end),
            "vehicles": [
                {
                    "vehicle_id": vehicle.id,
                    "name": vehicle.name,
                    "colour": vehicle.colour,
                    "count": len(tracks.get(vehicle.id, [])),
                    "positions": [
                        {k: v for k, v in p.to_dict().items() if k != "vehicle_id"}
                        for p in tracks.get(vehicle.id, [])
                    ],
                }
                for vehicle in config.vehicles
                if vehicle.id in vehicle_ids
            ],
        }
    )


@bp.get("/api/positions/extent")
def positions_extent():
    """
    The first and last stored position in a period, without the positions.

    Same query params and errors as /api/positions. For the calendar's time
    slider, which marks and can zoom to where the data actually is; asking
    /api/positions for that would ship every row over a range of days just to
    read two timestamps.

    Returns
    -------
    flask.Response
        JSON: `from`, `to` as applied, `first` and `last` across the whole
        selection (both `null` when it holds nothing), and `vehicles`, one
        entry per selected vehicle with its own `first`, `last` and `count`.
        Rows without a fix count: they are still measurements.
    """
    error, selection = _selection()
    if error:
        return error
    vehicle_ids, start, end, tracks = selection
    config = current_app.config["NUWAY_CONFIG"]

    vehicles = []
    for vehicle in config.vehicles:
        if vehicle.id not in vehicle_ids:
            continue
        track = tracks.get(vehicle.id, [])
        vehicles.append(
            {
                "vehicle_id": vehicle.id,
                "count": len(track),
                # Ascending by timestamp, per the repository contract.
                "first": format_timestamp(track[0].timestamp) if track else None,
                "last": format_timestamp(track[-1].timestamp) if track else None,
            }
        )

    firsts = [track[0].timestamp for track in tracks.values() if track]
    lasts = [track[-1].timestamp for track in tracks.values() if track]
    return jsonify(
        {
            "from": format_timestamp(start),
            "to": format_timestamp(end),
            "first": format_timestamp(min(firsts)) if firsts else None,
            "last": format_timestamp(max(lasts)) if lasts else None,
            "vehicles": vehicles,
        }
    )
