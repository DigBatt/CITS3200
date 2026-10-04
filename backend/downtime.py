"""
Downtime records, kept in one JSON file under `storage.directory`.

The file is read on every call rather than cached, so a change reaches the
figures without a restart and is seen by every worker process. Writes
are serialised by a lock and replace the file atomically. The lock is per
process: with more than one worker, two saves in the same instant could lose
one of them, so run a single worker.
"""

from __future__ import annotations
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence
from uuid import uuid4

from backend.files import write_json_atomic
from backend.models import Downtime
from backend.repository.base import RepositoryError

FILE_VERSION = 1


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """
    Two periods overlap when each starts before the other ends. Periods that
    only touch, one ending as the next starts, do not.
    """
    return a_start < b_end and b_start < a_end


def merged_intervals(
    records: Iterable[Downtime], start: Optional[datetime] = None, end: Optional[datetime] = None
) -> list[tuple[datetime, datetime]]:
    """
    One vehicle's downtime as disjoint periods, clipped to a window.

    Overlapping or touching records are joined, so an overlap the
    administrator confirmed is not counted twice (S19).

    Parameters
    ----------
    records : iterable of Downtime
        One vehicle's records; the caller filters by vehicle.
    start, end : datetime or None
        The window, UTC. None is unbounded on that side.

    Returns
    -------
    list of (datetime, datetime)
        Ascending, non-overlapping, each with start < end.
    """
    clipped = []
    for record in records:
        lo = max(record.start, start) if start else record.start
        hi = min(record.end, end) if end else record.end
        if lo < hi:
            clipped.append((lo, hi))
    clipped.sort()

    merged: list[tuple[datetime, datetime]] = []
    for lo, hi in clipped:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


class DowntimeStore:
    """
    Downtime records in one JSON file: `{"version": 1, "records": [...]}`.
    A missing file means no records yet.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def list(
        self,
        vehicle_ids: Optional[Sequence[str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[Downtime]:
        """
        Records ascending by start, optionally only those for `vehicle_ids`
        that overlap the window `start`..`end` (None is unbounded).
        """
        records = [
            r
            for r in self._read()
            if (vehicle_ids is None or r.vehicle_id in vehicle_ids)
            and (start is None or r.end > start)
            and (end is None or r.start < end)
        ]
        return sorted(records, key=lambda r: (r.start, r.vehicle_id, r.id))

    def get(self, record_id: str) -> Optional[Downtime]:
        return next((r for r in self._read() if r.id == record_id), None)

    def overlapping(
        self, vehicle_id: str, start: datetime, end: datetime, exclude_id: Optional[str] = None
    ) -> list[Downtime]:
        """
        This vehicle's records that overlap `start`..`end`, leaving out
        `exclude_id` so an edited record does not clash with itself (S18).
        """
        return [
            r
            for r in self.list([vehicle_id])
            if r.id != exclude_id and overlaps(r.start, r.end, start, end)
        ]

    def add(self, vehicle_id: str, start: datetime, end: datetime, reason: str, now: datetime) -> Downtime:
        """
        Store a new record.

        Raises
        ------
        ValueError
            If `end` is not after `start`. The API checks first and answers
            400; this guards the file against any other caller.
        """
        _check_period(start, end)
        record = Downtime(
            id=uuid4().hex,
            vehicle_id=vehicle_id,
            start=start,
            end=end,
            reason=reason,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            records = self._read()
            records.append(record)
            self._write(records)
        return record

    def update(
        self, record_id: str, vehicle_id: str, start: datetime, end: datetime, reason: str, now: datetime
    ) -> Optional[Downtime]:
        """
        Replace a record's vehicle, times and reason. None if the id is
        not on record.

        Raises
        ------
        ValueError
            If `end` is not after `start`.
        """
        _check_period(start, end)
        with self._lock:
            records = self._read()
            for i, existing in enumerate(records):
                if existing.id == record_id:
                    records[i] = Downtime(
                        id=existing.id,
                        vehicle_id=vehicle_id,
                        start=start,
                        end=end,
                        reason=reason,
                        created_at=existing.created_at,
                        updated_at=now,
                    )
                    self._write(records)
                    return records[i]
        return None

    def delete(self, record_id: str) -> bool:
        """
        Remove a record. False if the id is not on record.
        """
        with self._lock:
            records = self._read()
            kept = [r for r in records if r.id != record_id]
            if len(kept) == len(records):
                return False
            self._write(kept)
        return True

    def _read(self) -> list[Downtime]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise RepositoryError(f"Could not read {self.path}: {exc}") from exc

        try:
            raw = json.loads(text)
            if raw.get("version") != FILE_VERSION:
                raise ValueError(f"unsupported version {raw.get('version')!r}")
            return [Downtime.from_dict(entry) for entry in raw["records"]]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise RepositoryError(f"{self.path} is not a valid downtime file: {exc}") from exc

    def _write(self, records: Sequence[Downtime]) -> None:
        try:
            write_json_atomic(self.path, {"version": FILE_VERSION, "records": [r.to_dict() for r in records]})
        except OSError as exc:
            raise RepositoryError(f"Could not write {self.path}: {exc}") from exc


def _check_period(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValueError("end must be after start")

def intervals_by_vehicle(
    store: Optional[DowntimeStore], vehicle_ids: Sequence[str], start: datetime, end: datetime
) -> Optional[dict[str, list[tuple[datetime, datetime]]]]:
    """
    Each vehicle's downtime over a window, as /api/metrics and /api/operating
    take it (S19). Only the times: a record's reason stays admin only.

    Parameters
    ----------
    store : DowntimeStore or None
        None when `storage.directory` is unset.
    vehicle_ids : sequence of str
    start, end : datetime
        The window, UTC.

    Returns
    -------
    dict of {str: list of (datetime, datetime)} or None
        Every vehicle in `vehicle_ids`, with `merged_intervals` of its
        records, empty if it has none. None when there is no store, so there
        is no downtime log at all, which is not the same as no downtime.
    """
    if store is None:
        return None
    records = store.list(vehicle_ids, start, end)
    return {
        vehicle_id: merged_intervals([r for r in records if r.vehicle_id == vehicle_id], start, end)
        for vehicle_id in vehicle_ids
    }
