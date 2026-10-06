"""
Administrator sign-in (S13): backend.auth, the /api/admin endpoints, and
which pages and endpoints need signing in.
"""

from __future__ import annotations
import shutil
from datetime import timedelta

import pytest

from backend.app import create_app
from backend.auth import load_secrets
from backend.config import DEFAULT_CONFIG_DIR, ConfigError
from tests.admin_support import ADMIN_PASSWORD, ADMIN_USERNAME, sign_in, write_admin_secrets

# Admin-only endpoints, as (method, path, body). body is None for a GET.
ADMIN_ENDPOINTS = [
    ("GET", "/api/pickup-requests", None),
    ("GET", "/api/routes/full-campus-loop/waiting", None),
    ("POST", "/api/stops/reid-library/collect", {"vehicle_id": "1", "route_id": "full-campus-loop"}),
    ("GET", "/api/reviews", None),
]


@pytest.fixture
def config_dir(tmp_path):
    for name in ("app.yaml", "vehicles.yaml", "stops.json"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    write_admin_secrets(tmp_path)
    return tmp_path


@pytest.fixture
def app(config_dir):
    return create_app(config_dir)


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/admin/login", json={"username": username, "password": password})


# ---- Criterion 1: signed out, no admin function is reachable ----


def test_admin_page_redirects_to_sign_in(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert response.headers["Location"] == "/admin-login?next=%2Fadmin"


def test_redirect_keeps_the_operator_selection(client):
    response = client.get("/admin?vehicle=1&route=full-campus-loop")
    assert response.headers["Location"] == "/admin-login?next=%2Fadmin%3Fvehicle%3D1%26route%3Dfull-campus-loop"


def test_admin_html_cannot_be_fetched_around_the_sign_in(client):
    response = client.get("/admin.html")
    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ENDPOINTS)
def test_admin_endpoints_are_401_signed_out(client, method, path, body):
    response = client.open(path, method=method, json=body)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "not_signed_in"


# ---- Criterion 2: the admin account reaches the admin page ----


def test_right_credentials_sign_in(client):
    response = login(client)
    assert response.status_code == 200
    assert client.get("/api/admin/me").get_json() == {"signed_in": True}
    assert client.get("/admin").status_code == 200


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ENDPOINTS)
def test_admin_endpoints_work_signed_in(client, method, path, body):
    sign_in(client)
    assert client.open(path, method=method, json=body).status_code == 200


@pytest.mark.parametrize(
    ("username", "password"),
    [(ADMIN_USERNAME, "wrong"), ("someone", ADMIN_PASSWORD), (ADMIN_USERNAME, ""), ("", "")],
)
def test_wrong_credentials_are_401(client, username, password):
    response = login(client, username, password)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "bad_credentials"
    assert client.get("/api/admin/me").get_json() == {"signed_in": False}


def test_malformed_login_body_is_401(client):
    response = client.post("/api/admin/login", json={"username": 1, "password": None})
    assert response.status_code == 401
    assert client.post("/api/admin/login", data="not json").status_code == 401


def test_sign_in_page_sends_a_signed_in_admin_to_the_admin_page(client):
    assert client.get("/admin-login").status_code == 200
    sign_in(client)
    response = client.get("/admin-login")
    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"


def test_logout_ends_the_session(client):
    sign_in(client)
    client.post("/api/admin/logout")
    assert client.get("/api/admin/me").get_json() == {"signed_in": False}
    assert client.get("/admin").status_code == 302


def test_session_lasts_the_configured_hours(app):
    assert app.permanent_session_lifetime == timedelta(hours=12)


# ---- Criterion 3: the rider view needs no sign-in ----


def test_rider_endpoints_need_no_sign_in(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/stops").status_code == 200
    assert client.get("/api/routes").status_code == 200
    assert client.post("/api/pickup-requests", json={"stop_id": "reid-library"}).status_code == 201


# ---- secrets.yaml ----


def test_without_secrets_the_app_runs_but_no_one_can_sign_in(config_dir):
    (config_dir / "secrets.yaml").unlink()
    client = create_app(config_dir).test_client()

    assert client.get("/api/stops").status_code == 200
    response = login(client)
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "admin_not_configured"
    assert client.get("/admin").status_code == 302


def test_incomplete_secrets_file_is_a_config_error(config_dir):
    (config_dir / "secrets.yaml").write_text("secret_key: abc\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="secrets.yaml"):
        load_secrets(config_dir)


def test_example_secrets_file_has_every_key():
    """
    Copying the committed example and filling it in must give a usable file.
    """
    example = (DEFAULT_CONFIG_DIR / "secrets.example.yaml").read_text(encoding="utf-8")
    for key in ("secret_key:", "admin:", "username:", "password_hash:"):
        assert key in example
