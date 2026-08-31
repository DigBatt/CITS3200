"""
GET /api/positions.
"""

from __future__ import annotations
from datetime import datetime
from flask import Blueprint, current_app, jsonify, request

from backend.models import format_timestamp
from backend.api.params import parse_time_range, parse_vehicle_ids, PERTH_TZ, UTC_TZ

bp = Blueprint("positions", __name__)


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
        return jsonify({"error": {"code": str(code), "message": message}}), 400

    tracks = repo.get_positions(vehicle_ids, start, end)

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