"""
How recently a vehicle was last seen, as a traffic light beside "Last seen".

    green   last seen today, or on or after the last `green_within_weekdays`
            weekdays before today (with 1, a bus last seen on Friday is still
            green on Monday)
    red     last seen more than `red_after_days` calendar days ago
    yellow  anything in between

Days are Perth days, since "yesterday" means the operator's yesterday, not a
UTC one. Public holidays count as weekdays.
"""

from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Optional

from backend.api.params import PERTH_TZ


def _weekdays_before(day: date, count: int) -> date:
    """
    The date `count` weekdays before `day`, skipping Saturdays and Sundays.
    """
    while count > 0:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def freshness(
    last_seen: Optional[datetime], now: datetime, green_within_weekdays: int, red_after_days: int
) -> Optional[str]:
    """
    The traffic light for a vehicle last seen at `last_seen`.

    Returns
    -------
    str or None
        "green", "yellow" or "red". None when the vehicle has never been
        seen, since there is no age to judge.
    """
    if last_seen is None:
        return None

    today = now.astimezone(PERTH_TZ).date()
    seen = last_seen.astimezone(PERTH_TZ).date()

    if seen >= _weekdays_before(today, green_within_weekdays):
        return "green"
    if (today - seen).days > red_after_days:
        return "red"
    return "yellow"
