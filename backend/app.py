"""
Run as `python -m backend.app`
"""

from __future__ import annotations
import logging
from datetime import timedelta
from pathlib import Path
from flask import Flask, jsonify, redirect, send_from_directory
from backend.api.downtime import bp as downtime_bp
from backend.api.metrics import bp as metrics_bp
from backend.api.pickup_requests import bp as pickup_requests_bp
from backend.api.schedule import bp as schedule_bp
from backend.api.positions import bp as positions_bp
from backend.api.stops import bp as stops_bp
from backend.api.vehicles import bp as vehicles_bp
from backend.auth import admin_required, load_secrets, signed_in
from backend.auth import bp as auth_bp
from backend.config import DEFAULT_CONFIG_DIR, ConfigError, load_config
from backend.pickup_requests import PickupRequestStore
from backend.repository import CsvRepository, DowntimeStore
from backend.repository.base import RepositoryError

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
DEFAULT_SESSION_HOURS = 12

log = logging.getLogger(__name__)


def create_app(config_dir: Path | str = DEFAULT_CONFIG_DIR, config=None) -> Flask:
    """
    Build the configured application.

    Parameters
    ----------
    config_dir : Path or str, optional
        The directory holding app.yaml, vehicles.yaml and stops.yaml, and
        the uncommitted secrets.yaml the admin sign-in reads (S13). Also
        where /api/schedule writes the service schedule back to, so a test
        that edits it should copy config/ first.
    config : backend.config.Config, optional
        Already loaded config, for a test that needs its own paths. None
        reads `config_dir` as usual. Pass it by name.

    Returns
    -------
    Flask
        With the repository, the downtime store and the config on
        `app.config` under `REPOSITORY`, `DOWNTIME_STORE` and `NUWAY_CONFIG`.

    Raises
    ------
    ConfigError, RepositoryError
        If the config files or the data directory cannot be used.
    """
    app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="")

    config_dir = Path(config_dir)
    config = load_config(config_dir) if config is None else config
    app.config["NUWAY_CONFIG"] = config
    app.config["NUWAY_CONFIG_DIR"] = config_dir
    app.config["NUWAY_CONFIG_PATH"] = config_dir / "app.yaml"
    app.config["REPOSITORY"] = CsvRepository.from_config(config)
    app.config["DOWNTIME_STORE"] = DowntimeStore.from_config(config)
    app.config["PICKUP_REQUEST_STORE"] = PickupRequestStore()

    secrets = load_secrets(config_dir)
    if secrets is None:
        log.warning("No %s/secrets.yaml: admin sign-in is disabled.", config_dir)
    else:
        app.secret_key = secrets.secret_key
    app.config["ADMIN_ACCOUNT"] = secrets.admin if secrets else None
    session_hours = (config.admin or {}).get("session_hours", DEFAULT_SESSION_HOURS)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=session_hours)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    app.register_blueprint(auth_bp)
    app.register_blueprint(positions_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(downtime_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(stops_bp)
    app.register_blueprint(pickup_requests_bp)

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
