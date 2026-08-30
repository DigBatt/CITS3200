"""
YAML loader.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import yaml

from backend.models import Vehicle

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"

class ConfigError(Exception):
    """
    The config files are missing or unreadable
    """


@dataclass(frozen=True)
class Config:

    vehicles: list[Vehicle]
    data_directory: Optional[Path]
    inactivity_threshold_seconds: Optional[int]
    expected_poll_interval_seconds: Optional[int]
    timezone: Optional[str]
    utc_offset_hours: Optional[int]
    map_centre: Optional[list[float]]
    map_zoom: Optional[int]
    refresh_interval_seconds: Optional[int]

    def vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        return next((v for v in self.vehicles if v.id == vehicle_id), None)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing config file: {path}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc


def load_config(config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Config:
    config_dir = Path(config_dir)
    app = _read_yaml(config_dir / "app.yaml")
    fleet = _read_yaml(config_dir / "vehicles.yaml")

    try:
        data = app.get("data") or {}
        liveness = app.get("liveness") or {}
        display = app.get("display") or {}
        map_settings = app.get("map") or {}

        directory = data.get("directory")

        vehicles = [
            Vehicle(
                id=str(entry["id"]),
                name=entry.get("name"),
                colour=entry.get("colour"),
                positions_file=entry.get("positions_file"),
            )
            for entry in fleet.get("vehicles") or []
        ]

        return Config(
            vehicles=vehicles,
            data_directory=PROJECT_ROOT / directory if directory else None,
            inactivity_threshold_seconds=liveness.get("inactivity_threshold_seconds"),
            expected_poll_interval_seconds=liveness.get("expected_poll_interval_seconds"),
            timezone=display.get("timezone"),
            utc_offset_hours=display.get("utc_offset_hours"),
            map_centre=map_settings.get("centre"),
            map_zoom=map_settings.get("zoom"),
            refresh_interval_seconds=map_settings.get("refresh_interval_seconds"),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Could not read the config in {config_dir}: {exc}") from exc
