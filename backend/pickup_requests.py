"""
In-memory and only one process 
A restart clears it; nothing about the dataclass or the API in backend/api/pickup_requests.py
depends on how requests are kept, so a persistent store can replace this one
later without a rework.
"""

from __future__ import annotations
import threading
from datetime import datetime
from typing import Optional
from uuid import uuid4

from backend.models import PickupRequest


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

    def _open_request(self, stop_id: str, rider_token: str) -> Optional[PickupRequest]:
        return next(
            (
                r
                for r in self._requests.values()
                if r.stop_id == stop_id and r.rider_token == rider_token and r.status == PickupRequest.OPEN
            ),
            None,
        )
