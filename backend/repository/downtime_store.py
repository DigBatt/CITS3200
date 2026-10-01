"""
Operator reported downtime, stored in a JSON file.

Downtime is the one bucket of the time usage model the telemetry cannot
answer (backend/metrics/tum.py), so operators report it themselves on the
admin page. This module is only the store; the endpoints over it are S18.

A JSON file rather than a CSV because these records are edited and deleted,
while CsvRepository is append only: its incremental reader assumes a file it
has already read only ever grows. JSON rather than a database because there
are few of them, written by hand, and a plain file can be read, diffed and
fixed without any tool. json is in the standard library, so this adds no
dependency.

The file is a version number and the records, in the order `list` returns
them:

    {
      "version": 1,
      "records": [
        {"id": "...", "vehicle_id": "1",
         "start": "2026-09-17T01:00:00.123456Z", "end": "...",
         "reason": "Brake fault", "created_at": "...", "updated_at": "..."}
      ]
    }

Every write replaces the whole file: it is written beside the old one and then
renamed over it, which is atomic, so a reader, or a crash mid write, never sees
half a file. Before each operation the store checks whether the file changed
under it, as when a second server process wrote, and reads it again if so.

Times are stored in the canonical UTC form of backend.models.format_timestamp.
Bounds are half open, `start` inclusive to `end` exclusive, so two records that
merely touch do not overlap. That is the rule the admin page already applies
before it saves.
"""

from __future__ import annotations
import json
import logging
import os
import tempfile
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence
from uuid import uuid4

from backend.models import Downtime, Vehicle, format_timestamp, parse_timestamp
from backend.repository.base import RepositoryError

log = logging.getLogger(__name__)

FORMAT_VERSION = 1

#: Messages of the two ValueErrors a write raises, so a caller can tell them
#: apart without matching on prose.
END_BEFORE_START = "A downtime record must end after it starts"
EMPTY_REASON = "A downtime record needs a reason"

_FIELDS = ("id", "vehicle_id", "start", "end", "reason", "created_at", "updated_at")


class DowntimeStore:
    """
    Downtime records in a JSON file.

    Parameters
    ----------
    path : Path or str
        The JSON file. Created, with its parent directory, if missing.
    vehicles : sequence of Vehicle, optional
        The configured fleet. Writes naming an id outside it are refused. None
        skips that check, for a caller that has already validated the id.

    Raises
    ------
    RepositoryError
        If the file exists but cannot be read as downtime records. It is never
        overwritten in that case, so nothing in it is lost.

    Notes
    -----
    Reads are never filtered by the configured fleet, so a record kept for a
    vehicle since retired still comes back. Only writes are checked.
    """

    def __init__(self, path: Path | str, vehicles: Optional[Sequence[Vehicle]] = None):
        self.path = Path(path)
        self._known_ids = None if vehicles is None else {v.id for v in vehicles}
        self._lock = threading.Lock()
        self._records: list[Downtime] = []
        self._signature = None  # (mtime_ns, size) of the file as last read
        with self._lock:
            self._open()

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
            If `data.downtime_file` is unset, since records would otherwise be
            written to a path that was never configured.
        """
        if config.downtime_file is None:
            raise RepositoryError("config/app.yaml does not set data.downtime_file")
        return cls(config.downtime_file, config.vehicles)

    # ---- Reading ----

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
        wanted = set(vehicle_ids or [])
        start = None if start is None else parse_timestamp(start)
        end = None if end is None else parse_timestamp(end)
        with self._lock:
            self._refresh()
            return [
                record
                for record in self._records
                if (not wanted or record.vehicle_id in wanted)
                and (start is None or record.end > start)
                and (end is None or record.start < end)
            ]

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
        with self._lock:
            self._refresh()
            return self._find(str(record_id))

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
        start, end = parse_timestamp(start), parse_timestamp(end)
        with self._lock:
            self._refresh()
            return [
                record
                for record in self._records
                if record.vehicle_id == str(vehicle_id)
                and record.start < end
                and record.end > start
                and (exclude_id is None or record.id != str(exclude_id))
            ]

    # ---- Writing ----

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
        now = _now()
        record = Downtime(
            id=uuid4().hex, vehicle_id=vehicle_id, start=start, end=end,
            reason=reason, created_at=now, updated_at=now,
        )
        with self._lock:
            self._refresh()
            self._save([*self._records, record])
        log.info("stored downtime %s for %s", record.id, vehicle_id)
        return record

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
        with self._lock:
            self._refresh()
            existing = self._find(str(record_id))
            if existing is None:
                return None

            merged = self._validate(
                existing.vehicle_id if vehicle_id is None else vehicle_id,
                existing.start if start is None else start,
                existing.end if end is None else end,
                existing.reason if reason is None else reason,
            )
            updated = replace(
                existing,
                vehicle_id=merged[0], start=merged[1], end=merged[2], reason=merged[3],
                updated_at=_now(),
            )
            self._save([updated if r.id == existing.id else r for r in self._records])
            return updated

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
        with self._lock:
            self._refresh()
            kept = [r for r in self._records if r.id != str(record_id)]
            if len(kept) == len(self._records):
                return False
            self._save(kept)
            return True

    # ---- The file ----

    def _open(self) -> None:
        """
        Read the file, or create it empty if it does not exist yet.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RepositoryError(f"Could not create the folder for {self.path}: {exc}") from exc
        if self.path.exists():
            self._read()
        else:
            self._save([])

    def _refresh(self) -> None:
        """
        Read the file again if it changed since it was last read or written,
        as when another process wrote to it. Called under the lock.
        """
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            # Deleted from under the store: start again empty, as on a new
            # install, rather than resurrecting what was in memory.
            log.warning("%s disappeared; starting a new, empty downtime file", self.path)
            self._save([])
            return
        except OSError as exc:
            raise RepositoryError(f"Could not read {self.path}: {exc}") from exc
        if (stat.st_mtime_ns, stat.st_size) != self._signature:
            self._read()

    def _read(self) -> None:
        """
        Load every record from the file. Called under the lock.

        Raises
        ------
        RepositoryError
            If the file is not valid JSON, is of an unknown version, or holds
            a record that is incomplete or unreadable. The file is left as it
            is, for someone to fix.
        """
        try:
            stat = self.path.stat()
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RepositoryError(f"Could not read the downtime file {self.path}: {exc}") from exc

        if not isinstance(data, dict) or data.get("version") != FORMAT_VERSION:
            raise RepositoryError(f"{self.path} is not a version {FORMAT_VERSION} downtime file")

        records = []
        for index, raw in enumerate(data.get("records") or []):
            try:
                records.append(_from_json(raw))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise RepositoryError(f"{self.path}: record {index} is unreadable: {exc}") from exc

        self._records = _sorted(records)
        self._signature = (stat.st_mtime_ns, stat.st_size)

    def _save(self, records: list[Downtime]) -> None:
        """
        Replace the file with these records. Called under the lock.

        Written to a temporary file in the same folder, flushed to disk, then
        renamed over the real one, so the file on disk is always either the
        old records or the new, never a mix.
        """
        records = _sorted(records)
        payload = json.dumps(
            {"version": FORMAT_VERSION, "records": [_to_json(r) for r in records]},
            indent=2,
            ensure_ascii=False,
        )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            stat = self.path.stat()
        except OSError as exc:
            raise RepositoryError(f"Could not write the downtime file {self.path}: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        self._records = records
        self._signature = (stat.st_mtime_ns, stat.st_size)

    def _find(self, record_id: str) -> Optional[Downtime]:
        return next((r for r in self._records if r.id == record_id), None)

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

    def close(self) -> None:
        """
        Nothing to release: the file is only open while it is read or written.
        Kept so callers that closed the SQLite store need not change.
        """

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.path)!r})"


def _now() -> datetime:
    # Round-tripped through the stored form, so a record returned by a write
    # equals the same record read back from the file.
    return parse_timestamp(format_timestamp(datetime.now(timezone.utc)))


def _sorted(records: list[Downtime]) -> list[Downtime]:
    return sorted(records, key=lambda r: (r.start, r.vehicle_id, r.id))


def _to_json(record: Downtime) -> dict:
    return {
        "id": record.id,
        "vehicle_id": record.vehicle_id,
        "start": format_timestamp(record.start),
        "end": format_timestamp(record.end),
        "reason": record.reason,
        "created_at": format_timestamp(record.created_at),
        "updated_at": format_timestamp(record.updated_at),
    }


def _from_json(raw: dict) -> Downtime:
    missing = [field for field in _FIELDS if field not in raw]
    if missing:
        raise KeyError(", ".join(missing))
    return Downtime(
        id=str(raw["id"]),
        vehicle_id=str(raw["vehicle_id"]),
        start=parse_timestamp(raw["start"]),
        end=parse_timestamp(raw["end"]),
        reason=str(raw["reason"]),
        created_at=parse_timestamp(raw["created_at"]),
        updated_at=parse_timestamp(raw["updated_at"]),
    )
