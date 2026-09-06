"""GET /api/positions."""

from __future__ import annotations
from flask import Blueprint, current_app, jsonify

from backend.models import format_timestamp
from backend.api.params import ApiParameterError, parse_range, parse_vehicle_ids

bp = Blueprint("positions", __name__)


@bp.get("/api/positions")
def positions():
    config = current_app.config["NUWAY_CONFIG"]
    try:
        vehicle_ids = parse_vehicle_ids(config)
        start, end = parse_range(config)
    except ApiParameterError as exc:
        return jsonify(error={"code": exc.code, "message": exc.message}), 400

    tracks = current_app.config["REPOSITORY"].get_positions(vehicle_ids, start, end)
    selected = config.vehicles if vehicle_ids is None else [config.vehicle(v) for v in vehicle_ids]
    selected = [v for v in selected if v is not None]

    stamps = [p.timestamp for rows in tracks.values() for p in rows]
    return jsonify(
        {
            "from": format_timestamp(min(stamps)) if stamps else (format_timestamp(start) if start else None),
            "to": format_timestamp(max(stamps)) if stamps else (format_timestamp(end) if end else None),
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
                for vehicle in selected
            ],
        }
    )
