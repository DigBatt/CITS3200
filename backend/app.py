"""
Run as `python -m backend.app`
"""

from __future__ import annotations
import logging
from datetime import timedelta
from pathlib import Path
from flask import Flask, jsonify, redirect, send_from_directory
from backend.api.downtime import bp as downtime_bp
from backend.api.earth import bp as earth_bp, load_google_maps_key
from backend.api.metrics import bp as metrics_bp
from backend.api.pickup_requests import bp as pickup_requests_bp
from backend.api.positions import bp as positions_bp
from backend.api.reviews import bp as reviews_bp
from backend.api.stops import bp as stops_bp
from backend.api.vehicles import bp as vehicles_bp
from backend.auth import admin_required, load_secrets, signed_in
from backend.auth import bp as auth_bp
from backend.config import DEFAULT_CONFIG_DIR, ConfigError, load_config
from backend.downtime import DowntimeStore
from backend.pickup_requests import PickupRequestStore
from backend.reviews import ReviewStore
from backend.repository import CsvRepository
from backend.repository.base import RepositoryError

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
DEFAULT_SESSION_HOURS = 12

log = logging.getLogger(__name__)


def create_app(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Flask:
    """
    Build the configured application.

    Parameters
    ----------
    config_dir
        The directory holding app.yaml, vehicles.yaml and stops.yaml, and
        the uncommitted secrets.yaml the admin sign-in reads (S13).

    Returns
    -------
    Flask
        With the repository and the config on `app.config` under
        `REPOSITORY` and `NUWAY_CONFIG`.

    Raises
    ------
    ConfigError, RepositoryError
        If the config files or the data directory cannot be used.
    """
    app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="")

    config = load_config(config_dir)
    app.config["NUWAY_CONFIG"] = config
    app.config["REPOSITORY"] = CsvRepository.from_config(config)
    app.config["PICKUP_REQUEST_STORE"] = PickupRequestStore()
    # if storage is unset /api/downtime then answers 500.
    app.config["DOWNTIME_STORE"] = (
        DowntimeStore(config.storage_directory / "downtime.json") if config.storage_directory else None
    )
    # Same storage.directory as downtime, its own file (if unset /api/reviews answers 500).
    app.config["REVIEW_STORE"] = (
        ReviewStore(config.storage_directory / "reviews.json") if config.storage_directory else None
    )

    secrets = load_secrets(config_dir)
    if secrets is None:
        log.warning("No %s/secrets.yaml: admin sign-in is disabled.", config_dir)
    else:
        app.secret_key = secrets.secret_key
    app.config["ADMIN_ACCOUNT"] = secrets.admin if secrets else None
    # Optional: only the dashboard's Earth view needs it (backend/api/earth.py).
    app.config["GOOGLE_MAPS_API_KEY"] = load_google_maps_key(config_dir)
    session_hours = (config.admin or {}).get("session_hours", DEFAULT_SESSION_HOURS)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=session_hours)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    app.register_blueprint(auth_bp)
    app.register_blueprint(positions_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(stops_bp)
    app.register_blueprint(pickup_requests_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(earth_bp)
    app.register_blueprint(downtime_bp)

    @app.get("/")
    def index():
        """
        The dashboard itself.
        """
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/admin")
    @admin_required
    def admin():
        return send_from_directory(FRONTEND, "admin.html")

    @app.get("/admin.html")
    def admin_file():
        """
        The static folder would otherwise serve the page itself here, around
        the sign-in on /admin.
        """
        return redirect("/admin")

    @app.get("/admin-login")
    def admin_login():
        if signed_in():
            return redirect("/admin")
        return send_from_directory(FRONTEND, "admin-login.html")

    @app.errorhandler(RepositoryError)
    @app.errorhandler(ConfigError)
    def unavailable(exc):
        """
        Storage or config failed under a request. Shape from docs/api.md.
        """
        return jsonify(error={"code": "data_unavailable", "message": str(exc)}), 500

    return app

if __name__ == "__main__":
    create_app().run(debug=True)
