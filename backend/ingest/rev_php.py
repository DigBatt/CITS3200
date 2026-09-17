"""
The REV tracking endpoints, https://revproject.com/tracking/gps_pos{,2,3,4}.php.

Each returns the latest snapshot the vehicle posted:

    {"lat": -31.98, "lon": 115.82, "heading": 105.77,
     "battery_percentage": 0, "timestamp": 1747300465}

Mapping onto the schema (docs/data-schema.md):

    timestamp           -> timestamp        unix seconds, the vehicle's clock
    lat, lon            -> latitude, longitude
                                            null unless present, finite, inside
                                            the configured bounds and not (0, 0)
    heading             -> heading_deg      East=0 anticlockwise to compass
                                            bearing, (90 - h) % 360. 0 is unset
    battery_percentage  -> battery_percent  0 is unset
    (derived)           -> gps_status       0 with coordinates, -1 without
    (derived)           -> speed_mps        distance from the previous fix
    (absent)            -> altitude_m       always null
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Optional

from backend.metrics.tum import metres_between
from backend.models import Position


class PayloadError(ValueError):
    """
    The response cannot become a row at all.
    """


@dataclass(frozen=True)
class Settings:
    """
    What the mapping needs from config/app.yaml.
    """

    latitude_bounds: Optional[tuple[float, float]] = None
    longitude_bounds: Optional[tuple[float, float]] = None
    max_gap_seconds: Optional[float] = None
    max_clock_skew_seconds: float = 300.0

    @classmethod
    def from_config(cls, config) -> "Settings":
        """
        Read `logger.bounds` and `utilisation.max_gap_seconds`.
        Absent settings stay None.

        Parameters
        ----------
        config : backend.config.Config

        Returns
        -------
        Settings
        """
        bounds = (config.logger or {}).get("bounds") or {}
        latitude, longitude = bounds.get("latitude"), bounds.get("longitude")
        return cls(
            latitude_bounds=tuple(latitude) if latitude else None,
            longitude_bounds=tuple(longitude) if longitude else None,
            max_gap_seconds=(config.utilisation or {}).get("max_gap_seconds"),
        )


def parse(
    vehicle_id: str,
    payload: Any,
    previous: Optional[Position],
    settings: Settings,
    now: datetime,
) -> Position:
    """
    Map one decoded response onto the schema.

    Parameters
    ----------
    vehicle_id : str
        The vehicle the endpoint belongs to; the payload does not carry it.
    payload : Any
        The decoded JSON body.
    previous : Position or None
        The last stored row for this vehicle, for deriving speed.
    settings : Settings
    now : datetime
        Current UTC time, to reject timestamps from the future.

    Returns
    -------
    Position
        With `gps_status` -1 and null coordinates when the fix is missing or
        implausible.

    Raises
    ------
    PayloadError
        If the payload is not an object, or has no usable timestamp. A
        timestamp more than `max_clock_skew_seconds` ahead of `now` is
        unusable: stored, it would outrank every real row after it.
    """
    if not isinstance(payload, dict):
        raise PayloadError(f"expected a JSON object, got {type(payload).__name__}")

    seconds = _number(payload.get("timestamp"))
    if seconds is None or seconds <= 0:
        raise PayloadError(f"no usable timestamp: {payload.get('timestamp')!r}")
    try:
        timestamp = datetime.fromtimestamp(int(seconds), timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise PayloadError(f"timestamp {seconds!r} is out of range") from exc
    if timestamp > now + timedelta(seconds=settings.max_clock_skew_seconds):
        raise PayloadError(f"timestamp {timestamp.isoformat()} is in the future")

    latitude, longitude = _number(payload.get("lat")), _number(payload.get("lon"))
    has_fix = (
        latitude is not None
        and longitude is not None
        and (latitude, longitude) != (0.0, 0.0)
        and _within(latitude, settings.latitude_bounds)
        and _within(longitude, settings.longitude_bounds)
    )
    if not has_fix:
        latitude = longitude = None

    heading = _number(payload.get("heading"))
    battery = _number(payload.get("battery_percentage"))

    return Position(
        vehicle_id=vehicle_id,
        timestamp=timestamp,
        latitude=latitude,
        longitude=longitude,
        heading_deg=(90.0 - heading) % 360.0 if heading else None,
        speed_mps=_speed(previous, timestamp, latitude, longitude, settings) if has_fix else None,
        gps_status=0 if has_fix else Position.NO_FIX,
        battery_percent=battery if battery is not None and 0 < battery <= 100 else None,
    )


def _number(value: Any) -> Optional[float]:
    """
    A finite float, or None. Booleans and strings are not numbers here.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if isfinite(value) else None


def _within(value: float, bounds: Optional[tuple[float, float]]) -> bool:
    """
    Inclusive range test. No bounds admits everything.
    """
    return bounds is None or bounds[0] <= value <= bounds[1]


def _speed(
    previous: Optional[Position],
    timestamp: datetime,
    latitude: float,
    longitude: float,
    settings: Settings,
) -> Optional[float]:
    """
    Metres per second from the previous fix.

    None without a previous fix, or when the gap is not positive or is longer
    than `max_gap_seconds`, since speed over a gap says nothing about now.
    """
    if previous is None or previous.latitude is None or previous.longitude is None:
        return None
    seconds = (timestamp - previous.timestamp).total_seconds()
    if seconds <= 0 or (settings.max_gap_seconds is not None and seconds > settings.max_gap_seconds):
        return None
    return metres_between((previous.latitude, previous.longitude), (latitude, longitude)) / seconds
