"""
Run as `python -m backend.app`
"""

from __future__ import annotations
from pathlib import Path
from flask import Flask, jsonify, send_from_directory
from backend.api.downtime import bp as downtime_bp
from backend.api.metrics import bp as metrics_bp
from backend.api.schedule import bp as schedule_bp
from backend.api.positions import bp as positions_bp
from backend.api.vehicles import bp as vehicles_bp
from backend.config import DEFAULT_CONFIG_DIR, ConfigError, load_config
from backend.repository import CsvRepository, DowntimeStore
from backend.repository.base import RepositoryError

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def create_app(config=None, config_dir=DEFAULT_CONFIG_DIR) -> Flask:
    """
    Build the configured application.

    Parameters
    ----------
    config : backend.config.Config, optional
        Already loaded config, for a test that needs its own paths. None
        reads `config_dir` as usual.
    config_dir : Path or str, optional
        The config directory. Also where /api/schedule writes the service
        schedule back to, so a test that edits it should copy config/ first.

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

    app.register_blueprint(positions_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(downtime_bp)
    app.register_blueprint(schedule_bp)

    @app.get("/")
    def index():
        """
        The dashboard itself.
        """
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/admin")
    def admin():
        return send_from_directory(FRONTEND, "admin.html")

    @app.get("/admin-login")
    def admin_login():
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
