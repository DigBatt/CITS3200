"""
GET /api/operating

When each vehicle was operating over a window, split by whether that fell
inside or outside its rostered service time. For the service calendar, which
marks both on the mini month and draws them in each vehicle's lane.

Reads positions the way /api/positions and /api/metrics do, from the
repository the live logger writes to, and classifies them with the same time
usage model (backend.metrics.operating), so the calendar and the figures agree.
"""

from __future__ import annotations
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from backend.api.params import PERTH_TZ, UTC_TZ, parse_time_range, parse_vehicle_ids
from backend.config import ConfigError
from backend.downtime import intervals_by_vehicle
from backend.metrics.operating import operating_intervals
from backend.metrics.tum import Settings
from backend.models import format_timestamp

bp = Blueprint("operating", __name__)


@bp.get("/api/operating")
def operating():
    """
    Operating intervals for a selection and a period.

    Query params are those of /api/metrics: `vehicles`, `from`, `to`, with the
    same defaults (start of today in Perth, to now) and the same errors.

    Returns
    -------
    flask.Response
        JSON: the resolved `from` and `to`, and `vehicles`, one entry per
        selected vehicle with its `intervals`, each `{start, end, in_schedule}`.
        `in_schedule` is null only when no timezone is configured.
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

    settings = Settings.from_config(config)
    tracks = repo.get_positions(vehicle_ids, start, end)
    # S19: recorded downtime is not operating time, as in /api/metrics.
    downtime = intervals_by_vehicle(current_app.config["DOWNTIME_STORE"], vehicle_ids, start, end)

    try:
        vehicles = [
            {
                "vehicle_id": vehicle.id,
                "intervals": [
                    interval.to_dict()
                    for interval in operating_intervals(
                        vehicle.id,
                        tracks.get(vehicle.id, []),
                        start,
                        end,
                        settings,
                        downtime=None if downtime is None else downtime[vehicle.id],
                    )
                ],
            }
            for vehicle in config.vehicles
            if vehicle.id in vehicle_ids
        ]
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    return jsonify({"from": format_timestamp(start), "to": format_timestamp(end), "vehicles": vehicles})
