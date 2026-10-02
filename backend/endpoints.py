"""
backend/endpoints.yaml: the listen address and the public URLs (ngrok) that
reach this app. Served at GET /api/endpoints.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from backend.config import ConfigError

DEFAULT_ENDPOINTS_PATH = Path(__file__).resolve().parent / "endpoints.yaml"

#: What the file may name under `public`. Anything else is a typo.
PUBLIC_NAMES = ("api", "dashboard", "metro")


@dataclass(frozen=True)
class Endpoints:
    host: str = "127.0.0.1"
    port: int = 5000
    public: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listen": {"host": self.host, "port": self.port},
            "public": {name: self.public.get(name) for name in PUBLIC_NAMES},
        }


def load_endpoints(path: Path | str | None = DEFAULT_ENDPOINTS_PATH) -> Endpoints:
    """
    Read the mapping file. A missing file is the defaults; a malformed one
    raises ConfigError naming every bad entry.

    Parameters
    ----------
    path
        The YAML file, or None for the defaults without touching disk.
    """
    if path is None:
        return Endpoints()
    path = Path(path)
    if not path.exists():
        return Endpoints()

    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc

    problems: list[str] = []
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")

    unknown = set(raw) - {"listen", "public"}
    if unknown:
        problems.append(f"unknown key(s): {', '.join(sorted(unknown))}")

    listen = raw.get("listen") or {}
    if not isinstance(listen, dict):
        problems.append("listen: expected a mapping")
        listen = {}
    host = listen.get("host", "127.0.0.1")
    port = listen.get("port", 5000)
    if not isinstance(host, str) or not host:
        problems.append(f"listen.host: expected text, got {host!r}")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        problems.append(f"listen.port: expected an integer from 1 to 65535, got {port!r}")

    public_raw = raw.get("public") or {}
    public: dict[str, str] = {}
    if not isinstance(public_raw, dict):
        problems.append("public: expected a mapping")
    else:
        for name, url in public_raw.items():
            if name not in PUBLIC_NAMES:
                problems.append(f"public.{name}: unknown name, expected one of {', '.join(PUBLIC_NAMES)}")
            elif url is None:
                continue
            elif not isinstance(url, str) or not url.startswith(("http://", "https://")):
                problems.append(f"public.{name}: expected a URL starting with http:// or https://, got {url!r}")
            else:
                public[name] = url.rstrip("/")

    if problems:
        raise ConfigError("\n".join(f"{path}: {problem}" for problem in problems))
    return Endpoints(host=host, port=port, public=public)
