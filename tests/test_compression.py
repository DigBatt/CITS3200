"""
backend/compression.py: gzip for compressible responses, the 3D view's bus
model above all, without breaking revalidation, ranges or anything binary.
"""

from __future__ import annotations
import gzip
import os
import shutil
from pathlib import Path

import pytest

import backend.app as app_module
from backend.app import create_app

FRONTEND = Path(app_module.__file__).resolve().parent.parent / "frontend"
MODEL = "/models/nuway.json"
GZIP = {"Accept-Encoding": "gzip, deflate, br"}


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_the_bus_model_is_gzipped_and_unpacks_to_the_file(client):
    response = client.get(MODEL, headers=GZIP)
    assert response.status_code == 200
    assert response.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["Vary"]
    body = response.get_data()
    assert int(response.headers["Content-Length"]) == len(body)
    original = (FRONTEND / "models" / "nuway.json").read_bytes()
    assert gzip.decompress(body) == original
    assert len(body) < len(original) / 3, "the model should compress well"


def test_a_second_request_is_served_from_the_cache_unchanged(client):
    first = client.get(MODEL, headers=GZIP).get_data()
    second = client.get(MODEL, headers=GZIP).get_data()
    assert first == second


@pytest.mark.parametrize("accept", [None, "identity", "gzip;q=0", "br"])
def test_sent_plain_to_a_client_that_does_not_take_gzip(client, accept):
    headers = {"Accept-Encoding": accept} if accept else {}
    response = client.get(MODEL, headers=headers)
    assert "Content-Encoding" not in response.headers
    assert response.get_data() == (FRONTEND / "models" / "nuway.json").read_bytes()


def test_unchanged_file_still_revalidates_to_304(client):
    first = client.get(MODEL, headers=GZIP)
    etag = first.headers["ETag"]
    assert etag.endswith('-gzip"')

    again = client.get(MODEL, headers={**GZIP, "If-None-Match": etag})
    assert again.status_code == 304
    assert again.get_data() == b""
    assert again.headers["ETag"] == etag


def test_range_requests_are_left_alone(client):
    response = client.get(MODEL, headers={**GZIP, "Range": "bytes=0-99"})
    assert response.status_code == 206
    assert "Content-Encoding" not in response.headers
    assert len(response.get_data()) == 100


def test_api_json_is_compressed(client):
    response = client.get("/api/positions", query_string={"from": "2025-09-04", "to": "2025-09-04"}, headers=GZIP)
    assert response.headers["Content-Encoding"] == "gzip"
    assert b'"vehicles"' in gzip.decompress(response.get_data())


def test_small_responses_are_not_worth_compressing(client):
    response = client.get("/api/admin/me", headers=GZIP)
    assert "Content-Encoding" not in response.headers


def test_binary_files_are_left_alone(tmp_path, monkeypatch):
    # An image in a scratch frontend: compressible by size, but not by type.
    frontend = tmp_path / "frontend"
    (frontend / "img").mkdir(parents=True)
    (frontend / "img" / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(4096))
    monkeypatch.setattr(app_module, "FRONTEND", frontend)
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/img/photo.png", headers=GZIP)
    assert response.status_code == 200
    assert "Content-Encoding" not in response.headers


def test_an_edited_file_is_compressed_afresh(tmp_path, monkeypatch):
    # A copy of the frontend, so the test can edit a file safely.
    frontend = tmp_path / "frontend"
    shutil.copytree(FRONTEND / "js", frontend / "js")
    target = frontend / "js" / "api.js"
    monkeypatch.setattr(app_module, "FRONTEND", frontend)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        before = gzip.decompress(client.get("/js/api.js", headers=GZIP).get_data())
        target.write_text(target.read_text() + "\n// edited\n")
        stat = target.stat()
        os.utime(target, (stat.st_atime, stat.st_mtime + 5))  # a new mtime, so a new ETag
        after = gzip.decompress(client.get("/js/api.js", headers=GZIP).get_data())

    assert before != after
    assert after.endswith(b"// edited\n")
