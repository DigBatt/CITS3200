from __future__ import annotations
import hmac
import logging
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import yaml
from flask import Blueprint, current_app, jsonify, redirect, request, session
from werkzeug.security import check_password_hash

from backend.config import ConfigError

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)

SECRETS_FILE = "secrets.yaml"
SESSION_FLAG = "admin"


@dataclass(frozen=True)
class AdminAccount:
    username: str
    password_hash: str

    def check(self, username: str, password: str) -> bool:
        username_ok = hmac.compare_digest(username.encode(), self.username.encode())
        password_ok = check_password_hash(self.password_hash, password)
        return username_ok and password_ok


@dataclass(frozen=True)
class Secrets:
    secret_key: str
    admin: AdminAccount


def load_secrets(config_dir: Path | str) -> Optional[Secrets]:
    """
    Read secrets.yaml from the config directory.

    Returns
    -------
    Secrets, or None if the file does not exist.

    Raises
    ------
    ConfigError
        If the file exists but is missing a value.
    """
    path = Path(config_dir) / SECRETS_FILE
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        admin = raw.get("admin") or {}
        secrets = Secrets(
            secret_key=str(raw["secret_key"]),
            admin=AdminAccount(username=str(admin["username"]), password_hash=str(admin["password_hash"])),
        )
    except (OSError, yaml.YAMLError, AttributeError, KeyError) as exc:
        raise ConfigError(f"Could not read {path}: missing or invalid {exc}") from exc
    if not all([secrets.secret_key, secrets.admin.username, secrets.admin.password_hash]):
        raise ConfigError(f"{path} has an empty secret_key, admin.username or admin.password_hash")
    return secrets


def _account() -> Optional[AdminAccount]:
    return current_app.config.get("ADMIN_ACCOUNT")


def signed_in() -> bool:
    return bool(session.get(SESSION_FLAG))


def admin_required(view):
    """
    Close a view to anyone not signed in: `401` for an API endpoint, a
    redirect to the sign-in page for a page, which returns here afterwards.
    """

    @wraps(view)
    def guarded(*args, **kwargs):
        if signed_in():
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "not_signed_in", "message": "Sign in as the administrator first."}}), 401
        next_path = request.full_path.rstrip("?")
        return redirect(f"/admin-login?{urlencode({'next': next_path})}")

    return guarded


@bp.post("/api/admin/login")
def login():
    """
    Body: `{"username": "...", "password": "..."}`.

    `200` and a session cookie on the right credentials, `401`
    `bad_credentials` otherwise, `503` `admin_not_configured` if there is no
    secrets.yaml.
    """
    account = _account()
    if account is None:
        message = "Admin sign-in is not set up: create config/secrets.yaml from config/secrets.example.yaml."
        return jsonify({"error": {"code": "admin_not_configured", "message": message}}), 503

    body = request.get_json(silent=True) or {}
    username, password = body.get("username"), body.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not account.check(username, password):
        return jsonify({"error": {"code": "bad_credentials", "message": "Incorrect username or password."}}), 401

    session.clear()
    session[SESSION_FLAG] = True
    session.permanent = True
    return jsonify({"signed_in": True})


@bp.post("/api/admin/logout")
def logout():
    session.clear()
    return jsonify({"signed_in": False})


@bp.get("/api/admin/me")
def me():
    """
    Whether this browser is signed in. Always `200`, so the page can ask
    without triggering its own not-signed-in handling.
    """
    return jsonify({"signed_in": signed_in()})
