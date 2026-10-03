"""
Gzip for compressible responses.

Flask sends everything uncompressed, which matters most for the 3D view's bus
model (frontend/models/nuway.json, 2.8 MB of JSON, about 0.6 MB gzipped) and
for long /api/positions replies. This compresses a response when the browser
accepts gzip, the body is of a type that compresses well and is big enough to
be worth it.

Files (static files, and the pages sent with send_from_directory) are
compressed once and kept, keyed by their path and ETag: the ETag changes with
the file's modification time and size, so an edited file is compressed afresh
and a stale copy can never be served. Everything else, such as API JSON, is
compressed as it goes out.

Left alone: responses that are not 200, already encoded, partial (Range), or
carry no body (304). Every response that could have been compressed says
`Vary: Accept-Encoding`, so a cache keeps the two forms apart.

A gzipped file goes out tagged `<ETag>-gzip`, and the browser sends that tag
back to revalidate. It is turned back into the file's own tag before Flask
compares them, so an unchanged file still answers 304 rather than resending.
"""

from __future__ import annotations

import gzip
import threading
from collections import OrderedDict

from flask import Flask, Response, request

#: Below this a gzip header and the CPU cost outweigh the saving.
MIN_BYTES = 1024
LEVEL = 6
COMPRESSIBLE = (
    "application/json",
    "application/javascript",
    "text/javascript",
    "text/css",
    "text/html",
    "text/plain",
    "image/svg+xml",
)
#: Compressed files kept in memory, most recently used last. Enough for the
#: frontend's files many times over; the model is the only large one.
MAX_CACHED_FILES = 64


class _FileCache:
    def __init__(self, limit: int):
        self._items: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key, value: bytes) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)


def _accepts_gzip() -> bool:
    for part in request.headers.get("Accept-Encoding", "").split(","):
        coding, _, params = part.strip().partition(";")
        if coding.strip().lower() in ("gzip", "*"):
            # "gzip;q=0" is a refusal.
            return params.replace(" ", "") != "q=0"
    return False


SUFFIX = "-gzip"


def init_app(app: Flask) -> None:
    """Compress what is worth compressing on every response from `app`."""
    cache = _FileCache(MAX_CACHED_FILES)

    @app.before_request
    def plain_etags():
        # Revalidating a gzipped copy: compare against the file's own tag.
        tags = request.environ.get("HTTP_IF_NONE_MATCH")
        if tags and SUFFIX in tags:
            request.environ["HTTP_IF_NONE_MATCH"] = tags.replace(f'{SUFFIX}"', '"')

    @app.after_request
    def compress(response: Response) -> Response:
        if response.mimetype not in COMPRESSIBLE:
            return response
        response.vary.add("Accept-Encoding")

        etag, weak = response.get_etag()
        if response.status_code == 304:
            # Not modified: still name the gzipped copy the browser holds.
            if etag is not None and _accepts_gzip():
                response.set_etag(f"{etag}{SUFFIX}", weak=weak)
            return response

        if (
            response.status_code != 200
            or "Content-Encoding" in response.headers
            or "Content-Range" in response.headers
            or request.method == "HEAD"
            or not _accepts_gzip()
        ):
            return response

        is_file = response.direct_passthrough and etag is not None
        key = (request.path, etag) if is_file else None

        body = cache.get(key) if key else None
        if body is not None:
            # Served from the cache: the file was opened to stream it, and
            # replacing the body would otherwise leave it open.
            close = getattr(response.response, "close", None)
            if close:
                close()
        else:
            # A file response streams from disk; read it so it can be compressed.
            response.direct_passthrough = False
            data = response.get_data()
            if len(data) < MIN_BYTES:
                return response
            body = gzip.compress(data, compresslevel=LEVEL, mtime=0)
            if key:
                cache.put(key, body)

        response.direct_passthrough = False
        response.set_data(body)
        response.headers["Content-Encoding"] = "gzip"
        if etag is not None:
            # A different representation of the same resource needs its own tag.
            response.set_etag(f"{etag}{SUFFIX}", weak=weak)
        return response
