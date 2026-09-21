from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

UTC = timezone.utc
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def parse_timestamp(value: str | datetime) -> datetime:
    """
    Parse an ISO 8601 into a UTC datetime.
    """
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"

    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        while tail and tail[0].isdigit():
            digits, tail = digits + tail[0], tail[1:]
        text = f"{head}.{digits[:6]:0<6}{tail}"

    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def format_timestamp(value: datetime) -> str:
    """
    Render a datetime in the canonical form.
    """
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT) + "Z"


@dataclass(frozen=True)
class Vehicle:
    """
    A shuttle as declared in config/vehicles.yaml.
    """

    id: str
    name: Optional[str] = None
    colour: Optional[str] = None
    positions_file: Optional[str] = None
    source_url: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "colour": self.colour}


@dataclass(frozen=True)
class Position:
    """
    A telemetry sample for one vehicle at one instant.
    """

    vehicle_id: str
    timestamp: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    heading_deg: Optional[float] = None
    speed_mps: Optional[float] = None
    gps_status: Optional[int] = None
    battery_percent: Optional[float] = None

    NO_FIX = -1

    @property
    def has_fix(self) -> bool:
        return self.gps_status is not None and self.gps_status >= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "timestamp": format_timestamp(self.timestamp),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude_m": self.altitude_m,
            "heading_deg": self.heading_deg,
            "speed_mps": self.speed_mps,
            "gps_status": self.gps_status,
            "battery_percent": self.battery_percent,
        }


@dataclass(frozen=True)
class Event:
    """
    An engage or disengage.

    Placeholder.
    """

    vehicle_id: str
    timestamp: datetime
    kind: Optional[str] = None
    detail: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "timestamp": format_timestamp(self.timestamp),
            "kind": self.kind,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Downtime:
    """
    A period one vehicle was out of service, as reported by an operator.

    Downtime is the one part of the time usage model the telemetry cannot
    answer (see backend/metrics/tum.py), so operators enter these by hand.

    Bounds are half open: the record covers `start` up to but not including
    `end`, so two records that merely touch do not overlap.
    """

    id: str
    vehicle_id: str
    start: datetime
    end: datetime
    reason: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def overlaps(self, start: datetime, end: datetime) -> bool:
        """
        Test this record against a window, half open at both ends.

        Parameters
        ----------
        start, end : datetime
            UTC bounds.

        Returns
        -------
        bool
        """
        return self.start < end and self.end > start

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vehicle_id": self.vehicle_id,
            "start": format_timestamp(self.start),
            "end": format_timestamp(self.end),
            "reason": self.reason,
            "created_at": format_timestamp(self.created_at) if self.created_at else None,
            "updated_at": format_timestamp(self.updated_at) if self.updated_at else None,
        }
