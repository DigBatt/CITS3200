"""GET /api/vehicles: configured fleet and latest telemetry state."""

from __future__ import annotations

from datetime import datetime, timezone
from flask import Blueprint, current_app, jsonify

from backend.models import format_timestamp
from backend.api.params import ApiParameterError, parse_vehicle_ids

bp = Blueprint("vehicles", __name__)


@bp.get("/api/vehicles")
def vehicles():
    config = current_app.config["NUWAY_CONFIG"]
    try:
        vehicle_ids = parse_vehicle_ids(config)
    except ApiParameterError as exc:
        return jsonify(error={"code": exc.code, "message": exc.message}), 400

    selected = config.vehicles if vehicle_ids is None else [config.vehicle(v) for v in vehicle_ids]
    selected = [v for v in selected if v is not None]
    latest = current_app.config["REPOSITORY"].get_latest_positions([v.id for v in selected])
    now = datetime.now(timezone.utc)
    threshold = config.inactivity_threshold_seconds or 300

    rows = []
    for vehicle in selected:
        position = latest.get(vehicle.id)
        age = (now - position.timestamp).total_seconds() if position else None
        active = position is not None and age is not None and age <= threshold
        rows.append(
            {
                "id": vehicle.id,
                "name": vehicle.name,
                "colour": vehicle.colour,
                "status": "active" if active else "inactive",
                "last_seen": format_timestamp(position.timestamp) if position else None,
                "seconds_since_last_seen": max(0.0, age) if age is not None else None,
                "last_position": position.to_dict() if position else None,
            }
        )

    return jsonify(
        generated_at=format_timestamp(now),
        inactivity_threshold_seconds=threshold,
        refresh_interval_seconds=config.refresh_interval_seconds or 15,
        timezone=config.timezone or "Australia/Perth",
        vehicles=rows,
    )
