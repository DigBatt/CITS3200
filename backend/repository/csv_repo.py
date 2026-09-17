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
import io
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence
from backend.models import Position, Vehicle, format_timestamp, parse_timestamp
from backend.repository.base import Repository, RepositoryError, in_range, normalise

log = logging.getLogger(__name__)

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

#: Header of files written by `add_positions`.
FIELDNAMES = [
    "timestamp",
    "latitude",
    "longitude",
    "altitude_m",
    "heading_deg",
    "speed_mps",
    "gps_status",
    "battery_percent",
]

_FLOAT_FIELDS = ("latitude", "longitude", "altitude_m", "heading_deg", "speed_mps", "battery_percent")


@dataclass
class _FileState:
    """
    What has been read of one file so far.
    """

    stamp: tuple[int, int, int]  # (inode, mtime_ns, size)
    offset: int  # bytes consumed
    header: list[str]
    by_timestamp: dict[datetime, Position]
    positions: list[Position]  # ascending. this what callers get


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
        self._cache: dict[str, _FileState] = {}
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

    def add_positions(self, positions: Sequence[Position]) -> int:
        """
        See `Repository.add_positions`.

        Rows are appended in the order given, one batch per vehicle file. A
        new file gets the FIELDNAMES header first.
        """
        grouped: dict[str, list[Position]] = {}
        for position in positions:
            if position.vehicle_id not in self._files:
                raise RepositoryError(f"No vehicle with id {position.vehicle_id!r}")
            grouped.setdefault(position.vehicle_id, []).append(position)

        with self._lock:
            for vehicle_id, rows in grouped.items():
                self._append(self._files[vehicle_id], rows)
        return sum(len(rows) for rows in grouped.values())

    def _append(self, path: Path, rows: Sequence[Position]) -> None:
        """
        Append rows to one file in a single write.

        Parameters
        ----------
        path : Path
        rows : sequence of Position

        Raises
        ------
        RepositoryError
            If the file has a header other than FIELDNAMES, or the write fails.
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.stat().st_size == 0:
                writer.writerow(FIELDNAMES)
            elif self._check_appendable(path):
                buffer.write("\n")  # a crashed write left a partial line so readers skip it
            writer.writerows(self._position_to_row(p) for p in rows)
            with open(path, "a", newline="", encoding="utf-8") as handle:
                handle.write(buffer.getvalue())
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise RepositoryError(f"Could not write {path}: {exc}") from exc

    @staticmethod
    def _check_appendable(path: Path) -> bool:
        """
        Check an existing file can take appended rows.

        Parameters
        ----------
        path : Path
            A non-empty file.

        Returns
        -------
        bool
            True if the file does not end in a newline.

        Raises
        ------
        RepositoryError
            If its header is not FIELDNAMES, since appended values would land
            in the wrong columns.
        """
        with open(path, "rb") as handle:
            first = handle.readline()
            handle.seek(-1, os.SEEK_END)
            unterminated = handle.read(1) != b"\n"
        header = next(csv.reader([first.decode("utf-8-sig")]), [])
        if [column.strip().lower() for column in header] != FIELDNAMES:
            raise RepositoryError(f"{path} has a header other than {','.join(FIELDNAMES)}; not appending")
        return unterminated

    @staticmethod
    def _position_to_row(position: Position) -> list[Any]:
        """
        One CSV row in FIELDNAMES order, None as a blank cell.
        """
        values = [getattr(position, field) for field in FIELDNAMES[1:]]
        return [format_timestamp(position.timestamp)] + ["" if v is None else v for v in values]

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
        except FileNotFoundError:
            with self._lock:
                self._cache.pop(vehicle_id, None)
            return []
        stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)

        with self._lock:
            state = self._cache.get(vehicle_id)
            if state is not None and state.stamp == stamp:
                return state.positions
            # Only a longer file with the same inode was appended to. Anything
            # else was replaced or rewritten and is read from the start.
            appended = state is not None and stat.st_ino == state.stamp[0] and stat.st_size > state.offset
            state = self._read(path, vehicle_id, state if appended else None, stamp)
            if state is None:
                self._cache.pop(vehicle_id, None)
                return []
            self._cache[vehicle_id] = state
            return state.positions

    def _read(
        self, path: Path, vehicle_id: str, state: Optional[_FileState], stamp: tuple[int, int, int]
    ) -> Optional[_FileState]:
        """
        Parse a file from the start, or from where `state` left off.

        Parameters
        ----------
        path : Path
            File to read.
        vehicle_id : str
            Id to stamp the rows with; the file does not carry it.
        state : _FileState or None
            The previous read of this file, if it has only been appended to.
        stamp : tuple
            The file's current (inode, mtime_ns, size).

        Returns
        -------
        _FileState or None
            None if the file has no complete header line yet. Duplicate
            timestamps collapse to the last row, rows that will not parse or
            do not have one cell per header column are skipped, and a final
            line with no newline is left for the next read.

        Raises
        ------
        RepositoryError
            If the file cannot be read at all.
        """
        offset = state.offset if state else 0
        try:
            with open(path, "rb") as handle:
                handle.seek(offset)
                data = handle.read()
            end = data.rfind(b"\n") + 1
            text = data[:end].decode("utf-8-sig" if offset == 0 else "utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RepositoryError(f"Could not read {path}: {exc}") from exc

        lines = csv.reader(io.StringIO(text, newline=""))
        header = state.header if state else next(lines, None)
        if not header:
            return None

        by_timestamp = state.by_timestamp if state else {}
        last = state.positions[-1].timestamp if state and state.positions else None
        added: list[Position] = []
        in_order = True
        skipped = 0
        for values in lines:
            if not any(value.strip() for value in values):
                continue  # blank line
            if len(values) != len(header):
                skipped += 1  # truncated by a crashed write, or malformed
                continue
            try:
                position = self._row_to_position(dict(zip(header, values)), vehicle_id)
            except (ValueError, KeyError, TypeError):
                skipped += 1
                continue
            if last is not None and position.timestamp <= last:
                in_order = False
            last = position.timestamp
            by_timestamp[position.timestamp] = position
            added.append(position)

        if skipped:
            log.warning("%s: skipped %d unreadable rows", path, skipped)

        if state is not None and in_order:
            positions = state.positions + added
        else:
            positions = [by_timestamp[key] for key in sorted(by_timestamp)]
        return _FileState(stamp, offset + end, header, by_timestamp, positions)

    def _row_to_position(self, row: dict[str, Optional[str]], vehicle_id: str) -> Position:
        """
        Map one CSV row onto the schema as per COLUMN_MAP.

        Parameters
        ----------
        row : dict
            Header to cell for one row.
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
