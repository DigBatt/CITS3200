"""
A test admin account (S13) for tests whose endpoints need signing in.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

import yaml
from werkzeug.security import generate_password_hash

from backend.schedule import DAYS

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "test-password"

# Few iterations, so the many sign-ins across the suite stay fast.
_HASH = generate_password_hash(ADMIN_PASSWORD, method="pbkdf2:sha256:1000")


def write_admin_secrets(config_dir: Path) -> None:
    """
    Write a secrets.yaml holding the test account into a test's config directory.
    """
    secrets = {
        "secret_key": "test-secret-key",
        "admin": {"username": ADMIN_USERNAME, "password_hash": _HASH},
    }
    (Path(config_dir) / "secrets.yaml").write_text(yaml.safe_dump(secrets), encoding="utf-8")


def sign_in(client):
    """
    Sign a Flask test client in as the test admin. Returns the client.
    """
    response = client.post("/api/admin/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.get_json()
    return client


#: Every day, wide open, so widening a copied app.yaml to this makes
#: POST /api/pickup-requests succeed no matter the real time a test happens
#: to run at (backend/operating_hours.py). The sample config's own hours are
#: realistic office hours, which is the opposite of what most tests want.
_ALL_DAY = ["00:00", "23:59"]


def allow_pickup_requests_any_time(config_dir: Path, app_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Widen `pickup_requests.operating_hours` in a test's app.yaml to every day,
    all day. For a test exercising POST /api/pickup-requests (or anything
    downstream of it) that is not itself testing the operating hours gate.

    Parameters
    ----------
    config_dir : Path
        Directory holding the test's own app.yaml, already copied from
        config/.
    app_config : dict, optional
        The already loaded app.yaml, if the caller has one in hand (and will
        write it back itself). None reads and writes the file directly.

    Returns
    -------
    dict
        The updated app.yaml content, in case the caller wants to make
        further changes before writing it.
    """
    path = Path(config_dir) / "app.yaml"
    config = app_config if app_config is not None else yaml.safe_load(path.read_text(encoding="utf-8"))
    config.setdefault("pickup_requests", {})["operating_hours"] = {day: _ALL_DAY for day in DAYS}
    if app_config is None:
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config
