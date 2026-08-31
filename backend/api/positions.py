"""
GET /api/positions.
"""

from __future__ import annotations
from flask import Blueprint, current_app, jsonify

from backend.models import format_timestamp

bp = Blueprint("positions", __name__)


@bp.get("/api/positions")
def positions():
    """
    Every stored position grouped by vehicle.

    Returns
    -------
    flask.Response
        JSON: `from`, `to` (the extent of the returned data, null when there is
        none) and `vehicles`, one entry per configured vehicle with its name,
        colour, count and positions ascending by timestamp. A vehicle with no
        data is present with `count` 0.
    """
    config = current_app.config["NUWAY_CONFIG"]
    tracks = current_app.config["REPOSITORY"].get_positions()

    stamps = [p.timestamp for rows in tracks.values() for p in rows]
    return jsonify(
        {
            "from": format_timestamp(min(stamps)) if stamps else None,
            "to": format_timestamp(max(stamps)) if stamps else None,
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
            ],
        }
    )
