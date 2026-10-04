"""
Time usage model as per the GMG 2020 guideline.

What the telemetry can and cannot answer:

    working           moving and reporting
    operating delay   stopped away from the depot, or no GPS fix
    standby           stopped at the depot, if a depot is configured

    downtime          not in the telemetry; from the admin page's log (S19)
    available         scheduled time less that downtime
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

#: The KPIs a downtime log unblocks (S19)
DOWNTIME_KPIS = ("uptime", "mechanical_availability", "physical_availability", "use_of_availability")


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """
    `numerator / denominator`, or None when either is unknown or the
    denominator is zero, since nothing to divide by is not 0%.
    """
    if numerator is None or not denominator:
        return None
    return numerator / denominator


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
    #: How the downtime log was applied (S19), see `downtime_treatment`.
    #: None when there is no log.
    downtime: Optional[dict[str, Any]] = None

    def check(self) -> None:
        """
        Assert the guideline's rule that all time is accounted for.

        Raises
        ------
        AssertionError
            If the measured buckets and downtime do not sum to calendar time.
        """
        measured = sum(
            self.buckets[name] or 0.0
            for name in (
                "working_seconds",
                "operating_delay_seconds",
                "standby_seconds",
                "not_reporting_seconds",
                "downtime_seconds",
            )
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
            "downtime": self.downtime,
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
            # S21: a period booked to start later, or already ended, does
            # not count on this day.
            if not period.applies_on(day):
                continue
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
    return overlap_seconds(span.start, span.end, periods)


def overlap_seconds(start: datetime, end: datetime, periods: Sequence[tuple[datetime, datetime]]) -> float:
    """
    How much of `start`..`end` falls inside the given periods.
    """
    return sum((max(0.0, (min(end, closes) - max(start, opens)).total_seconds()) for opens, closes in periods), 0.0)


def scheduled_downtime(
    downtime: Sequence[tuple[datetime, datetime]], periods: Sequence[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """
    The parts of the downtime that fall inside the roster.

    GMG nests downtime inside scheduled time (`AT = ST - DT`), so a repair
    while the bus was not rostered takes nothing from its availability.

    Parameters
    ----------
    downtime : sequence of (datetime, datetime)
        Disjoint, as `backend.downtime.merged_intervals` returns them.
    periods : sequence of (datetime, datetime)
        This vehicle's service periods, as `service_periods` returns them.

    Returns
    -------
    list of (datetime, datetime)
        Ascending and disjoint.
    """
    pieces = [
        (max(lo, opens), min(hi, closes))
        for lo, hi in downtime
        for opens, closes in periods
        if max(lo, opens) < min(hi, closes)
    ]
    return sorted(pieces)


def without(classified: Sequence[Span], cut: Sequence[tuple[datetime, datetime]]) -> list[Span]:
    """
    The spans with the given periods cut out of them.

    Downtime replaces whatever the telemetry said over the same time, so the
    buckets and downtime still add up to calendar time.

    Parameters
    ----------
    classified : sequence of Span
    cut : sequence of (datetime, datetime)
        Ascending and disjoint.

    Returns
    -------
    list of Span
        What is left of each span, keeping its state.
    """
    kept: list[Span] = []
    for span in classified:
        cursor = span.start
        for lo, hi in cut:
            if hi <= cursor or lo >= span.end:
                continue
            if lo > cursor:
                kept.append(Span(span.state, cursor, lo))
            cursor = hi
        if cursor < span.end:
            kept.append(Span(span.state, cursor, span.end))
    return kept


def downtime_treatment(
    recorded: float, counted: Optional[float], replaced: dict[State, float]
) -> dict[str, Any]:
    """
    How much downtime was recorded and what was done with it, for the API.

    Parameters
    ----------
    recorded : float
        Downtime in the window, inside the roster or not.
    counted : float or None
        The part inside the roster, which became the downtime bucket. None
        when the roster cannot be placed, so nothing was counted.
    replaced : dict of {State: float}
        Telemetry time the counted downtime took the place of, by state.

    Returns
    -------
    dict
        `recorded_seconds`, `counted_seconds`, `outside_roster_seconds`,
        `replaced_seconds` keyed by bucket name, and `summary`, one sentence.
    """
    outside = None if counted is None else recorded - counted
    replaced_seconds = {f"{state.value}_seconds": seconds for state, seconds in replaced.items() if seconds}

    parts = []
    if counted:
        took = ", ".join(f"{_format_duration(s)} {state.value.replace('_', ' ')}" for state, s in replaced.items() if s)
        parts.append(f"{_format_duration(counted)} in service hours counted as downtime, in place of {took}")
    if outside:
        parts.append(f"{_format_duration(outside)} outside service hours left out, since the bus was not rostered then")
    summary = f"{_format_duration(recorded)} of downtime recorded"
    summary += f": {'; '.join(parts)}." if parts else "."

    return {
        "recorded_seconds": recorded,
        "counted_seconds": counted,
        "outside_roster_seconds": outside,
        "replaced_seconds": replaced_seconds,
        "summary": summary,
    }


def _format_duration(seconds: float) -> str:
    """
    `5400` as "1 h 30 min", rounded to the minute; under a minute in seconds.
    """
    if seconds < 60:
        return f"{round(seconds)} s"
    hours, minutes = divmod(round(seconds / 60), 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def summarise(
    vehicle_id: str,
    positions: Sequence[Position],
    start: datetime,
    end: datetime,
    settings: Settings,
    downtime: Optional[Sequence[tuple[datetime, datetime]]] = None,
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
    downtime : sequence of (datetime, datetime) or None
        This vehicle's downtime as disjoint periods clipped to the window,
        from `backend.downtime.merged_intervals`. None means there is no
        downtime log at all, so the KPIs that need downtime stay blocked; an
        empty list means the log exists and records none. Only downtime
        inside this vehicle's roster is counted.

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
    scheduled = scheduled_seconds(start, end, settings, vehicle_id)
    periods = service_periods(start, end, settings, vehicle_id)
    # Unknown without a log, or without a timezone to place the roster in.
    counted = None if downtime is None or periods is None else scheduled_downtime(downtime, periods)
    downtime_seconds = None if counted is None else sum(((hi - lo).total_seconds() for lo, hi in counted), 0.0)

    measured = spans(positions, start, end, settings)
    classified = without(measured, counted) if counted else measured
    totals = {state: 0.0 for state in State}
    for span in classified:
        totals[span.state] += span.seconds
    # What the counted downtime took the place of, by state.
    replaced = {state: 0.0 for state in State}
    for span in measured:
        replaced[span.state] += span.seconds
    for state in State:
        replaced[state] -= totals[state]

    calendar = (end - start).total_seconds()
    working = totals[State.WORKING]
    delay = totals[State.DELAY]
    standby = totals[State.STANDBY]
    operating = working + delay
    # GMG nests working time inside scheduled time, so effective utilisation
    # counts only the working time that fell within service hours.
    scheduled_working = (
        None
        if periods is None
        else sum((seconds_within(span, periods) for span in classified if span.state == State.WORKING), 0.0)
    )
    # Likewise operating time, so the availability KPIs compare like with
    # like: AT is inside the roster, so OT/AT must be too, or it could top 100%.
    scheduled_operating = (
        None
        if periods is None
        else sum(
            (seconds_within(span, periods) for span in classified if span.state in (State.WORKING, State.DELAY)),
            0.0,
        )
    )
    available = None if downtime_seconds is None else scheduled - downtime_seconds

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
        "scheduled_operating_seconds": scheduled_operating,
        "unscheduled_seconds": calendar - scheduled if scheduled is not None else None,
        "downtime_seconds": downtime_seconds,
        "available_seconds": available,
        "productive_seconds": None,
    }
    result.kpis = {
        "asset_utilisation": operating / calendar,
        "operating_efficiency": working / operating if operating else None,
        "effective_utilisation": scheduled_working / scheduled if scheduled else None,
        **{name: None for name in BLOCKED_KPIS},
    }

    result.unavailable = dict(BLOCKED_KPIS)
    if available is not None:
        # S19: the admin page's downtime log unblocks the availability KPIs.
        result.kpis["uptime"] = available / calendar
        result.kpis["mechanical_availability"] = _ratio(scheduled_operating, scheduled_operating + downtime_seconds)
        result.kpis["physical_availability"] = _ratio(available, scheduled)
        result.kpis["use_of_availability"] = _ratio(scheduled_operating, available)
        for name in DOWNTIME_KPIS:
            del result.unavailable[name]
        if result.kpis["mechanical_availability"] is None:
            result.unavailable["mechanical_availability"] = "no operating time or downtime in service hours in this window"
        if result.kpis["physical_availability"] is None:
            result.unavailable["physical_availability"] = "no scheduled service time in this window"
        if result.kpis["use_of_availability"] is None:
            result.unavailable["use_of_availability"] = "no available time in this window"
    elif downtime is not None:
        # A log, but no timezone to place the roster in.
        for name in DOWNTIME_KPIS:
            result.unavailable[name] = "needs a timezone; config/app.yaml does not set display.timezone"
    if scheduled is None:
        result.unavailable["effective_utilisation"] = (
            "needs a timezone; config/app.yaml does not set display.timezone"
        )
        result.unavailable["scheduled_seconds"] = result.unavailable["effective_utilisation"]
        result.unavailable["scheduled_working_seconds"] = result.unavailable["effective_utilisation"]
        result.unavailable["scheduled_operating_seconds"] = result.unavailable["effective_utilisation"]
        result.unavailable["unscheduled_seconds"] = result.unavailable["effective_utilisation"]
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
        if downtime is not None:
            # S19: downtime only counts inside the roster, so with none it is
            # 0, and so is available time and uptime.
            result.notes["downtime_seconds"] = note
            result.notes["available_seconds"] = note
            result.notes["uptime"] = note
        result.unavailable["effective_utilisation"] = (
            "needs scheduled time; no service schedule is in the system"
        )
    elif not scheduled:
        # Scheduled time is known and is zero, e.g. a weekend: the ratio has
        # nothing to divide by, which is not the same as 0%.
        result.unavailable["effective_utilisation"] = "no scheduled service time in this window"
    if not operating:
        result.unavailable["operating_efficiency"] = "no operating time in this window"
    if not settings.has_depot:
        result.unavailable["standby_seconds"] = (
            "needs a depot; config/app.yaml does not set utilisation.depot, so stopped time "
            "counts as operating delay"
        )
    if downtime is None:
        result.unavailable["downtime_seconds"] = BLOCKED_KPIS["uptime"]
        result.unavailable["available_seconds"] = BLOCKED_KPIS["physical_availability"]
    elif periods is None:
        result.unavailable["downtime_seconds"] = "needs a timezone; config/app.yaml does not set display.timezone"
        result.unavailable["available_seconds"] = result.unavailable["downtime_seconds"]
    result.unavailable["productive_seconds"] = BLOCKED_KPIS["production_effectiveness"]

    if downtime is not None:
        recorded = sum(((hi - lo).total_seconds() for lo, hi in downtime), 0.0)
        result.downtime = downtime_treatment(recorded, downtime_seconds, replaced)
        if recorded:
            result.notes["downtime_seconds"] = result.downtime["summary"]

    result.check()
    return result
