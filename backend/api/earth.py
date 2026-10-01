"""
GET /api/earth: whether the dashboard's Earth view can run, and the key it
needs.

The Earth view (frontend/js/earth3d.js) draws Google's photorealistic 3D tiles,
which need a Google Maps Platform API key with the Map Tiles API enabled. The
key is optional and lives in the uncommitted config/secrets.yaml as
`google_maps_api_key`; without it the rest of the dashboard, the 3D campus
view included, runs as normal and only Earth is unavailable.

The key is handed to the browser because the browser fetches the tiles with
it; there is no way to use it without the page seeing it. It must therefore
be restricted in the Google Cloud console, to this site's address and to the
Map Tiles API, so that a copy is no use anywhere else.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

import yaml
from flask import Blueprint, current_app, jsonify

from backend.config import ConfigError

bp = Blueprint("earth", __name__)

SECRETS_FILE = "secrets.yaml"
KEY_NAME = "google_maps_api_key"


def load_google_maps_key(config_dir: Path | str) -> Optional[str]:
    """
    The Google Maps API key from secrets.yaml.

    Returns
    -------
    str or None
        None when there is no secrets.yaml, or it sets no key or a blank one.

    Raises
    ------
    ConfigError
        If secrets.yaml exists but is not valid YAML, or the key is not text.
    """
    path = Path(config_dir) / SECRETS_FILE
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    key = raw.get(KEY_NAME) if isinstance(raw, dict) else None
    if key is None:
        return None
    if not isinstance(key, str):
        raise ConfigError(f"{path}: {KEY_NAME} must be text")
    key = key.strip()
    return key if key and key != "REPLACE_ME" else None


@bp.get("/api/earth")
def earth():
    """
    Always `200`. `{"available": true, "api_key": "..."}` when a key is set,
    otherwise `{"available": false, "api_key": null, "reason": "..."}`, so the
    page can say why the Earth view is off rather than failing to load it.
    """
    key = current_app.config.get("GOOGLE_MAPS_API_KEY")
    if not key:
        return jsonify(
            {
                "available": False,
                "api_key": None,
                "reason": f"Needs a Google Maps API key: set {KEY_NAME} in config/secrets.yaml.",
            }
        )
    return jsonify({"available": True, "api_key": key})
