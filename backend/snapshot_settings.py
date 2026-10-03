
"""Persistent metric selection for daily snapshots (S16)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.files import write_json_atomic


# Metrics currently supported by the TUM calculation.
AVAILABLE_METRICS = {
    "asset_utilisation": "Asset utilisation",
    "operating_efficiency": "Operating efficiency",
    "effective_utilisation": "Effective utilisation",
}


class SnapshotSettingsStore:
    """Read and save the administrator's snapshot metric selection."""

    def __init__(self, storage_directory: Path, default_metrics: list[str]):
        self.path = Path(storage_directory) / "snapshot_settings.json"
        self.default_metrics = self.validate(default_metrics)

    @staticmethod
    def validate(metrics: list[str]) -> list[str]:
        """Validate metric names and reject duplicate or unsupported values."""

        if not isinstance(metrics, list):
            raise ValueError("Metrics must be a list.")

        if not metrics:
            raise ValueError("Select at least one metric.")

        if any(
            not isinstance(metric, str) or metric not in AVAILABLE_METRICS
            for metric in metrics
        ):
            raise ValueError("One or more metrics are not supported.")

        if len(metrics) != len(set(metrics)):
            raise ValueError("Duplicate metrics are not allowed.")

        return list(metrics)

    def load(self) -> list[str]:
        """Return saved metrics, or configured defaults if no file exists."""

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return list(self.default_metrics)

        if not isinstance(data, dict):
            raise ValueError("Invalid snapshot settings file.")

        return self.validate(data.get("metrics"))

    def save(self, metrics: list[str]) -> list[str]:
        """Validate and atomically persist the selected metrics."""

        selected = self.validate(metrics)

        write_json_atomic(self.path, {"metrics": selected})

        return selected
