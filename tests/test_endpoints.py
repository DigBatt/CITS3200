"""backend/endpoints.yaml: the loader, GET /api/endpoints, and the proxy headers."""

from __future__ import annotations
import shutil

import pytest

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR, ConfigError
from backend.endpoints import Endpoints, load_endpoints

VALID = """
listen:
  host: 0.0.0.0
  port: 5001
public:
  api: https://nuway-api.ngrok.app/
  dashboard: https://nuway-dashboard.ngrok.app
  metro: null
"""


@pytest.fixture
def config_dir(tmp_path):
    target = tmp_path / "config"
    target.mkdir()
    for name in ("app.yaml", "vehicles.yaml", "stops.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, target / name)
    return target


def test_missing_file_is_the_defaults(tmp_path):
    assert load_endpoints(tmp_path / "nope.yaml") == Endpoints()
    assert load_endpoints(None) == Endpoints()
    assert Endpoints().to_dict() == {
        "listen": {"host": "127.0.0.1", "port": 5000},
        "public": {"api": None, "dashboard": None, "metro": None},
    }


def test_valid_file_is_parsed_and_urls_are_trimmed(tmp_path):
    path = tmp_path / "endpoints.yaml"
    path.write_text(VALID, encoding="utf-8")
    loaded = load_endpoints(path)
    assert loaded.host == "0.0.0.0"
    assert loaded.port == 5001
    assert loaded.public == {
        "api": "https://nuway-api.ngrok.app",
        "dashboard": "https://nuway-dashboard.ngrok.app",
    }


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("listen:\n  port: 70000\n", "listen.port"),
        ("listen:\n  port: true\n", "listen.port"),
        ("listen:\n  host: ''\n", "listen.host"),
        ("public:\n  admin: https://x\n", "public.admin: unknown name"),
        ("public:\n  api: nuway-api.ngrok.app\n", "public.api: expected a URL"),
        ("listen: 5\n", "listen: expected a mapping"),
        ("tunnels: {}\n", "unknown key.s.: tunnels"),
    ],
)
def test_bad_files_are_rejected_naming_the_entry(tmp_path, text, fragment):
    path = tmp_path / "endpoints.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=fragment):
        load_endpoints(path)


def test_every_problem_is_listed_at_once(tmp_path):
    path = tmp_path / "endpoints.yaml"
    path.write_text("listen:\n  port: 0\npublic:\n  api: 5\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_endpoints(path)
    assert "listen.port" in str(caught.value)
    assert "public.api" in str(caught.value)


def test_endpoints_route_serves_the_mapping(config_dir, tmp_path):
    path = tmp_path / "endpoints.yaml"
    path.write_text(VALID, encoding="utf-8")
    client = create_app(config_dir, endpoints_path=path).test_client()

    body = client.get("/api/endpoints").get_json()

    assert body == {
        "listen": {"host": "0.0.0.0", "port": 5001},
        "public": {
            "api": "https://nuway-api.ngrok.app",
            "dashboard": "https://nuway-dashboard.ngrok.app",
            "metro": None,
        },
    }


def test_endpoints_route_without_a_file_reports_defaults(config_dir):
    client = create_app(config_dir, endpoints_path=None).test_client()
    body = client.get("/api/endpoints").get_json()
    assert body["public"] == {"api": None, "dashboard": None, "metro": None}


def test_rider_cookie_is_secure_only_behind_https(config_dir):
    client = create_app(config_dir, endpoints_path=None).test_client()

    plain = client.post("/api/pickup-requests", json={"stop_id": "reid-library"})
    assert plain.status_code == 201
    assert "Secure" not in plain.headers["Set-Cookie"]

    # A fresh rider, arriving through the ngrok tunnel.
    tunnelled = create_app(config_dir, endpoints_path=None).test_client().post(
        "/api/pickup-requests",
        json={"stop_id": "reid-library"},
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "nuway-api.ngrok.app"},
    )
    assert tunnelled.status_code == 201
    assert "Secure" in tunnelled.headers["Set-Cookie"]
