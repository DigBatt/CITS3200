"""GET /api/vehicles.

The fleet, its identity and its current state.

Response shape: docs/api.md.
"""

from __future__ import annotations
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

from backend.config import ConfigError
from backend.freshness import freshness
from backend.models import format_timestamp

bp = Blueprint("vehicles", __name__)


@bp.get("/api/vehicles")
def vehicles():
    """
    The configured fleet with each vehicle's latest position and liveness.

    Returns
    -------
    flask.Response
        JSON: `generated_at`, the echoed `inactivity_threshold_seconds` and
        `freshness_rule`, and `vehicles`, one entry per configured vehicle. A
        vehicle with no telemetry at all is `inactive` with nulls for the rest.

    Raises
    ------
    ConfigError
        If `liveness.inactivity_threshold_seconds`,
        `liveness.green_within_weekdays` or `liveness.red_after_days` is
        unset, since there is no answer to give without them.
    """
    config = current_app.config["NUWAY_CONFIG"]
    threshold = config.inactivity_threshold_seconds
    if threshold is None:
        raise ConfigError("config/app.yaml does not set liveness.inactivity_threshold_seconds")
    green_within_weekdays = config.green_within_weekdays
    red_after_days = config.red_after_days
    if green_within_weekdays is None or red_after_days is None:
        raise ConfigError(
            "config/app.yaml does not set liveness.green_within_weekdays and liveness.red_after_days"
        )

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
                "freshness": freshness(
                    position.timestamp if position else None, now, green_within_weekdays, red_after_days
                ),
                "last_position": position.to_dict() if position else None,
            }
        )

    return jsonify(
        {
            "generated_at": format_timestamp(now),
            "inactivity_threshold_seconds": threshold,
            "freshness_rule": {
                "green_within_weekdays": green_within_weekdays,
                "red_after_days": red_after_days,
            },
            "vehicles": payload,
        }
    )
