"""
Run as `python -m backend.app`
"""

from __future__ import annotations
from pathlib import Path
from flask import Flask, jsonify, send_from_directory
from backend.api.positions import bp as positions_bp
from backend.config import ConfigError, load_config
from backend.repository import CsvRepository
from backend.repository.base import RepositoryError

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def create_app() -> Flask:
    """
    Build the configured application.

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

    config = load_config()
    app.config["NUWAY_CONFIG"] = config
    app.config["REPOSITORY"] = CsvRepository.from_config(config)

    app.register_blueprint(positions_bp)

    @app.get("/")
    def index():
        """
        The dashboard itself.
        """
        return send_from_directory(FRONTEND, "index.html")

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
