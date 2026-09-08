"""
GET /api/metrics

Utilisation figures from the GMG time usage model, per vehicle over the
requested window.
"""

from __future__ import annotations
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from backend.api.params import PERTH_TZ, UTC_TZ, parse_time_range, parse_vehicle_ids
from backend.config import ConfigError
from backend.metrics.tum import Settings, summarise
from backend.models import format_timestamp

bp = Blueprint("metrics", __name__)


@bp.get("/api/metrics")
def metrics():
    """
    Utilisation for a selection and a period.

    Query params are those of /api/positions: `vehicles`, `from`, `to`.

    Returns
    -------
    flask.Response
        JSON: the resolved `from` and `to`, and `vehicles`, one entry per
        selected vehicle with its `buckets`, `kpis` and `unavailable`. 400 in
        the documented shape for a bad parameter.

    Raises
    ------
    ConfigError
        If the `utilisation` thresholds are unset, since the model cannot
        classify anything without them.
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

    try:
        vehicles = [
            summarise(vehicle.id, tracks.get(vehicle.id, []), start, end, settings).to_dict()
            for vehicle in config.vehicles
            if vehicle.id in vehicle_ids
        ]
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    return jsonify(
        {
            "from": format_timestamp(start),
            "to": format_timestamp(end),
            "vehicles": vehicles,
        }
    )
