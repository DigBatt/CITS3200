"""
The driving roster, synced from a calendar.online calendar.

The drivers book their shifts on a shared calendar.online calendar, so that is
where the roster really lives. This module reads it on a timer and turns each
drive into a one-day period of the service schedule, naming its operator, so
the calendar and the utilisation figures follow it with nobody copying shifts
across by hand.

READ ONLY. It only ever GETs the events the calendar's own page loads; it
never writes to the calendar.

Where it goes:

    config/app.yaml `roster_sync`   which events count and which bus they are
    config/secrets.yaml             `calendar_online_id`, the calendar's link
                                    id. Anyone holding it can open the
                                    calendar, so it is never committed.
    storage.directory/roster_sync.json
                                    the last good copy, so a restart or an
                                    outage of calendar.online leaves the
                                    roster as it was rather than empty.

The calendar's API answers with every occurrence of a repeating event already
expanded, each with a local wall clock start and end in the time zone asked
for, so a drive maps straight onto a period on its weekday, from its date to
the next. A cancelled week is simply absent, and disappears from the roster
on the next sync.

Synced periods sit beside the hand kept roster in app.yaml rather than in it,
so the admin page's Schedule editor never writes them back as if they were its
own. Where one would overlap a hand kept period for the same bus, the hand
kept one wins and the drive is reported as a conflict.
"""

from __future__ import annotations
import json
import logging
import re
import threading
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import yaml

from backend.files import write_json_atomic
from backend.ingest.fetch import FetchError, fetch_json
from backend.schedule import DAYS, Schedule, ScheduleError, ServicePeriod, _validated

log = logging.getLogger(__name__)

SOURCE = "calendar.online"
API_URL = "https://api.calendar.online/event"
SECRET_KEY = "calendar_online_id"
FILE_NAME = "roster_sync.json"
FILE_VERSION = 1
#: The calendar's wall clock format, in the time zone asked for.
EVENT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
#: Generous: a year of weekly drives is well under this.
MAX_BODY_BYTES = 2 * 1024 * 1024
#: A bus named in an event title, "nUWAy 2", picks that bus.
VEHICLE_IN_TITLE = re.compile(r"\bnuway\s*(\d+)\b", re.IGNORECASE)
#: A calendar link id, as it appears in the calendar's address.
CALENDAR_ID = re.compile(r"^[A-Za-z0-9]{8,64}$")


class SyncError(Exception):
    """
    The calendar could not be read, or what came back made no sense.
    """


# ---- Settings ----


@dataclass(frozen=True)
class SyncSettings:
    """
    The `roster_sync` block of config/app.yaml, and the calendar id.

    Parameters
    ----------
    calendar_id : str
        The id in the calendar's address, from secrets.yaml.
    vehicles : tuple of str
        The bus a drive is for when its title names none.
    sub_calendars : frozenset of int
        Sub-calendars whose timed events are all drives.
    title_pattern : re.Pattern, optional
        A timed event elsewhere on the calendar counts too when its title
        matches, so a one-off demo booked under Events still shows.
    timezone : str
        The roster's time zone, `display.timezone`; events are asked for in it.
    """

    calendar_id: str
    vehicles: tuple[str, ...]
    sub_calendars: frozenset[int] = frozenset()
    title_pattern: Optional[re.Pattern] = None
    timezone: str = "UTC"
    interval_seconds: float = 900
    days_back: int = 56
    days_ahead: int = 120
    timeout_seconds: float = 15
    user_agent: str = "Mozilla/5.0"

    @classmethod
    def load(cls, config, config_dir: Path | str) -> Optional["SyncSettings"]:
        """
        The settings, or None when syncing is off.

        Syncing is on when app.yaml has a `roster_sync` block and secrets.yaml
        sets `calendar_online_id`. Either missing is not an error: the roster
        is then the hand kept one alone.

        Raises
        ------
        SyncError
            If either is present but malformed, so a typo stops startup
            rather than silently leaving the roster unsynced.
        """
        block = config.roster_sync
        calendar_id = load_calendar_id(config_dir)
        if not block or not calendar_id:
            return None
        if not isinstance(block, dict):
            raise SyncError("roster_sync must be a mapping")

        known = {vehicle.id for vehicle in config.vehicles}
        vehicles = tuple(str(v) for v in block.get("vehicles") or [])
        if not vehicles or not set(vehicles) <= known:
            raise SyncError(f"roster_sync.vehicles must name configured vehicles ({', '.join(sorted(known))})")

        try:
            sub_calendars = frozenset(int(item) for item in block.get("sub_calendars") or [])
            pattern = block.get("title_pattern")
            title_pattern = re.compile(pattern, re.IGNORECASE) if pattern else None
            settings = cls(
                calendar_id=calendar_id,
                vehicles=vehicles,
                sub_calendars=sub_calendars,
                title_pattern=title_pattern,
                timezone=config.timezone or "UTC",
                interval_seconds=float(block.get("interval_minutes", 15)) * 60,
                days_back=int(block.get("days_back", 56)),
                days_ahead=int(block.get("days_ahead", 120)),
                timeout_seconds=float(block.get("timeout_seconds", 15)),
                user_agent=(config.logger or {}).get("user_agent") or cls.user_agent,
            )
        except (TypeError, ValueError, re.error) as exc:
            raise SyncError(f"roster_sync: {exc}") from exc

        if not sub_calendars and title_pattern is None:
            raise SyncError("roster_sync needs sub_calendars or a title_pattern, or no event would count")
        if settings.interval_seconds < 60:
            raise SyncError("roster_sync.interval_minutes must be at least 1")
        return settings


def load_calendar_id(config_dir: Path | str) -> Optional[str]:
    """
    `calendar_online_id` from secrets.yaml, or None when it is not set.

    Raises
    ------
    SyncError
        If secrets.yaml cannot be read, or the id is not a calendar id.
    """
    path = Path(config_dir) / "secrets.yaml"
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SyncError(f"Could not read {path}: {exc}") from exc
    value = raw.get(SECRET_KEY) if isinstance(raw, dict) else None
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or not CALENDAR_ID.match(value.strip()):
        # Never echo the value: it is the key to the calendar.
        raise SyncError(f"{path}: {SECRET_KEY} is not a calendar.online id")
    return value.strip()


# ---- Reading the calendar ----


@dataclass(frozen=True)
class Drive:
    """
    One timed occurrence that counts as a shift, in local wall clock.
    """

    id: str
    start: datetime
    end: datetime
    title: str
    operator: Optional[str]
    vehicles: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start.strftime(EVENT_TIME_FORMAT),
            "end": self.end.strftime(EVENT_TIME_FORMAT),
            "title": self.title,
            "operator": self.operator,
            "vehicles": list(self.vehicles),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Drive":
        return cls(
            id=str(raw["id"]),
            start=datetime.strptime(raw["start"], EVENT_TIME_FORMAT),
            end=datetime.strptime(raw["end"], EVENT_TIME_FORMAT),
            title=str(raw.get("title") or ""),
            operator=raw.get("operator") or None,
            vehicles=tuple(str(v) for v in raw.get("vehicles") or []),
        )


def events_url(calendar_id: str, tz: str, start: date, end: date) -> str:
    """
    The address the calendar's own page loads its events from.
    """
    query = urlencode({
        "timeZone": tz,
        "startDate": f"{start.isoformat()} 00:00:00",
        "endDate": f"{end.isoformat()} 00:00:00",
        "capabilityId": calendar_id,
    })
    return f"{API_URL}?{query}"


def fetch_events(settings: SyncSettings, start: date, end: date) -> list[dict[str, Any]]:
    """
    Every event on the calendar between two local dates, as the API sends it.

    Raises
    ------
    SyncError
        On any network failure or a body that is not a list of events. The
        message never includes the address, since it carries the id.
    """
    url = events_url(settings.calendar_id, settings.timezone, start, end)
    try:
        body = fetch_json(url, settings.user_agent, settings.timeout_seconds, max_bytes=MAX_BODY_BYTES)
    except FetchError as exc:
        raise SyncError(f"Could not read the calendar: {str(exc).replace(url, SOURCE)}") from None
    if not isinstance(body, list):
        raise SyncError("The calendar answered with something other than a list of events")
    return body


def _name(value: Any) -> Optional[str]:
    """
    An operator name, tidied as the schedule tidies it, or None.
    """
    if not isinstance(value, str):
        return None
    name = " ".join(value.split())
    return name[:80] or None


def to_drives(events: Iterable[dict[str, Any]], settings: SyncSettings, known: Iterable[str]) -> list[Drive]:
    """
    The events that are shifts, as drives.

    An event counts when it is timed, starts and ends on the same day, and is
    on one of `sub_calendars` or has a title matching `title_pattern`. A
    whole day event is leave or a holiday, never a shift. The operator is
    the event's "who"; the bus is the one its title names ("nUWAy 2"), else
    `settings.vehicles`.

    Events that cannot be read are skipped with a warning rather than failing
    the sync, so one odd booking does not freeze everyone else's.
    """
    known = set(known)
    drives = []
    for event in events:
        try:
            if not isinstance(event, dict) or event.get("wholeDay"):
                continue
            title = str(event.get("title") or "")
            on_sub_calendar = bool(settings.sub_calendars & {int(s) for s in event.get("subCalendars") or []})
            on_title = bool(settings.title_pattern and settings.title_pattern.search(title))
            if not (on_sub_calendar or on_title):
                continue

            start = datetime.strptime(str(event["start_date"]), EVENT_TIME_FORMAT)
            end = datetime.strptime(str(event["end_date"]), EVENT_TIME_FORMAT)
            if end <= start:
                log.warning("roster sync: skipped event %s, it ends before it starts", event.get("id"))
                continue
            if end.date() != start.date() and end != datetime.combine(start.date() + timedelta(days=1), datetime.min.time()):
                # The roster cannot hold a period crossing midnight.
                log.warning("roster sync: skipped event %s, it runs past midnight", event.get("id"))
                continue

            named = [m for m in VEHICLE_IN_TITLE.findall(title) if m in known]
            drives.append(Drive(
                id=str(event.get("id")),
                start=start,
                end=end,
                title=title,
                operator=_name(event.get("who")),
                vehicles=tuple(named) if named else settings.vehicles,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("roster sync: skipped an event it could not read (%s)", exc)
    return sorted(drives, key=lambda d: (d.start, d.end, d.id))


def drive_period(drive: Drive) -> tuple[str, ServicePeriod]:
    """
    A drive as a period of the schedule: its weekday, in force on its date.
    """
    day = drive.start.date()
    # A drive to exactly midnight closes at the last minute of its day, as
    # the roster's periods end within the day they start.
    end = drive.end.time() if drive.end.date() == day else datetime.max.time().replace(second=0, microsecond=0)
    return DAYS[day.weekday()], ServicePeriod(
        start=drive.start.time().replace(second=0, microsecond=0),
        end=end.replace(second=0, microsecond=0),
        vehicles=frozenset(drive.vehicles),
        starts_on=day,
        ends_on=day + timedelta(days=1),
        operator=drive.operator,
    )


# ---- The last good copy ----


@dataclass
class SyncState:
    """
    What the last sync left behind.

    `drives` are every drive known, the fetched window replacing what was
    there and anything older kept, so last term's figures keep last term's
    roster after it scrolls out of the window.
    """

    drives: list[Drive] = field(default_factory=list)
    synced_at: Optional[datetime] = None
    window: Optional[tuple[date, date]] = None
    error: Optional[str] = None
    error_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        stamp = lambda value: value.isoformat() if value else None  # noqa: E731
        return {
            "version": FILE_VERSION,
            "source": SOURCE,
            "synced_at": stamp(self.synced_at),
            "window": [self.window[0].isoformat(), self.window[1].isoformat()] if self.window else None,
            "error": self.error,
            "error_at": stamp(self.error_at),
            "drives": [drive.to_dict() for drive in self.drives],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SyncState":
        moment = lambda value: datetime.fromisoformat(value) if value else None  # noqa: E731
        window = raw.get("window")
        return cls(
            drives=[Drive.from_dict(item) for item in raw.get("drives") or []],
            synced_at=moment(raw.get("synced_at")),
            window=(date.fromisoformat(window[0]), date.fromisoformat(window[1])) if window else None,
            error=raw.get("error"),
            error_at=moment(raw.get("error_at")),
        )


class SyncStore:
    """
    The last good copy, in one JSON file under `storage.directory`.

    Read on every call, like the downtime store, so every worker sees the
    same roster. Writes are serialised by a per process lock and atomic.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> SyncState:
        """
        The stored state; empty when nothing has synced yet or the file is
        unreadable, which is logged rather than raised so a bad file cannot
        take the schedule down with it.
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return SyncState.from_dict(raw)
        except FileNotFoundError:
            return SyncState()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("roster sync: ignoring unreadable %s (%s)", self.path, exc)
            return SyncState()

    def record(self, drives: list[Drive], window: tuple[date, date], now: datetime) -> SyncState:
        """
        Store a successful fetch of `window`, replacing what was in it.
        """
        with self._lock:
            state = self.load()
            lo, hi = window
            kept = [d for d in state.drives if not (lo <= d.start.date() < hi)]
            state.drives = sorted(kept + drives, key=lambda d: (d.start, d.end, d.id))
            state.synced_at, state.window = now, window
            state.error = state.error_at = None
            write_json_atomic(self.path, state.to_dict())
            return state

    def record_error(self, message: str, now: datetime) -> SyncState:
        """
        Note a failed sync, keeping the last good drives.
        """
        with self._lock:
            state = self.load()
            state.error, state.error_at = message, now
            write_json_atomic(self.path, state.to_dict())
            return state


# ---- Syncing ----


class RosterSync:
    """
    Keeps the store in step with the calendar.

    Parameters
    ----------
    settings : SyncSettings
    store : SyncStore
    known_vehicles : iterable of str
        The fleet, so a title naming a bus we do not have is not believed.
    """

    def __init__(self, settings: SyncSettings, store: SyncStore, known_vehicles: Iterable[str], fetch=fetch_events):
        self.settings = settings
        self.store = store
        self.known = tuple(known_vehicles)
        self._fetch = fetch
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.timezone)).date()

    def sync_once(self) -> SyncState:
        """
        Fetch the window around today and store it, or note why not.

        Never raises for a calendar problem: the error is stored and shown,
        and the last good roster stays in force.
        """
        with self._lock:
            now = datetime.now(dt_timezone.utc)
            today = self.today()
            window = (today - timedelta(days=self.settings.days_back), today + timedelta(days=self.settings.days_ahead))
            try:
                events = self._fetch(self.settings, *window)
                drives = to_drives(events, self.settings, self.known)
            except SyncError as exc:
                log.warning("roster sync failed: %s", exc)
                return self.store.record_error(str(exc), now)
            state = self.store.record(drives, window, now)
            log.info("roster sync: %d drives from %s", len(drives), SOURCE)
            return state

    def start(self) -> None:
        """
        Sync now, then every `interval_seconds`, on a daemon thread.
        """
        if self._thread is not None:
            return

        def run():
            while not self._stop.is_set():
                try:
                    self.sync_once()
                except Exception:  # a bug here must not kill the thread
                    log.exception("roster sync crashed")
                self._stop.wait(self.settings.interval_seconds)

        self._thread = threading.Thread(target=run, name="roster-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


# ---- Merging into the schedule ----


@dataclass(frozen=True)
class Merged:
    """
    The schedule in force, and how the synced part fared.

    `synced` is day to the synced periods that were accepted, for showing
    apart from the hand kept roster; `conflicts` are drives left out because
    they overlap a hand kept period for the same bus.
    """

    schedule: Schedule
    synced: dict[str, list[ServicePeriod]]
    conflicts: list[Drive]


def coalesce(drives: Iterable[Drive]) -> list[Drive]:
    """
    Join drives of the same bus that overlap into one, naming every operator.

    Two people booked onto one bus at once (a handover, a second driver) is
    one stretch of service, not two: joined, the bus's time is counted once
    and neither name is lost.
    """
    joined: list[Drive] = []
    for drive in sorted(drives, key=lambda d: (d.vehicles, d.start, d.end, d.id)):
        last = joined[-1] if joined else None
        if last and last.vehicles == drive.vehicles and last.start.date() == drive.start.date() and drive.start < last.end:
            names = [n for n in (last.operator or "").split(", ") if n]
            names += [n for n in (drive.operator or "").split(", ") if n and n not in names]
            joined[-1] = replace(
                last,
                id=f"{last.id}+{drive.id}",
                end=max(last.end, drive.end),
                title=last.title if drive.title == last.title else f"{last.title} / {drive.title}",
                operator=", ".join(names) or None,
            )
        else:
            joined.append(drive)
    return sorted(joined, key=lambda d: (d.start, d.end, d.id))


def merge(schedule: Schedule, drives: Iterable[Drive]) -> Merged:
    """
    Add synced drives to the hand kept schedule.

    Overlapping drives of one bus are joined first (`coalesce`). A drive that
    would still overlap a hand kept period for the same bus is left out and
    reported, since the model refuses to count one bus's time twice. The
    hand kept roster always wins: it is what an administrator set on purpose.
    """
    periods = {day: list(rows) for day, rows in schedule.periods.items()}
    synced: dict[str, list[ServicePeriod]] = {}
    conflicts = []
    for drive in coalesce(drives):
        day, period = drive_period(drive)
        try:
            rows = _validated(day, periods.get(day, []) + [period])
        except ScheduleError:
            conflicts.append(drive)
            continue
        periods[day] = rows
        synced.setdefault(day, []).append(period)
    return Merged(Schedule(periods={d: r for d, r in periods.items() if r}), synced, conflicts)


def with_synced_roster(settings, store: Optional[SyncStore]):
    """
    Time usage `Settings` with the synced drives added to its schedule, so
    /api/metrics and /api/operating count the same roster the calendar shows.
    """
    if store is None:
        return settings
    return replace(settings, schedule=effective_schedule(settings.schedule or Schedule(), store).schedule)


def effective_schedule(base: Schedule, store: Optional[SyncStore]) -> Merged:
    """
    The hand kept schedule with the last synced drives added.

    With syncing off (`store` None) it is the hand kept schedule unchanged.
    """
    if store is None:
        return Merged(base, {}, [])
    return merge(base, store.load().drives)
