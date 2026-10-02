"""
When a vehicle was operating, split by whether that fell inside its rostered
service time or outside it.

Operating time is the GMG model's: working plus operating delay, exactly as
backend.metrics.tum.spans classifies the telemetry, so these intervals add up
to the same operating time /api/metrics reports. Scheduled time is the
vehicle's roster (backend.metrics.tum.service_periods), so a bus out of hours
shows as operating outside schedule even while another bus is rostered.

Kept apart from tum.py so the calendar's view of operating time adds a module
rather than changing the one /api/metrics depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from backend.metrics.tum import Settings, Span, State, service_periods, spans
from backend.models import Position, format_timestamp

#: The states GMG counts as operating time.
OPERATING = frozenset({State.WORKING, State.DELAY})


@dataclass(frozen=True)
class OperatingInterval:
    """
    One stretch of operating time, wholly inside or wholly outside schedule.

    `in_schedule` is None when scheduled time cannot be known, which is only
    when no timezone is configured to place the roster on a clock.
    """

    start: datetime
    end: datetime
    in_schedule: Optional[bool]

    def to_dict(self) -> dict:
        return {
            "start": format_timestamp(self.start),
            "end": format_timestamp(self.end),
            "in_schedule": self.in_schedule,
        }


def operating_stretches(classified: Sequence[Span]) -> list[tuple[datetime, datetime]]:
    """
    Operating time as continuous stretches: working and operating delay that
    follow one another are one stretch, since both are operating.
    """
    stretches: list[tuple[datetime, datetime]] = []
    for span in classified:
        if span.state not in OPERATING:
            continue
        if stretches and stretches[-1][1] == span.start:
            stretches[-1] = (stretches[-1][0], span.end)
        else:
            stretches.append((span.start, span.end))
    return stretches


def split_by_schedule(
    stretches: Sequence[tuple[datetime, datetime]],
    periods: Optional[Sequence[tuple[datetime, datetime]]],
) -> list[OperatingInterval]:
    """
    Cut each stretch where scheduled time starts or stops.

    Parameters
    ----------
    stretches : sequence of (start, end)
        Operating time, ascending and not overlapping.
    periods : sequence of (opens, closes), or None
        Scheduled time, ascending and not overlapping. Empty means nothing is
        rostered, so all operating time is outside schedule. None means it
        cannot be known, so nothing is marked either way.

    Returns
    -------
    list of OperatingInterval
        Ascending; together they cover exactly the stretches.
    """
    if periods is None:
        return [OperatingInterval(start, end, None) for start, end in stretches]

    intervals: list[OperatingInterval] = []
    for start, end in stretches:
        cursor = start
        for opens, closes in periods:
            if closes <= cursor or opens >= end:
                continue
            if opens > cursor:
                intervals.append(OperatingInterval(cursor, opens, False))
            inside_end = min(closes, end)
            intervals.append(OperatingInterval(max(opens, cursor), inside_end, True))
            cursor = inside_end
            if cursor >= end:
                break
        if cursor < end:
            intervals.append(OperatingInterval(cursor, end, False))
    return intervals


def operating_intervals(
    vehicle_id: str, positions: Sequence[Position], start: datetime, end: datetime, settings: Settings
) -> list[OperatingInterval]:
    """
    One vehicle's operating time over a window, split by its roster.

    Raises
    ------
    ValueError
        As backend.metrics.tum.spans: a required threshold is unset, or the
        window is empty.
    """
    stretches = operating_stretches(spans(positions, start, end, settings))
    return split_by_schedule(stretches, service_periods(start, end, settings, vehicle_id))
