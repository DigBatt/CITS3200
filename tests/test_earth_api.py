"""
/api/earth: the Earth view is available only with a Google Maps API key in
secrets.yaml, and says why when it is not.
"""

from __future__ import annotations
import shutil

import pytest

from backend.api.earth import load_google_maps_key
from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR, ConfigError

SECRETS = """secret_key: test-only
admin:
  username: admin
  password_hash: "scrypt:32768:8:1$x$y"
"""


def config_dir_with(tmp_path, secrets_text):
    config_dir = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config_dir)
    secrets = config_dir / "secrets.yaml"
    if secrets_text is None:
        secrets.unlink(missing_ok=True)
    else:
        secrets.write_text(secrets_text, encoding="utf-8")
    return config_dir


def earth(config_dir):
    app = create_app(config_dir=config_dir)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/api/earth")
    assert response.status_code == 200
    return response.get_json()


def test_available_with_a_key(tmp_path):
    body = earth(config_dir_with(tmp_path, SECRETS + "google_maps_api_key: abc123\n"))
    assert body == {"available": True, "api_key": "abc123"}


@pytest.mark.parametrize(
    "secrets_text",
    [None, SECRETS, SECRETS + "google_maps_api_key: ''\n", SECRETS + "google_maps_api_key: REPLACE_ME\n"],
    ids=["no-secrets-file", "no-key", "blank-key", "placeholder-key"],
)
def test_unavailable_without_a_usable_key_says_why(tmp_path, secrets_text):
    body = earth(config_dir_with(tmp_path, secrets_text))
    assert body["available"] is False
    assert body["api_key"] is None
    assert "google_maps_api_key" in body["reason"]


def test_a_key_that_is_not_text_is_a_config_error(tmp_path):
    config_dir = config_dir_with(tmp_path, SECRETS + "google_maps_api_key: [1, 2]\n")
    with pytest.raises(ConfigError):
        load_google_maps_key(config_dir)


def test_the_key_is_trimmed(tmp_path):
    config_dir = config_dir_with(tmp_path, SECRETS + "google_maps_api_key: '  abc123  '\n")
    assert load_google_maps_key(config_dir) == "abc123"
