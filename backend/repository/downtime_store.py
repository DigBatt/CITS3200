"""
Operator reported downtime, stored in SQLite.

Downtime is the one bucket of the time usage model the telemetry cannot
answer (backend/metrics/tum.py), so operators report it themselves on the
admin page. This module is only the store; the endpoints over it are S18.

SQLite rather than a CSV because these records are edited and deleted, while
CsvRepository is append only: its incremental reader assumes a file it has
already read only ever grows. sqlite3 is in the standard library, so this
adds no dependency.

Times are stored in the canonical UTC form of backend.models.format_timestamp,
which is fixed width and so compares and sorts correctly as text. Bounds are
half open, `start` inclusive to `end` exclusive, so two records that merely
touch do not overlap. That is the rule the admin page already applies before
it saves.
"""

from __future__ import annotations
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence
from uuid import uuid4

from backend.models import Downtime, Vehicle, format_timestamp, parse_timestamp
from backend.repository.base import RepositoryError

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS downtime (
    id          TEXT PRIMARY KEY,
    vehicle_id  TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK (end_time > start_time),
    CHECK (reason <> '')
);
CREATE INDEX IF NOT EXISTS downtime_vehicle_start ON downtime (vehicle_id, start_time);
"""

_COLUMNS = "id, vehicle_id, start_time, end_time, reason, created_at, updated_at"

#: Messages of the two ValueErrors a write raises, so a caller can tell them
#: apart without matching on prose.
END_BEFORE_START = "A downtime record must end after it starts"
EMPTY_REASON = "A downtime record needs a reason"


class DowntimeStore:
    """
    Downtime records in a SQLite file.

    Parameters
    ----------
    database_path : Path or str
        The SQLite file. Created, with its parent directory, if missing.
    vehicles : sequence of Vehicle, optional
        The configured fleet. Writes naming an id outside it are refused. None
        skips that check, for a caller that has already validated the id.

    Notes
    -----
    Reads are never filtered by the configured fleet, so a record kept for a
    vehicle since retired still comes back. Only writes are checked.
    """

    def __init__(self, database_path: Path | str, vehicles: Optional[Sequence[Vehicle]] = None):
        self.database_path = Path(database_path)
        self._known_ids = None if vehicles is None else {v.id for v in vehicles}
        self._lock = threading.Lock()
        self._connection = self._connect()

    @classmethod
    def from_config(cls, config) -> "DowntimeStore":
        """
        Build from a backend.config.Config.

        Parameters
        ----------
        config : backend.config.Config

        Returns
        -------
        DowntimeStore

        Raises
        ------
        RepositoryError
            If `data.downtime_database` is unset, since records would
            otherwise be written to a path that was never configured.
        """
        if config.downtime_database is None:
            raise RepositoryError("config/app.yaml does not set data.downtime_database")
        return cls(config.downtime_database, config.vehicles)

    def _connect(self) -> sqlite3.Connection:
        """
        Open the file and apply the schema.

        Returns
        -------
        sqlite3.Connection

        Raises
        ------
        RepositoryError
            If the file cannot be opened or the schema cannot be applied.
        """
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            # Flask serves requests on several threads; the lock below, not
            # sqlite3's own check, is what keeps use of this handle serial.
            connection = sqlite3.connect(self.database_path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            # WAL so the logger process can read while the admin page writes.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            connection.commit()
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise RepositoryError(f"Could not open the downtime database at {self.database_path}: {exc}") from exc

    def list(
        self,
        vehicle_ids: Optional[Sequence[str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[Downtime]:
        """
        Stored records, ascending by start time.

        Parameters
        ----------
        vehicle_ids : sequence of str, optional
            None or empty means every vehicle.
        start, end : datetime, optional
            UTC bounds. A record is returned when it overlaps the window, so
            one that began before `start` and is still open at `start` counts.
            None is unbounded on that side.

        Returns
        -------
        list of Downtime
            One flat list, not grouped per vehicle: these are sparse, and
            callers want them in time order.
        """
        clauses, parameters = [], []

        requested = list(dict.fromkeys(vehicle_ids or []))
        if requested:
            clauses.append(f"vehicle_id IN ({','.join('?' * len(requested))})")
            parameters.extend(requested)
        if start is not None:
            clauses.append("end_time > ?")
            parameters.append(format_timestamp(start))
        if end is not None:
            clauses.append("start_time < ?")
            parameters.append(format_timestamp(end))

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT {_COLUMNS} FROM downtime{where} ORDER BY start_time, vehicle_id, id", parameters)
        return [self._to_record(row) for row in rows]

    def get(self, record_id: str) -> Optional[Downtime]:
        """
        One record by id.

        Parameters
        ----------
        record_id : str

        Returns
        -------
        Downtime or None
            None if no record has that id.
        """
        rows = self._query(f"SELECT {_COLUMNS} FROM downtime WHERE id = ?", [str(record_id)])
        return self._to_record(rows[0]) if rows else None

    def add(self, vehicle_id: str, start: datetime, end: datetime, reason: str) -> Downtime:
        """
        Store a new record.

        Overlapping an existing record is allowed: the admin page warns about
        it but still saves, so the store does not refuse it. Call `overlapping`
        first to raise that warning.

        Parameters
        ----------
        vehicle_id : str
        start, end : datetime
            UTC bounds, `end` strictly after `start`.
        reason : str
            Free text, not empty.

        Returns
        -------
        Downtime
            The stored record, with its server assigned id and timestamps.

        Raises
        ------
        ValueError
            If `end` is not after `start`, or `reason` is empty.
        RepositoryError
            If the vehicle is not in the configured fleet, or the write fails.
        """
        vehicle_id, start, end, reason = self._validate(vehicle_id, start, end, reason)
        now = format_timestamp(datetime.now(timezone.utc))
        record_id = uuid4().hex

        self._write(
            f"INSERT INTO downtime ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [record_id, vehicle_id, format_timestamp(start), format_timestamp(end), reason, now, now],
        )
        log.info("stored downtime %s for %s", record_id, vehicle_id)
        return self.get(record_id)

    def update(
        self,
        record_id: str,
        vehicle_id: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        reason: Optional[str] = None,
    ) -> Optional[Downtime]:
        """
        Change a stored record.

        Parameters
        ----------
        record_id : str
        vehicle_id, start, end, reason : optional
            Only the fields given are changed. None leaves that field alone;
            no field is nullable, so None is never a new value.

        Returns
        -------
        Downtime or None
            The updated record, or None if no record has that id.

        Raises
        ------
        ValueError
            If the result would end before it starts, or have an empty reason.
        RepositoryError
            If the vehicle is not in the configured fleet, or the write fails.
        """
        existing = self.get(record_id)
        if existing is None:
            return None

        merged = self._validate(
            existing.vehicle_id if vehicle_id is None else vehicle_id,
            existing.start if start is None else start,
            existing.end if end is None else end,
            existing.reason if reason is None else reason,
        )
        self._write(
            "UPDATE downtime SET vehicle_id = ?, start_time = ?, end_time = ?, reason = ?, updated_at = ? WHERE id = ?",
            [
                merged[0],
                format_timestamp(merged[1]),
                format_timestamp(merged[2]),
                merged[3],
                format_timestamp(datetime.now(timezone.utc)),
                str(record_id),
            ],
        )
        return self.get(record_id)

    def delete(self, record_id: str) -> bool:
        """
        Remove a record.

        Parameters
        ----------
        record_id : str

        Returns
        -------
        bool
            False if no record had that id, so a caller can answer 404.

        Raises
        ------
        RepositoryError
            If the write fails.
        """
        return self._write("DELETE FROM downtime WHERE id = ?", [str(record_id)]) > 0

    def overlapping(
        self, vehicle_id: str, start: datetime, end: datetime, exclude_id: Optional[str] = None
    ) -> list[Downtime]:
        """
        Records for one vehicle that clash with a period.

        The rule the admin page applies before saving: two periods overlap
        when each starts before the other ends.

        Parameters
        ----------
        vehicle_id : str
        start, end : datetime
            The proposed UTC bounds.
        exclude_id : str, optional
            A record to ignore, so editing one does not clash with itself.

        Returns
        -------
        list of Downtime
            Empty when the period is clear.
        """
        query = f"SELECT {_COLUMNS} FROM downtime WHERE vehicle_id = ? AND start_time < ? AND end_time > ?"
        parameters = [str(vehicle_id), format_timestamp(end), format_timestamp(start)]
        if exclude_id is not None:
            query += " AND id <> ?"
            parameters.append(str(exclude_id))

        return [self._to_record(row) for row in self._query(f"{query} ORDER BY start_time, id", parameters)]

    def _validate(
        self, vehicle_id: str, start: datetime, end: datetime, reason: str
    ) -> tuple[str, datetime, datetime, str]:
        """
        Check and normalise the fields of a write.

        Returns
        -------
        tuple
            The fields, with naive times read as UTC and the reason stripped.

        Raises
        ------
        ValueError
            If `end` is not after `start`, or `reason` is empty.
        RepositoryError
            If the vehicle is not in the configured fleet.
        """
        vehicle_id = str(vehicle_id)
        if self._known_ids is not None and vehicle_id not in self._known_ids:
            raise RepositoryError(f"No vehicle with id {vehicle_id!r} in the configured fleet")

        start, end = parse_timestamp(start), parse_timestamp(end)
        if end <= start:
            raise ValueError(END_BEFORE_START)

        reason = str(reason).strip()
        if not reason:
            raise ValueError(EMPTY_REASON)

        return vehicle_id, start, end, reason

    def _query(self, statement: str, parameters: Sequence) -> list[sqlite3.Row]:
        """
        Run a read.
        """
        try:
            with self._lock:
                return self._connection.execute(statement, tuple(parameters)).fetchall()
        except sqlite3.Error as exc:
            raise RepositoryError(f"Could not read the downtime database: {exc}") from exc

    def _write(self, statement: str, parameters: Sequence) -> int:
        """
        Run a write and commit it.

        Returns
        -------
        int
            Rows affected.
        """
        try:
            with self._lock:
                cursor = self._connection.execute(statement, tuple(parameters))
                self._connection.commit()
                return cursor.rowcount
        except sqlite3.IntegrityError as exc:
            raise RepositoryError(f"Rejected by the downtime database: {exc}") from exc
        except sqlite3.Error as exc:
            raise RepositoryError(f"Could not write to the downtime database: {exc}") from exc

    @staticmethod
    def _to_record(row: sqlite3.Row) -> Downtime:
        """
        One stored row as a Downtime.
        """
        return Downtime(
            id=row["id"],
            vehicle_id=row["vehicle_id"],
            start=parse_timestamp(row["start_time"]),
            end=parse_timestamp(row["end_time"]),
            reason=row["reason"],
            created_at=parse_timestamp(row["created_at"]),
            updated_at=parse_timestamp(row["updated_at"]),
        )

    def close(self) -> None:
        """
        Release the handle.
        """
        with self._lock:
            self._connection.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.database_path)!r})"
