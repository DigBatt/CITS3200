"""
The CSV files are an implementation of the database described in
docs/data-schema.md.

One file per vehicle, named in config/vehicles.yaml which is resolved against
`data.directory` in config/app.yaml.

Column mapping:

    timestamp                 -> timestamp        (required)
    latitude, longitude       -> as named
    altitude                  -> altitude_m
    heading                   -> heading_deg
    speed_mps, gps_status     -> as named
    battery_percent           -> as named
    timestamp_unix            -> ignored, derivable from timestamp
    position_covariance_type  -> ignored, not in the schema
"""

from __future__ import annotations
import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence
from backend.models import Position, Vehicle, parse_timestamp
from backend.repository.base import Repository, RepositoryError, in_range, normalise

COLUMN_MAP = {
    "timestamp": "timestamp",
    "latitude": "latitude",
    "longitude": "longitude",
    "altitude": "altitude_m",
    "altitude_m": "altitude_m",
    "heading": "heading_deg",
    "heading_deg": "heading_deg",
    "speed_mps": "speed_mps",
    "gps_status": "gps_status",
    "battery_percent": "battery_percent",
}

_FLOAT_FIELDS = ("latitude", "longitude", "altitude_m", "heading_deg", "speed_mps", "battery_percent")


class CsvRepository(Repository):
    """
    Positions read from one CSV per vehicle.

    Parameters
    ----------
    data_directory : Path or str
        Directory holding the per vehicle CSVs.
    vehicles : sequence of Vehicle
        The configured fleet. A vehicle with no file yet is empty.
    """

    def __init__(self, data_directory: Path | str, vehicles: Sequence[Vehicle]):
        self.data_directory = Path(data_directory)
        self._vehicles = list(vehicles)
        self._files = {
            v.id: self.data_directory / (v.positions_file or f"positions_{v.id}.csv") for v in self._vehicles
        }
        self._cache: dict[str, tuple[Any, list[Position]]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config) -> "CsvRepository":
        """
        Build from a backend.config.Config.

        Parameters
        ----------
        config : backend.config.Config

        Returns
        -------
        CsvRepository

        Raises
        ------
        RepositoryError
            If `data.directory` is unset, since every vehicle would otherwise
            read empty off a path that was never configured.
        """
        if config.data_directory is None:
            raise RepositoryError("config/app.yaml does not set data.directory")
        return cls(config.data_directory, config.vehicles)

    def vehicle_ids(self) -> list[str]:
        """
        See `Repository.vehicle_ids`.
        """
        return [v.id for v in self._vehicles]

    def get_positions(
        self,
        vehicle_ids: Optional[Sequence[str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> dict[str, list[Position]]:
        """
        See `Repository.get_positions`.
        """
        return {
            vehicle_id: [p for p in self._positions_for(vehicle_id) if in_range(p, start, end)]
            for vehicle_id in self._resolve_ids(vehicle_ids)
        }

    def get_latest_positions(self, vehicle_ids: Optional[Sequence[str]] = None) -> dict[str, Optional[Position]]:
        """
        See `Repository.get_latest_positions`.
        """
        result: dict[str, Optional[Position]] = {}
        for vehicle_id in self._resolve_ids(vehicle_ids):
            positions = self._positions_for(vehicle_id)
            result[vehicle_id] = positions[-1] if positions else None
        return result

    def _positions_for(self, vehicle_id: str) -> list[Position]:
        """
        Every row for one vehicle.

        Parameters
        ----------
        vehicle_id : str

        Returns
        -------
        list of Position
            Ascending by timestamp. Empty for an unknown id or a missing file.
        """
        path = self._files.get(vehicle_id)
        if path is None:
            return []

        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            stamp = None

        with self._lock:
            cached = self._cache.get(vehicle_id)
            if cached is not None and cached[0] == stamp:
                return cached[1]

        positions = [] if stamp is None else self._read_file(path, vehicle_id)
        with self._lock:
            self._cache[vehicle_id] = (stamp, positions)
        return positions

    def _read_file(self, path: Path, vehicle_id: str) -> list[Position]:
        """
        Parse one CSV.

        Parameters
        ----------
        path : Path
            File to read.
        vehicle_id : str
            Id to stamp the rows with; the file does not carry it.

        Returns
        -------
        list of Position
            Ascending by timestamp, duplicate timestamps collapsed, unreadable
            rows skipped.

        Raises
        ------
        RepositoryError
            If the file cannot be read at all.
        """
        try:
            with open(path, newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            raise RepositoryError(f"Could not read {path}: {exc}") from exc

        by_timestamp: dict[datetime, Position] = {}
        skipped = 0
        for line_number, row in enumerate(rows, start=2):  # header is line 1
            try:
                position = self._row_to_position(row, vehicle_id)
            except (ValueError, KeyError, TypeError) as exc:
                skipped += 1
                continue
            by_timestamp[position.timestamp] = position

        return [by_timestamp[key] for key in sorted(by_timestamp)]

    def _row_to_position(self, row: dict[str, Optional[str]], vehicle_id: str) -> Position:
        """
        Map one CSV row onto the schema as per COLUMN_MAP.

        Parameters
        ----------
        row : dict
            One row from `csv.DictReader`.
        vehicle_id : str

        Returns
        -------
        Position
            Blank cells and absent columns alike become None.

        Raises
        ------
        ValueError
            If the timestamp is missing or a field will not parse.
        """
        values: dict[str, Any] = {}
        for column, raw in row.items():
            field = COLUMN_MAP.get((column or "").strip().lower())
            if field is None:
                continue  # timestamp_unix, position_covariance_type
            text = (raw or "").strip()
            values[field] = text or None

        timestamp = values.get("timestamp")
        if not timestamp:
            raise ValueError("no timestamp")

        return normalise(
            Position(
                vehicle_id=vehicle_id,
                timestamp=parse_timestamp(timestamp),
                gps_status=int(float(values["gps_status"])) if values.get("gps_status") else None,
                **{f: float(values[f]) if values.get(f) else None for f in _FLOAT_FIELDS},
            )
        )

    def __repr__(self) -> str:
        return f"CsvRepository({str(self.data_directory)!r}, {len(self._vehicles)} vehicles)"
