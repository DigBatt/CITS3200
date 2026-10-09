
"""Admin API for daily snapshots (S17)."""

from datetime import date

from flask import Blueprint, current_app, jsonify, send_file

from backend.auth import admin_required

bp = Blueprint("snapshots", __name__)


def get_store():
    """Return the configured snapshot store."""
    return current_app.config["SNAPSHOT_STORE"]


@bp.get("/api/snapshots")
@admin_required
def list_snapshots():
    """List available snapshots and missing dates."""
    store = get_store()

    if store is None:
        return jsonify(error={
            "code": "data_unavailable",
            "message": "Snapshot storage is not configured.",
        }), 500

    try:
        available = [
            day.isoformat() if isinstance(day, date) else day
            for day in store.list_dates()
        ]

        schedule_store = current_app.config.get("SNAPSHOT_SCHEDULE_STORE")
        missing = []

        if schedule_store is not None:
            missing = schedule_store.missing_dates()

        return jsonify(
            available=available,
            missing=missing,
        )

    except (OSError, ValueError) as exc:
        return jsonify(error={
            "code": "data_unavailable",
            "message": str(exc),
        }), 500


@bp.get("/api/snapshots/<day>/download")
@admin_required
def download_snapshot(day):
    """Download a snapshot JSON file."""
    store = get_store()

    if store is None:
        return jsonify(error={
            "code": "data_unavailable",
            "message": "Snapshot storage is not configured.",
        }), 500

    try:
        snapshot_date = date.fromisoformat(day)
    except ValueError:
        return jsonify(error={
            "code": "invalid_date",
            "message": "Expected YYYY-MM-DD.",
        }), 400

    path = store.path_for(snapshot_date)

    if not path.is_file():
        return jsonify(error={
            "code": "not_found",
            "message": "No snapshot exists for this date.",
        }), 404

    return send_file(
        path,
        as_attachment=True,
        download_name=f"snapshot-{snapshot_date.isoformat()}.json",
        mimetype="application/json",
    )
