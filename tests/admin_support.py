"""
A test admin account (S13) for tests whose endpoints need signing in.
"""

from __future__ import annotations
from pathlib import Path

import yaml
from werkzeug.security import generate_password_hash

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
