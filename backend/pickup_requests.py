"""
In-memory and only one process 
A restart clears it; nothing about the dataclass or the API in backend/api/pickup_requests.py
depends on how requests are kept, so a persistent store can replace this one
later without a rework.
"""

from __future__ import annotations
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence
from uuid import uuid4

from backend.models import PickupRequest


@dataclass(frozen=True)
class StopWaiting:
    """
    Open requests at one stop (S09.2). `oldest_created_at` is None when nobody
    is waiting.
    """

    stop_id: str
    waiting: int
    oldest_created_at: Optional[datetime]


def waiting_at_stops(requests: Iterable[PickupRequest], stop_ids: Sequence[str]) -> list[StopWaiting]:
    """
    Count open requests per stop, in the order of `stop_ids`.

    Requests at stops not in `stop_ids` are ignored, so passing a route's
    stops leaves out riders waiting somewhere the shuttle does not go.
    """
    counts = {stop_id: 0 for stop_id in stop_ids}
    oldest: dict[str, datetime] = {}
    for r in requests:
        if r.status != PickupRequest.OPEN or r.stop_id not in counts:
            continue
        counts[r.stop_id] += 1
        if r.stop_id not in oldest or r.created_at < oldest[r.stop_id]:
            oldest[r.stop_id] = r.created_at
    return [StopWaiting(stop_id, counts[stop_id], oldest.get(stop_id)) for stop_id in stop_ids]


class PickupRequestStore:
    """
    Thread-safe, in-memory home for pickup requests.
    """

    def __init__(self):
        self._requests: dict[str, PickupRequest] = {}
        self._lock = threading.Lock()

    def create(self, stop_id: str, rider_token: str, now: datetime) -> tuple[PickupRequest, bool]:
        """
        Open a request, or hand back the rider's existing open one at this stop
        """
        with self._lock:
            existing = self._open_request(stop_id, rider_token)
            if existing is not None:
                return existing, False
            request = PickupRequest(
                id=uuid4().hex,
                stop_id=stop_id,
                rider_token=rider_token,
                status=PickupRequest.OPEN,
                created_at=now,
            )
            self._requests[request.id] = request
            return request, True

    def list(self, status: Optional[str] = None) -> list[PickupRequest]:
        """
        Every request, ascending by `created_at`, optionally filtered by status
        """
        with self._lock:
            requests = list(self._requests.values())
        if status is not None:
            requests = [r for r in requests if r.status == status]
        return sorted(requests, key=lambda r: r.created_at)

    def collect(self, stop_id: str, now: datetime) -> list[PickupRequest]:
        """
        Close every open request at a stop as collected (S10). The records are
        kept, with `cleared_at`, for the admin's review of the day.

        Returns the requests closed, empty if nobody was waiting.
        """
        with self._lock:
            closed = [
                replace(r, status=PickupRequest.COLLECTED, cleared_at=now)
                for r in self._requests.values()
                if r.stop_id == stop_id and r.status == PickupRequest.OPEN
            ]
            for r in closed:
                self._requests[r.id] = r
        return sorted(closed, key=lambda r: r.created_at)

    def expire(self, now: datetime, max_age: timedelta) -> list[PickupRequest]:
        """
        Mark open requests older than `max_age` as expired (S10). Kept like
        collected ones, with `cleared_at` set to `now`.

        Returns the requests expired.
        """
        with self._lock:
            stale = [
                replace(r, status=PickupRequest.EXPIRED, cleared_at=now)
                for r in self._requests.values()
                if r.status == PickupRequest.OPEN and now - r.created_at > max_age
            ]
            for r in stale:
                self._requests[r.id] = r
        return sorted(stale, key=lambda r: r.created_at)

    def _open_request(self, stop_id: str, rider_token: str) -> Optional[PickupRequest]:
        return next(
            (
                r
                for r in self._requests.values()
                if r.stop_id == stop_id and r.rider_token == rider_token and r.status == PickupRequest.OPEN
            ),
            None,
        )
