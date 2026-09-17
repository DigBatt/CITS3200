"""
One HTTP GET to a source endpoint, decoded as JSON.
"""

from __future__ import annotations
import json
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MAX_BODY_BYTES = 64 * 1024

class FetchError(Exception):
    """
    The endpoint did not give us a JSON body.
    """


def fetch_json(url: str, user_agent: str, timeout: float) -> Any:
    """
    GET a URL and decode its JSON body.

    Parameters
    ----------
    url : str
    user_agent : str
        Sent as-is. The REV server answers 406 to non-browser agents.
    timeout : float
        Seconds, for the connection and for each read.

    Returns
    -------
    Any
        The decoded body.

    Raises
    ------
    FetchError
        On any network failure, a non-2xx status, a body that is not
        `application/json`, a body over MAX_BODY_BYTES, or invalid JSON.
    """
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            body = response.read(MAX_BODY_BYTES + 1)
    except HTTPError as exc:
        raise FetchError(f"{url}: HTTP {exc.code}") from exc
    except (OSError, HTTPException) as exc:  # URLError, timeouts, resets, TLS
        raise FetchError(f"{url}: {exc}") from exc

    if content_type != "application/json" and not content_type.endswith("+json"):
        raise FetchError(f"{url}: expected JSON, got {content_type}")
    if len(body) > MAX_BODY_BYTES:
        raise FetchError(f"{url}: response larger than {MAX_BODY_BYTES} bytes")
    try:
        return json.loads(body)
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError both
        raise FetchError(f"{url}: invalid JSON: {exc}") from exc
