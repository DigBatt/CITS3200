"""
backend.ingest.fetch, against a local HTTP server.
"""

from __future__ import annotations
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.ingest.fetch import MAX_BODY_BYTES, FetchError, fetch_json

UA = "Mozilla/5.0 test"
SNAPSHOT = b'{"lat":-31.98,"lon":115.82,"heading":0,"battery_percentage":0,"timestamp":1787918898}'
NOT_FOUND = b"<html><head><title>404 Not Found</title></head><body>Not Found</body></html>"

ROUTES = {
    "/json": (200, "application/json", SNAPSHOT),
    "/json-charset": (200, "application/json; charset=utf-8", SNAPSHOT),
    "/problem": (200, "application/problem+json", b'{"ok":false}'),
    "/html-404": (404, "text/html", NOT_FOUND),
    "/html-200": (200, "text/html", NOT_FOUND),
    "/bad-json": (200, "application/json", b'{"lat":'),
    "/bad-utf8": (200, "application/json", b'{"a":"\xff"}'),
    "/big": (200, "application/json", b'"' + b"x" * MAX_BODY_BYTES + b'"'),
    "/error": (500, "text/plain", b"boom"),
}


class Handler(BaseHTTPRequestHandler):
    seen_agents: list[str] = []

    def do_GET(self):
        Handler.seen_agents.append(self.headers.get("User-Agent"))
        if self.path == "/slow":
            time.sleep(1.0)
            status, content_type, body = ROUTES["/json"]
        else:
            status, content_type, body = ROUTES.get(self.path, (404, "text/html", NOT_FOUND))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_decodes_json(server):
    assert fetch_json(f"{server}/json", UA, 5)["timestamp"] == 1787918898


@pytest.mark.parametrize("path", ["/json-charset", "/problem"])
def test_accepts_json_content_types(server, path):
    assert isinstance(fetch_json(f"{server}{path}", UA, 5), dict)


def test_sends_the_user_agent(server):
    Handler.seen_agents.clear()
    fetch_json(f"{server}/json", UA, 5)
    assert Handler.seen_agents == [UA]


@pytest.mark.parametrize(
    "path, message",
    [
        ("/html-404", "HTTP 404"),
        ("/error", "HTTP 500"),
        ("/html-200", "expected JSON, got text/html"),
        ("/bad-json", "invalid JSON"),
        ("/bad-utf8", "invalid JSON"),
        ("/big", "larger than"),
    ],
)
def test_bad_responses_raise(server, path, message):
    with pytest.raises(FetchError, match=message):
        fetch_json(f"{server}{path}", UA, 5)


def test_timeout_raises(server):
    started = time.monotonic()
    with pytest.raises(FetchError):
        fetch_json(f"{server}/slow", UA, 0.2)
    assert time.monotonic() - started < 0.9


def test_refused_connection_raises():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(FetchError):
        fetch_json(f"http://127.0.0.1:{port}/json", UA, 2)


def test_bad_url_raises():
    with pytest.raises(FetchError):
        fetch_json("http://nonexistent.invalid/json", UA, 2)
