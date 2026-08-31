from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime
from typing import Iterable, Optional, Sequence
from backend.models import Event, Position

class RepositoryError(Exception):
    """
    Repo error.
    """

def normalise(position: Position) -> Position:
    """
    Apply the schema's rules to a row on its way out of storage.

    Only one so far: no fix means null coordinates, and the CSVs still carry
    the last known ones on those rows.

    Parameters
    ----------
    position : Position
        Row as read from storage.

    Returns
    -------
    Position
        The row, coordinates dropped if `gps_status` is -1.
    """
    if position.gps_status == Position.NO_FIX and (position.latitude is not None or position.longitude is not None):
        return replace(position, latitude=None, longitude=None)
    return position


def in_range(position: Position, start: Optional[datetime], end: Optional[datetime]) -> bool:
    """
    Test a position against a time window, inclusive at both ends.

    Parameters
    ----------
    position : Position
        Row to test.
    start, end : datetime or None
        UTC bounds. None is unbounded on that side.

    Returns
    -------
    bool
    """
    if start is not None and position.timestamp < start:
        return False
    if end is not None and position.timestamp > end:
        return False
    return True


class Repository(ABC):

    @abstractmethod
    def vehicle_ids(self) -> list[str]:
        """
        Every id in this store.

        Returns
        -------
        list of str
            What `vehicle_ids=None` expands to.
        """

    @abstractmethod
    def get_positions(
        self,
        vehicle_ids: Optional[Sequence[str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> dict[str, list[Position]]:
        """
        Stored positions per vehicle, ascending by timestamp.

        Parameters
        ----------
        vehicle_ids : sequence of str, optional
            None or empty means the whole fleet.
        start, end : datetime, optional
            Inclusive UTC bounds.

        Returns
        -------
        dict of {str: list of Position}
            A key per requested id, empty where there is no data. An id the
            store does not know is empty, not an error.
        """

    @abstractmethod
    def get_latest_positions(
        self, vehicle_ids: Optional[Sequence[str]] = None
    ) -> dict[str, Optional[Position]]:
        """
        The most recent position per vehicle.

        Parameters
        ----------
        vehicle_ids : sequence of str, optional
            None or empty means the whole fleet.

        Returns
        -------
        dict of {str: Position or None}
            None where the vehicle has no data.
        """

    def get_events(
        self,
        vehicle_ids: Optional[Sequence[str]] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> dict[str, list[Event]]:
        """
        Engage/disengage events per vehicle.

        Parameters
        ----------
        vehicle_ids : sequence of str, optional
            None or empty means the whole fleet.
        start, end : datetime, optional
            Inclusive UTC bounds, unused for now.

        Returns
        -------
        dict of {str: list of Event}
            A key per requested id, all empty.
        """
        return {vehicle_id: [] for vehicle_id in self._resolve_ids(vehicle_ids)}

    def _resolve_ids(self, vehicle_ids: Optional[Iterable[str]]) -> list[str]:
        """
        Expand a selection to the ids to answer for.

        Parameters
        ----------
        vehicle_ids : iterable of str or None
            None or empty means the whole fleet.

        Returns
        -------
        list of str
            Requested order kept, duplicates collapsed.
        """
        if vehicle_ids is None:
            return list(self.vehicle_ids())
        requested = [str(v) for v in vehicle_ids]
        if not requested:
            return list(self.vehicle_ids())
        return list(dict.fromkeys(requested))

    def close(self) -> None:
        """
        Release any handles
        """
