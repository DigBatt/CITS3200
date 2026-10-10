
"""Storage for daily metric snapshots (S17)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from backend.files import write_json_atomic


class SnapshotStore:
    """Persist one daily snapshot per Perth calendar date."""

    def __init__(self, storage_directory: Path):
        self.directory = Path(storage_directory) / "snapshots"

    def path_for(self, day: date) -> Path:
        return self.directory / f"{day.isoformat()}.json"

    def exists(self, day: date) -> bool:
        return self.path_for(day).is_file()

    def save(self, day: date, snapshot: dict[str, Any]) -> None:
        """Save a snapshot without overwriting an existing day."""
        path = self.path_for(day)

        if path.exists():
            raise FileExistsError(f"Snapshot already exists for {day}")

        write_json_atomic(path, snapshot)

    def load(self, day: date) -> dict[str, Any]:
        """Load an existing snapshot."""
        with self.path_for(day).open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            raise ValueError("Invalid snapshot file.")

        return data

    def list_dates(self) -> list[date]:
        """List stored snapshot dates, newest first."""
        if not self.directory.exists():
            return []

        dates = []

        for path in self.directory.glob("*.json"):
            try:
                dates.append(date.fromisoformat(path.stem))
            except ValueError:
                continue

        return sorted(dates, reverse=True)
