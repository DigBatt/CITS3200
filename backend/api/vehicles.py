"""GET /api/vehicles.

The fleet, its identity and its current state.

Response shape: docs/api.md.

Ages are measured against wall clock time.
"""

from __future__ import annotations
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from backend.config import ConfigError
from backend.models import format_timestamp

bp = Blueprint("vehicles", __name__)


@bp.get("/api/vehicles")
def vehicles():
    """
    The configured fleet with each vehicle's latest position and liveness.

    Returns
    -------
    flask.Response
        JSON: `generated_at`, the echoed `inactivity_threshold_seconds`, and
        `vehicles`, one entry per configured vehicle. A vehicle with no
        telemetry at all is `inactive` with nulls for the rest.

    Raises
    ------
    ConfigError
        If `liveness.inactivity_threshold_seconds` is unset, since there is no
        answer to give without it.
    """
    config = current_app.config["NUWAY_CONFIG"]
    threshold = config.inactivity_threshold_seconds
    if threshold is None:
        raise ConfigError("config/app.yaml does not set liveness.inactivity_threshold_seconds")

    latest = current_app.config["REPOSITORY"].get_latest_positions()
    now = datetime.now(timezone.utc)

    payload = []
    for vehicle in config.vehicles:
        position = latest.get(vehicle.id)
        age = (now - position.timestamp).total_seconds() if position else None
        payload.append(
            {
                **vehicle.to_dict(),
                "status": "active" if age is not None and age <= threshold else "inactive",
                "last_seen": format_timestamp(position.timestamp) if position else None,
                "seconds_since_last_seen": round(age, 1) if age is not None else None,
                "last_position": position.to_dict() if position else None,
            }
        )

    return jsonify(
        {
            "generated_at": format_timestamp(now),
            "inactivity_threshold_seconds": threshold,
            "vehicles": payload,
        }
    )
