"""
When riders may request a pickup at all (S15 follow-up).

Deliberately separate from `utilisation.service_hours` (backend/schedule.py):
that is the fleet's roster for the time usage model, per vehicle, editable
from the admin page and merged with the synced calendar. This is the simpler,
public question "is the shuttle running right now", one open/close window a
day for the whole service, hand kept in `pickup_requests.operating_hours` of
config/app.yaml:

    pickup_requests:
      operating_hours:
        monday: ["07:00", "19:00"]
        tuesday: ["07:00", "19:00"]

A day left out (weekends, in the sample above) has no service that day. Like
`pickup_requests.expire_after_seconds`, leaving the whole block out turns the
feature off rather than closing the service every day, so an existing
deployment that never sets it keeps working exactly as before. Times are
local wall clock in `display.timezone`, same as the roster.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo

#: Day keys, Monday first to match `datetime.weekday()`.
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class OperatingHoursError(Exception):
    """
    The `pickup_requests.operating_hours` block is malformed.
    """


def _parse_time(value: Any, where: str) -> time:
    try:
        parsed = time.fromisoformat(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise OperatingHoursError(f"{where}: {value!r} is not a time of day, expected HH:MM") from exc
    if parsed.tzinfo is not None:
        raise OperatingHoursError(f"{where}: must be a local wall clock time, without a timezone")
    return parsed


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


@dataclass(frozen=True)
class OperatingHours:
    """
    One open/close window per day. A day absent from `windows` has no service.

    Parameters
    ----------
    windows : dict of {str: (time, time)}
        Day name to (open, close), `close` strictly after `open`.
    configured : bool
        False only when `pickup_requests.operating_hours` was left out of
        app.yaml entirely, which turns the whole check off (`covers` always
        true) rather than refusing every request. True even if every day
        ended up with no window, since that was still a deliberate choice.
    """

    windows: dict[str, tuple[time, time]]
    configured: bool = True

    @classmethod
    def from_config_block(cls, block: Optional[dict]) -> "OperatingHours":
        """
        Build from the `pickup_requests.operating_hours` mapping of app.yaml.

        Parameters
        ----------
        block : dict or None
            None or `{}` means the feature is off: `covers` always answers
            true, so a deployment that never sets this is unaffected.

        Raises
        ------
        OperatingHoursError
            If a day name is unknown, a time is malformed, or a window does
            not end after it starts.
        """
        if not block:
            return cls(windows={}, configured=False)

        windows: dict[str, tuple[time, time]] = {}
        for key, value in block.items():
            day = str(key).strip().lower()
            if day not in DAYS:
                raise OperatingHoursError(f"{key!r} is not a day. Expected one of: {', '.join(DAYS)}")
            if value is None:
                continue
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise OperatingHoursError(f"{day}: expected an [open, close] pair, got {value!r}")
            start = _parse_time(value[0], f"{day} open")
            end = _parse_time(value[1], f"{day} close")
            if end <= start:
                raise OperatingHoursError(
                    f"{day}: {_format_time(start)}-{_format_time(end)} must close after it opens. "
                    "A window crossing midnight is not supported."
                )
            windows[day] = (start, end)
        return cls(windows=windows, configured=True)

    def window_for(self, day: str) -> Optional[tuple[time, time]]:
        """
        The (open, close) pair for a day name, or None if there is no service.
        """
        return self.windows.get(day)

    def covers(self, moment: datetime, timezone: str) -> bool:
        """
        Whether `moment` falls inside a configured window.

        Parameters
        ----------
        moment : datetime
            The instant. Naive values are read as UTC.
        timezone : str
            The zone the hours are written in, `display.timezone`.

        Returns
        -------
        bool
            True, never an error, when the feature is off (`configured` is
            False) or `timezone` is not set, since neither is a reason to
            turn riders away. Otherwise false for a day with no window.
            Half open, so an instant exactly at the closing time is out,
            same as the service roster.
        """
        if not self.configured or not timezone:
            return True
        day, local_time = local_day_and_time(moment, timezone)
        window = self.windows.get(day)
        return window is not None and window[0] <= local_time < window[1]

    def to_dict(self) -> dict[str, Optional[list[str]]]:
        """
        Every day, Monday first, `[open, close]` or null when there is none.
        """
        result: dict[str, Optional[list[str]]] = {}
        for day in DAYS:
            window = self.windows.get(day)
            result[day] = [_format_time(window[0]), _format_time(window[1])] if window else None
        return result


def local_day_and_time(moment: datetime, timezone: str) -> tuple[str, time]:
    """
    The day name (one of `DAYS`) and wall clock time of an instant, local to
    `timezone`. Naive `moment` is read as UTC.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    local = moment.astimezone(ZoneInfo(timezone))
    return DAYS[local.weekday()], local.time()
