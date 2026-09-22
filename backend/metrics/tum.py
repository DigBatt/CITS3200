"""
Time usage model as per the GMG 2020 guideline.

What the telemetry can and cannot answer:

    working           moving and reporting
    operating delay   stopped away from the depot, or no GPS fix
    standby           stopped at the depot, if a depot is configured

    downtime          NOT derivable, needs a fault or maintenance log
    available         NOT derivable, needs downtime
    productive/non    NOT derivable, needs passenger counts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from math import asin, cos, radians, sin, sqrt
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

from backend.models import Position, format_timestamp
from backend.schedule import DAYS, Schedule

EARTH_RADIUS_M = 6_371_000.0

#: KPIs the data cannot support
BLOCKED_KPIS = {
    "uptime": "needs downtime; no fault or maintenance log in the data",
    "mechanical_availability": "needs downtime; no fault or maintenance log in the data",
    "physical_availability": "needs available time, which needs downtime",
    "use_of_availability": "needs available time, which needs downtime",
    "production_effectiveness": "needs productive time; no passenger counts in the data",
}


class State(str, Enum):
    """
    What a vehicle was doing over one span.
    """

    WORKING = "working"
    DELAY = "operating_delay"
    STANDBY = "standby"
    NOT_REPORTING = "not_reporting"


@dataclass(frozen=True)
class Settings:
    """
    Thresholds from the `utilisation` block of config/app.yaml.
    """

    stationary_speed_mps: Optional[float] = None
    max_gap_seconds: Optional[float] = None
    min_standby_seconds: Optional[float] = None
    depot_centre: Optional[Sequence[float]] = None
    depot_radius_m: Optional[float] = None
    schedule: Optional[Schedule] = None
    timezone: Optional[str] = None

    @property
    def has_depot(self) -> bool:
        return self.depot_centre is not None and self.depot_radius_m is not None

    @classmethod
    def from_config(cls, config) -> "Settings":
        """
        Read the block from a backend.config.Config.
        Absent settings stay None.

        Parameters
        ----------
        config : backend.config.Config

        Returns
        -------
        Settings
        """
        block = config.utilisation or {}
        depot = block.get("depot") or {}
        return cls(
            stationary_speed_mps=block.get("stationary_speed_mps"),
            max_gap_seconds=block.get("max_gap_seconds"),
            min_standby_seconds=block.get("min_standby_seconds"),
            depot_centre=depot.get("centre"),
            depot_radius_m=depot.get("radius_m"),
            schedule=Schedule.from_config_block(block.get("service_hours")),
            timezone=config.timezone,
        )


@dataclass(frozen=True)
class Span:
    """
    One classified stretch of the window.
    """

    state: State
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass
class Utilisation:
    """
    GMG buckets and KPIs for one vehicle over one window.

    A bucket or KPI the data cannot support is None, and `unavailable` says
    what it is waiting on.
    """

    vehicle_id: str
    window_start: datetime
    window_end: datetime
    buckets: dict[str, Optional[float]] = field(default_factory=dict)
    kpis: dict[str, Optional[float]] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)
    #: Figures that are real but need explaining, unlike `unavailable` which
    #: explains a figure that is None. Keyed the same way.
    notes: dict[str, str] = field(default_factory=dict)

    def check(self) -> None:
        """
        Assert the guideline's rule that all time is accounted for.

        Raises
        ------
        AssertionError
            If the measured buckets do not sum to calendar time.
        """
        measured = sum(
            self.buckets[name] or 0.0
            for name in ("working_seconds", "operating_delay_seconds", "standby_seconds", "not_reporting_seconds")
        )
        calendar = self.buckets["calendar_seconds"] or 0.0
        assert abs(measured - calendar) < 1e-6, f"{measured} != {calendar}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "from": format_timestamp(self.window_start),
            "to": format_timestamp(self.window_end),
            "buckets": self.buckets,
            "kpis": self.kpis,
            "unavailable": self.unavailable,
            "notes": self.notes,
        }


def metres_between(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Great circle distance in metres between two (latitude, longitude) pairs.
    """
    lat1, lon1, lat2, lon2 = (radians(v) for v in (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))


def classify(position: Position, settings: Settings) -> State:
    """
    The state a sample implies until the next sample.

    Parameters
    ----------
    position : Position
    settings : Settings

    Returns
    -------
    State
        Never NOT_REPORTING; that is a property of the gap.
    """
    if position.gps_status == Position.NO_FIX or position.speed_mps is None:
        return State.DELAY
    if position.speed_mps >= settings.stationary_speed_mps:
        return State.WORKING
    if not settings.has_depot or position.latitude is None or position.longitude is None:
        return State.DELAY
    at_depot = metres_between((position.latitude, position.longitude), settings.depot_centre) <= settings.depot_radius_m
    return State.STANDBY if at_depot else State.DELAY


def spans(
    positions: Sequence[Position], start: datetime, end: datetime, settings: Settings
) -> list[Span]:
    """
    Tile [start, end) with classified spans.

    Parameters
    ----------
    positions : sequence of Position
        Ascending by timestamp.
    start, end : datetime
        The reporting window, UTC.
    settings : Settings

    Returns
    -------
    list of Span
        Adjacent spans of the same state merged.

    Raises
    ------
    ValueError
        If a required threshold is unset, or the window is empty.
    """
    if settings.stationary_speed_mps is None:
        raise ValueError("config/app.yaml does not set utilisation.stationary_speed_mps")
    if settings.max_gap_seconds is None:
        raise ValueError("config/app.yaml does not set utilisation.max_gap_seconds")
    if settings.has_depot and settings.min_standby_seconds is None:
        raise ValueError("config/app.yaml does not set utilisation.min_standby_seconds")
    if end <= start:
        raise ValueError("empty reporting window")

    inside = [p for p in positions if start <= p.timestamp < end]
    raw: list[Span] = []
    cursor = start

    for index, position in enumerate(inside):
        if position.timestamp > cursor:
            raw.append(Span(State.NOT_REPORTING, cursor, position.timestamp))
        next_stamp = inside[index + 1].timestamp if index + 1 < len(inside) else end
        span_end = min(next_stamp, end)
        gap = (span_end - position.timestamp).total_seconds()
        state = classify(position, settings) if gap <= settings.max_gap_seconds else State.NOT_REPORTING
        raw.append(Span(state, position.timestamp, span_end))
        cursor = span_end

    if cursor < end:
        raw.append(Span(State.NOT_REPORTING, cursor, end))

    return _apply_min_standby(_merge(raw), settings)


def _merge(raw: Sequence[Span]) -> list[Span]:
    """
    Join adjacent spans that share a state.
    """
    merged: list[Span] = []
    for span in raw:
        if merged and merged[-1].state == span.state and merged[-1].end == span.start:
            merged[-1] = Span(span.state, merged[-1].start, span.end)
        else:
            merged.append(span)
    return merged


def _apply_min_standby(merged: Sequence[Span], settings: Settings) -> list[Span]:
    """
    Demote standby shorter than the minimum to an operating delay.
    """
    if not settings.has_depot:
        return list(merged)
    demoted = [
        Span(State.DELAY, s.start, s.end)
        if s.state == State.STANDBY and s.seconds < settings.min_standby_seconds
        else s
        for s in merged
    ]
    return _merge(demoted)


def service_periods(
    start: datetime, end: datetime, settings: Settings, vehicle_id: Optional[str] = None
) -> Optional[list[tuple[datetime, datetime]]]:
    """
    Service periods overlapping the window, each clipped to it.

    The roster is read in the display timezone, since it is written in local
    time. Every day of the week is looked up separately and a day may hold
    several periods, so a split shift or a Saturday timetable is expressed
    directly. Public holidays and per vehicle rosters are not modelled.

    Parameters
    ----------
    start, end : datetime
        The reporting window, UTC.
    settings : Settings
    vehicle_id : str, optional
        Whose roster to read. A period naming no vehicle is fleet wide and
        applies to all of them. None pools every period, which answers "was
        anything scheduled" rather than "was this bus scheduled".

    Returns
    -------
    list of (datetime, datetime) or None
        Ascending (opens, closes) pairs, clipped to the window.

        Empty when nothing is rostered, which is a real answer: no schedule
        means no scheduled time, so the whole window is unscheduled. Callers
        should say so rather than treat it as missing, see `summarise`.

        None only when the timezone is unset, since a local roster cannot be
        placed on a clock without one. That is a broken config, not an empty
        schedule.
    """
    if settings.timezone is None:
        return None

    schedule = settings.schedule or Schedule()
    tz = ZoneInfo(settings.timezone)
    periods: list[tuple[datetime, datetime]] = []
    day: date = start.astimezone(tz).date()
    last: date = end.astimezone(tz).date()

    while day <= last:
        for period in schedule.for_day(DAYS[day.weekday()], vehicle_id):
            opens = max(datetime.combine(day, period.start, tzinfo=tz), start)
            closes = min(datetime.combine(day, period.end, tzinfo=tz), end)
            if closes > opens:
                periods.append((opens, closes))
        day += timedelta(days=1)

    return sorted(periods)


def scheduled_seconds(
    start: datetime, end: datetime, settings: Settings, vehicle_id: Optional[str] = None
) -> Optional[float]:
    """
    Service hours overlapping the window, in seconds.

    Returns
    -------
    float or None
        None when scheduled time is unknown, see `service_periods`.
    """
    periods = service_periods(start, end, settings, vehicle_id)
    return None if periods is None else sum(((closes - opens).total_seconds() for opens, closes in periods), 0.0)


def seconds_within(span: Span, periods: Sequence[tuple[datetime, datetime]]) -> float:
    """
    How much of a span falls inside the given periods.
    """
    return sum((max(0.0, (min(span.end, closes) - max(span.start, opens)).total_seconds()) for opens, closes in periods), 0.0)


def summarise(
    vehicle_id: str, positions: Sequence[Position], start: datetime, end: datetime, settings: Settings
) -> Utilisation:
    """
    Buckets and KPIs for one vehicle over one window.

    Parameters
    ----------
    vehicle_id : str
    positions : sequence of Position
        Ascending by timestamp.
    start, end : datetime
        The reporting window, UTC.
    settings : Settings

    Returns
    -------
    Utilisation
        Buckets and KPIs the telemetry supports, None and a reason for the
        rest.

    Raises
    ------
    ValueError
        If a required threshold is unset, or the window is empty.
    """
    classified = spans(positions, start, end, settings)
    totals = {state: 0.0 for state in State}
    for span in classified:
        totals[span.state] += span.seconds

    calendar = (end - start).total_seconds()
    working = totals[State.WORKING]
    delay = totals[State.DELAY]
    standby = totals[State.STANDBY]
    operating = working + delay
    scheduled = scheduled_seconds(start, end, settings, vehicle_id)
    periods = service_periods(start, end, settings, vehicle_id)
    # GMG nests working time inside scheduled time, so effective utilisation
    # counts only the working time that fell within service hours.
    scheduled_working = (
        None
        if periods is None
        else sum((seconds_within(span, periods) for span in classified if span.state == State.WORKING), 0.0)
    )

    result = Utilisation(vehicle_id=vehicle_id, window_start=start, window_end=end)
    result.buckets = {
        "calendar_seconds": calendar,
        "working_seconds": working,
        "operating_delay_seconds": delay,
        "standby_seconds": standby,
        "not_reporting_seconds": totals[State.NOT_REPORTING],
        "operating_seconds": operating,
        "scheduled_seconds": scheduled,
        "scheduled_working_seconds": scheduled_working,
        "unscheduled_seconds": calendar - scheduled if scheduled is not None else None,
        "downtime_seconds": None,
        "available_seconds": None,
        "productive_seconds": None,
    }
    result.kpis = {
        "asset_utilisation": operating / calendar,
        "operating_efficiency": working / operating if operating else None,
        "effective_utilisation": scheduled_working / scheduled if scheduled else None,
        **{name: None for name in BLOCKED_KPIS},
    }

    result.unavailable = dict(BLOCKED_KPIS)
    if scheduled is None:
        result.unavailable["effective_utilisation"] = (
            "needs a timezone; config/app.yaml does not set display.timezone"
        )
        result.unavailable["scheduled_seconds"] = result.unavailable["effective_utilisation"]
        result.unavailable["scheduled_working_seconds"] = result.unavailable["effective_utilisation"]
    elif settings.schedule is None or settings.schedule.is_empty_for(vehicle_id):
        # S21: nothing rostered is a real figure, not a missing one. Scheduled
        # time is zero and the window is unscheduled; the note says why, so
        # the dashboard does not read it as the fleet having been idle.
        #
        # Per vehicle, since the roster is: a bus nobody scheduled says so,
        # even while the rest of the fleet has a timetable.
        note = (
            "No service schedule is in the system, so all time counts as unscheduled."
            if settings.schedule is None or settings.schedule.is_empty
            else "No service schedule is in the system for this vehicle, so all its time counts as unscheduled."
        )
        result.notes["scheduled_seconds"] = note
        result.notes["unscheduled_seconds"] = note
        result.unavailable["effective_utilisation"] = (
            "needs scheduled time; no service schedule is in the system"
        )
    if not operating:
        result.unavailable["operating_efficiency"] = "no operating time in this window"
    if not settings.has_depot:
        result.unavailable["standby_seconds"] = (
            "needs a depot; config/app.yaml does not set utilisation.depot, so stopped time "
            "counts as operating delay"
        )
    result.unavailable["downtime_seconds"] = BLOCKED_KPIS["uptime"]
    result.unavailable["available_seconds"] = BLOCKED_KPIS["physical_availability"]
    result.unavailable["productive_seconds"] = BLOCKED_KPIS["production_effectiveness"]

    result.check()
    return result
