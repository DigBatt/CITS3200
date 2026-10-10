"""
Run as `python -m backend.app`
"""

from __future__ import annotations
import logging
import os
from datetime import timedelta
from pathlib import Path
from dataclasses import replace

from flask import Flask, jsonify, redirect, send_from_directory
from backend.api.downtime import bp as downtime_bp
from backend.api.snapshot_settings import bp as snapshot_settings_bp
from backend.api.earth import bp as earth_bp, load_google_maps_key
from backend.api.metrics import bp as metrics_bp
from backend.api.operating import bp as operating_bp
from backend.api.pickup_requests import bp as pickup_requests_bp
from backend.api.schedule import bp as schedule_bp
from backend.api.positions import bp as positions_bp
from backend.api.reviews import bp as reviews_bp
from backend.api.network import bp as network_bp
from backend.api.stops import bp as stops_bp
from backend.api.vehicles import bp as vehicles_bp
from backend.compression import init_app as init_compression
from backend.auth import admin_required, load_secrets, signed_in
from backend.auth import bp as auth_bp
from backend.config import DEFAULT_CONFIG_DIR, ConfigError, load_config
from backend.downtime import DowntimeStore
from backend.operating_hours import OperatingHours, OperatingHoursError
from backend.path_network import FILE_NAME as PATHS_FILE, PathNetwork, PathNetworkError
from backend.pickup_requests import PickupRequestStore
from backend.reviews import ReviewStore
from backend.roster_sync import FILE_NAME as ROSTER_SYNC_FILE, RosterSync, SyncError, SyncSettings, SyncStore
from backend.repository import CsvRepository
from backend.snapshot_settings import SnapshotSettingsStore
from backend.stops import resolve_paths
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
    # The campus paths a route's legs follow (backend/path_network.py). Without
    # the snapshot every leg is a straight line, which still works.
    try:
        paths = PathNetwork.load(config_dir / PATHS_FILE)
    except PathNetworkError as exc:
        log.warning("%s; route legs will be straight lines.", exc)
        paths = None
    app.config["PATH_NETWORK"] = paths
    # Every route's legs given a path, so the map has one to draw even for a
    # route written by hand as a list of stops.
    config = replace(config, stops=resolve_paths(config.stops, paths))
    app.config["NUWAY_CONFIG"] = config
    app.config["NUWAY_CONFIG_DIR"] = config_dir
    app.config["NUWAY_CONFIG_PATH"] = config_dir / "app.yaml"
    app.config["REPOSITORY"] = CsvRepository.from_config(config)
    app.config["PICKUP_REQUEST_STORE"] = PickupRequestStore()
    # S15 follow-up: when riders may request a pickup at all (backend/operating_hours.py).
    try:
        app.config["OPERATING_HOURS"] = OperatingHours.from_config_block(
            (config.pickup_requests or {}).get("operating_hours")
        )
    except OperatingHoursError as exc:
        raise ConfigError(f"pickup_requests.operating_hours: {exc}") from exc
    # if storage is unset /api/downtime then answers 500.
    app.config["DOWNTIME_STORE"] = (
        DowntimeStore(config.storage_directory / "downtime.json") if config.storage_directory else None
    )
    # Same storage.directory as downtime, its own file (if unset /api/reviews answers 500).
    app.config["REVIEW_STORE"] = (
        ReviewStore(config.storage_directory / "reviews.json") if config.storage_directory else None
    )

    # S16: Persistent snapshot metric selection.
    app.config["SNAPSHOT_SETTINGS_STORE"] = (
        SnapshotSettingsStore(
            config.storage_directory,
            config.snapshot_default_metrics or [
                "asset_utilisation",
                "operating_efficiency",
                "effective_utilisation",
            ],
        )
        if config.storage_directory else None
    )

    # The driving roster synced from calendar.online (backend/roster_sync.py).
    # Its last good copy lives beside the downtime records. Built here but
    # only started by `start_roster_sync`, so a test app never touches the
    # network.
    try:
        sync_settings = SyncSettings.load(config, config_dir)
    except SyncError as exc:
        raise ConfigError(str(exc)) from exc
    if sync_settings and config.storage_directory:
        store = SyncStore(config.storage_directory / ROSTER_SYNC_FILE)
        app.config["ROSTER_SYNC_STORE"] = store
        app.config["ROSTER_SYNC"] = RosterSync(sync_settings, store, [v.id for v in config.vehicles])
    else:
        if sync_settings:
            log.warning("roster_sync is set but storage.directory is not: the roster will not sync.")
        app.config["ROSTER_SYNC_STORE"] = None
        app.config["ROSTER_SYNC"] = None

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
    app.register_blueprint(operating_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(stops_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(pickup_requests_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(earth_bp)
    # Gzip for JSON, scripts and styles: the 3D view's model above all.
    init_compression(app)
    app.register_blueprint(downtime_bp)
    app.register_blueprint(snapshot_settings_bp)

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


def start_roster_sync(app: Flask) -> None:
    """
    Start syncing the roster from calendar.online, when it is configured.

    Under the debug reloader the app is built twice, once in a watcher
    process that never serves; syncing only in the serving one keeps it to a
    single poller.
    """
    sync = app.config.get("ROSTER_SYNC")
    if sync is None:
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    sync.start()


if __name__ == "__main__":
    app = create_app()
    app.debug = True
    start_roster_sync(app)
    app.run(debug=True)
