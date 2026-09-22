"""
The shuttle service schedule (S21).

The roster of when the fleet is meant to be in service. The time usage model
needs it to tell scheduled time apart from everything else; without it every
hour looks the same and effective utilisation cannot be computed.

Source of truth is `utilisation.service_hours` in config/app.yaml, so a
schedule change is a config change and the figures recalculate with no code
change. The admin page edits the same block through /api/schedule.

Shape, one list of periods per day. A period names the vehicles it is for, or
omits `vehicles` to mean the whole fleet, so one roster covers a fleet wide
timetable and a single bus running a different shift:

    service_hours:
      monday:
        - hours: ["08:00", "12:00"]
        - hours: ["13:00", "17:00"]
          vehicles: ["1", "2"]
      saturday:
        - hours: ["09:00", "13:00"]
          vehicles: ["3"]

A day that is absent or empty is simply not in service. That is not an error:
a fleet that does not run on Sundays is a normal schedule, and time outside
service counts as unscheduled. The same holds per vehicle, so a bus nobody
rostered is unscheduled all week rather than missing.

Times are local wall clock in `display.timezone`, because a roster is written
in local time. A period must end after it starts, so an overnight run that
crosses midnight cannot yet be expressed; it would need two rows on two days.
"""

from __future__ import annotations
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import yaml

log = logging.getLogger(__name__)

#: Day keys, Monday first to match `datetime.weekday()`.
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

#: Keys of the older single pair format, expanded on read.
LEGACY_WEEKDAY = "weekday"
LEGACY_WEEKEND = "weekend"

_INDENT = "  "


class ScheduleError(Exception):
    """
    The schedule is malformed, or it could not be written back.
    """


def _parse_time(value: Any) -> time:
    """
    Read one `HH:MM` wall clock time.

    Raises
    ------
    ScheduleError
        If it is not a time of day.
    """
    try:
        parsed = time.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ScheduleError(f"{value!r} is not a time of day, expected HH:MM") from exc
    if parsed.tzinfo is not None:
        raise ScheduleError(f"{value!r} must be a local wall clock time, without a timezone")
    return parsed


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


def _parse_vehicles(value: Any) -> Optional[frozenset[str]]:
    """
    Read a period's vehicle scope.

    Returns
    -------
    frozenset of str, or None
        None for the whole fleet, which is what an absent key, null, an empty
        list and the word "all" all mean. Naming no vehicle cannot sensibly
        mean "no vehicles", since such a period would never apply.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return None if value.strip().lower() == "all" else frozenset({value.strip()})
    if isinstance(value, (list, tuple, set, frozenset)):
        ids = {str(item).strip() for item in value if str(item).strip()}
        return frozenset(ids) or None
    raise ScheduleError(f"{value!r} is not a list of vehicle ids")


@dataclass(frozen=True)
class ServicePeriod:
    """
    One stretch of rostered service, and the vehicles it is for.

    Parameters
    ----------
    start, end : time
        Local wall clock, `end` strictly after `start`.
    vehicles : frozenset of str, optional
        None means every vehicle, now and any added later.
    """

    start: time
    end: time
    vehicles: Optional[frozenset[str]] = None

    @property
    def is_fleet_wide(self) -> bool:
        return self.vehicles is None

    def applies_to(self, vehicle_id: Optional[str]) -> bool:
        """
        Whether this period covers a vehicle.

        Parameters
        ----------
        vehicle_id : str, optional
            None asks "any vehicle at all", which every period answers.
        """
        return vehicle_id is None or self.vehicles is None or vehicle_id in self.vehicles

    def shares_vehicles_with(self, other: "ServicePeriod") -> bool:
        """
        Whether two periods could apply to the same vehicle at once.
        """
        if self.vehicles is None or other.vehicles is None:
            return True
        return bool(self.vehicles & other.vehicles)

    def covers_time(self, moment: time) -> bool:
        """
        Half open, so an instant exactly at the closing time is out.
        """
        return self.start <= moment < self.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": _format_time(self.start),
            "end": _format_time(self.end),
            "vehicles": None if self.vehicles is None else sorted(self.vehicles),
        }

    @property
    def _sort_key(self) -> tuple:
        return (self.start, self.end, tuple(sorted(self.vehicles or ())))


@dataclass(frozen=True)
class Schedule:
    """
    When the fleet is meant to be in service, as local wall clock periods.

    Parameters
    ----------
    periods : dict of {str: list of ServicePeriod}
        Day name to its periods, ascending. A day with no service is absent
        rather than present and empty.
    """

    periods: dict[str, list[ServicePeriod]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """
        True when no day has any service period, for any vehicle.
        """
        return not any(self.periods.values())

    def is_empty_for(self, vehicle_id: Optional[str]) -> bool:
        """
        True when nothing is rostered for one vehicle.

        A vehicle nobody scheduled is unscheduled all week. That is a real
        answer, not a missing one, and /api/metrics says so per vehicle.
        """
        return not any(
            period.applies_to(vehicle_id) for day in DAYS for period in self.periods.get(day, [])
        )

    def for_day(self, day: str, vehicle_id: Optional[str] = None) -> list[ServicePeriod]:
        """
        The periods rostered on one day name, optionally for one vehicle.
        """
        return [period for period in self.periods.get(day, []) if period.applies_to(vehicle_id)]

    def vehicle_ids(self) -> list[str]:
        """
        Every vehicle named anywhere in the roster, ascending.

        A fleet wide period names none, so this is not the fleet; it is who
        has been singled out.
        """
        named: set[str] = set()
        for rows in self.periods.values():
            for period in rows:
                named |= period.vehicles or frozenset()
        return sorted(named)

    def covers(self, moment: datetime, timezone: str, vehicle_id: Optional[str] = None) -> bool:
        """
        Whether an instant falls inside scheduled service time.

        Parameters
        ----------
        moment : datetime
            The instant. Naive values are read as UTC.
        timezone : str
            The zone the roster is written in, `display.timezone`.
        vehicle_id : str, optional
            None asks whether any vehicle is scheduled then.

        Returns
        -------
        bool
            False for an empty schedule, since nothing is rostered. Periods
            are half open, so an instant exactly at a closing time is out.
        """
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        local = moment.astimezone(ZoneInfo(timezone))
        return any(
            period.covers_time(local.time()) for period in self.for_day(DAYS[local.weekday()], vehicle_id)
        )

    @classmethod
    def from_config_block(cls, block: Optional[dict]) -> "Schedule":
        """
        Build from the `service_hours` mapping of config/app.yaml.

        Accepts the current shape, a list of `{hours, vehicles}` mappings per
        day, and the older shapes: a bare `["08:00", "17:00"]` pair, a list of
        such pairs, and `weekday`/`weekend` keys that expand across those
        days. Anything from the older shapes is fleet wide.

        Parameters
        ----------
        block : dict or None
            None or empty gives an empty schedule, never an error.

        Returns
        -------
        Schedule

        Raises
        ------
        ScheduleError
            If a day is unknown, a time is malformed, a period does not end
            after it starts, or two periods for the same vehicle overlap.
        """
        periods: dict[str, list[ServicePeriod]] = {}
        for key, value in (block or {}).items():
            day = str(key).strip().lower()
            if day == LEGACY_WEEKDAY:
                days: Sequence[str] = DAYS[:5]
            elif day == LEGACY_WEEKEND:
                days = DAYS[5:]
            elif day in DAYS:
                days = (day,)
            else:
                raise ScheduleError(f"{key!r} is not a day. Expected one of: {', '.join(DAYS)}")

            for target in days:
                periods.setdefault(target, []).extend(cls._parse_day(target, value))

        return cls(periods={day: _validated(day, rows) for day, rows in periods.items() if rows})

    @staticmethod
    def _parse_day(day: str, value: Any) -> list[ServicePeriod]:
        """
        One day's value, in any shape this module accepts.
        """
        if value is None:
            return []
        if not isinstance(value, list):
            raise ScheduleError(f"{day}: expected a list of periods, got {value!r}")
        # A bare ["08:00", "17:00"] is one period, not two malformed ones.
        if len(value) == 2 and all(isinstance(item, str) for item in value):
            value = [value]

        rows = []
        for entry in value:
            if isinstance(entry, dict):
                hours = entry.get("hours")
                if hours is None:
                    hours = [entry.get("start"), entry.get("end")]
                if not isinstance(hours, (list, tuple)) or len(hours) != 2:
                    raise ScheduleError(f"{day}: expected 'hours' as an [open, close] pair, got {entry!r}")
                rows.append(
                    ServicePeriod(_parse_time(hours[0]), _parse_time(hours[1]), _parse_vehicles(entry.get("vehicles")))
                )
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                rows.append(ServicePeriod(_parse_time(entry[0]), _parse_time(entry[1])))
            else:
                raise ScheduleError(f"{day}: expected an [open, close] pair or a period mapping, got {entry!r}")
        return rows

    @classmethod
    def from_dict(cls, payload: Any) -> "Schedule":
        """
        Build from the JSON body of a write, same shape as `to_dict`.

        Raises
        ------
        ScheduleError
            If the payload is not a mapping of day to periods.
        """
        if not isinstance(payload, dict):
            raise ScheduleError("Expected an object of day names to lists of periods")
        return cls.from_config_block(payload)

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        """
        Every day, in order, as period objects.

        A day with no service is present and empty, so a caller sees the whole
        week rather than having to know which days were omitted. `vehicles` is
        null for a fleet wide period.
        """
        return {day: [period.to_dict() for period in self.periods.get(day, [])] for day in DAYS}

    def to_yaml_block(self, indent: str = _INDENT * 2) -> str:
        """
        The `service_hours` value as YAML lines, for writing back to app.yaml.

        Only days that have service are written, and `vehicles` is left out of
        a fleet wide period, so the common timetable stays short.
        """
        lines = []
        for day in DAYS:
            rows = self.periods.get(day, [])
            if not rows:
                continue
            lines.append(f"{indent}{day}:")
            for period in rows:
                lines.append(f'{indent}{_INDENT}- hours: ["{_format_time(period.start)}", "{_format_time(period.end)}"]')
                if period.vehicles is not None:
                    listed = ", ".join(f'"{vehicle}"' for vehicle in sorted(period.vehicles))
                    lines.append(f"{indent}{_INDENT}  vehicles: [{listed}]")
        return "\n".join(lines)


def _validated(day: str, rows: Iterable[ServicePeriod]) -> list[ServicePeriod]:
    """
    Sort one day's periods and reject the ones the model cannot represent.

    Raises
    ------
    ScheduleError
        If a period does not end after it starts, or two periods that could
        apply to the same vehicle overlap. Overlapping periods would be
        counted twice in that vehicle's scheduled time, so they are refused
        rather than silently inflating the figures. Two periods for different
        vehicles may overlap freely, which is the point of a per vehicle
        roster.
    """
    ordered = sorted(rows, key=lambda period: period._sort_key)
    for period in ordered:
        if period.end <= period.start:
            raise ScheduleError(
                f"{day}: {_format_time(period.start)}-{_format_time(period.end)} must end after it starts. "
                "A period crossing midnight is not supported; split it across two days."
            )

    for index, period in enumerate(ordered):
        for other in ordered[index + 1 :]:
            if other.start >= period.end:
                continue
            if period.shares_vehicles_with(other):
                scope = "the whole fleet" if period.is_fleet_wide or other.is_fleet_wide else "the same vehicle"
                raise ScheduleError(
                    f"{day}: periods overlap at {_format_time(other.start)} for {scope}"
                )
    return ordered


def load_schedule(config_path: Path | str) -> Schedule:
    """
    Read the schedule out of an app.yaml.

    Parameters
    ----------
    config_path : Path or str

    Returns
    -------
    Schedule
        Empty if the file has no `utilisation.service_hours`.

    Raises
    ------
    ScheduleError
        If the file cannot be read, or the block is malformed.
    """
    try:
        with open(config_path, encoding="utf-8") as handle:
            document = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ScheduleError(f"Could not read {config_path}: {exc}") from exc

    return Schedule.from_config_block((document.get("utilisation") or {}).get("service_hours"))


def save_schedule(config_path: Path | str, schedule: Schedule) -> None:
    """
    Write the schedule back into an app.yaml, in place.

    Only the `service_hours` block is rewritten. The rest of the file, its
    ordering and its comments, is left byte for byte as it was, because
    app.yaml is hand maintained and round tripping it through a YAML dumper
    would strip every comment in it.

    The new text is parsed and compared against what was asked for before it
    replaces anything, and the swap itself is atomic, so a failed write leaves
    the previous file intact.

    Parameters
    ----------
    config_path : Path or str
    schedule : Schedule

    Raises
    ------
    ScheduleError
        If the file has no `utilisation:` section to write into, or the
        rewritten file would not read back as the schedule given.
    """
    path = Path(config_path)
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScheduleError(f"Could not read {path}: {exc}") from exc

    updated = _replace_block(original, schedule)

    # Never replace a good file with one we have not proved reads back.
    try:
        document = yaml.safe_load(updated) or {}
        written = Schedule.from_config_block((document.get("utilisation") or {}).get("service_hours"))
    except (yaml.YAMLError, ScheduleError) as exc:
        raise ScheduleError(f"Refusing to write {path}: the result would not parse ({exc})") from exc
    if written != schedule:
        raise ScheduleError(f"Refusing to write {path}: the result would not read back as the schedule given")

    _atomic_write(path, updated)
    log.info("wrote service schedule to %s", path)


def _replace_block(text: str, schedule: Schedule) -> str:
    """
    Swap the `service_hours` block of an app.yaml for this schedule.

    Returns
    -------
    str
        The whole file, with only that block changed. A schedule with no
        service at all is written as an empty mapping, which reads back as
        "nothing rostered" rather than vanishing into an absent key.

    Raises
    ------
    ScheduleError
        If there is no `utilisation:` section to put it in.
    """
    lines = text.splitlines()
    start = end = None
    indent = _INDENT

    for index, line in enumerate(lines):
        match = re.match(r"^(\s+)service_hours:\s*(#.*)?$", line)
        if match:
            indent = match.group(1)
            start = index
            end = _block_end(lines, index, len(indent))
            break

    body = schedule.to_yaml_block(indent + _INDENT)
    block = [f"{indent}service_hours:"] + ([body] if body else [f"{indent}{_INDENT}{{}}"])

    if start is None:
        # No block yet: append one to the end of the utilisation section.
        anchor = next((i for i, line in enumerate(lines) if re.match(r"^utilisation:\s*(#.*)?$", line)), None)
        if anchor is None:
            raise ScheduleError("app.yaml has no 'utilisation:' section to write service_hours into")
        start = end = _block_end(lines, anchor, 0)

    return "\n".join(lines[:start] + block + lines[end:]) + "\n"


def _block_end(lines: Sequence[str], start: int, indent_width: int) -> int:
    """
    Index just past the last line belonging to the block opened at `start`.

    A blank line inside the block belongs to it; trailing blanks do not, so
    the spacing between sections survives the rewrite.
    """
    end = start + 1
    last_content = end
    while end < len(lines):
        line = lines[end]
        if line.strip() and (len(line) - len(line.lstrip())) <= indent_width:
            break
        end += 1
        if line.strip():
            last_content = end
    return last_content


def _atomic_write(path: Path, text: str) -> None:
    """
    Replace a file's contents in one step.

    Raises
    ------
    ScheduleError
        If the file cannot be written.
    """
    handle = None
    try:
        fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
        handle = os.fdopen(fd, "w", encoding="utf-8")
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temporary, path)
    except OSError as exc:
        if handle is not None:
            handle.close()
        raise ScheduleError(f"Could not write {path}: {exc}") from exc
