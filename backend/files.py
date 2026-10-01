"""
Writing the JSON files kept under `storage.directory` in config/app.yaml.
"""

from __future__ import annotations
import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path | str, data: Any) -> None:
    """
    Replace `path` with `data` as JSON, all at once.

    Writes a temp file beside `path`, flushes it to disk, then renames it
    over `path`, so a reader or a crash mid-write sees the old file or the
    new one and never a partial one. Creates the parent directory if needed.

    Parameters
    ----------
    path : Path or str
    data : Any
        Anything `json.dump` accepts.

    Raises
    ------
    TypeError
        If `data` is not JSON serialisable. `path` is left untouched.
    OSError
        If the directory or file cannot be written. `path` is left untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
