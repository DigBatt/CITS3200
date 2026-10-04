
"""Admin API for snapshot metric selection (S16)."""

from flask import Blueprint, current_app, jsonify, request

from backend.auth import admin_required
from backend.config import ConfigError

bp = Blueprint("snapshot_settings", __name__)


def get_store():
    """Return the snapshot settings store configured by the application."""
    store = current_app.config["SNAPSHOT_SETTINGS_STORE"]
    if store is None:
        raise ConfigError("storage.directory is not set in config/app.yaml, so snapshot settings cannot be stored.")
    return store


@bp.get("/api/snapshot-settings")
@admin_required
def get_snapshot_settings():
    """Return the currently selected metrics."""

    try:
        metrics = get_store().load()
    except (OSError, ValueError) as exc:
        return jsonify(error={
            "code": "data_unavailable",
            "message": str(exc),
        }), 500

    return jsonify(metrics=metrics)


@bp.put("/api/snapshot-settings")
@admin_required
def update_snapshot_settings():
    """Validate and save the administrator's metric selection."""

    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return jsonify(error={
            "code": "invalid_request",
            "message": "Expected a JSON object.",
        }), 400

    try:
        metrics = get_store().save(body.get("metrics"))
    except ValueError as exc:
        return jsonify(error={
            "code": "invalid_metrics",
            "message": str(exc),
        }), 400
    except OSError as exc:
        return jsonify(error={
            "code": "data_unavailable",
            "message": str(exc),
        }), 500

    return jsonify(metrics=metrics)
