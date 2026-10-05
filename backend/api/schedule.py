"""
/api/schedule, the shuttle service schedule (S21).

The roster lives in `utilisation.service_hours` of config/app.yaml, so it is
configuration, and editing it here is the same as editing the file: the
figures recalculate on the next /api/metrics with no code change.

AUTHENTICATION (S13):

    GET is public, and stays public. The dashboard shows scheduled time to
    anyone, so anyone may read the roster behind it.

    PUT is admin only, through the same `admin_required` guard as the
    /api/downtime writes, as is POST /api/schedule/sync, which only reads
    the calendar again; it never writes to it.

SYNCED DRIVES (backend/roster_sync.py):

    When the roster syncs from calendar.online, its drives come back under
    `synced`, apart from the hand kept `schedule`, so the editor only ever
    sends back what it owns. The dashboard draws both.
"""

from __future__ import annotations
from flask import Blueprint, current_app, jsonify, request

from backend.auth import admin_required
from backend.config import load_config
from backend.roster_sync import SOURCE as SYNC_SOURCE, effective_schedule
from backend.schedule import DAYS, Schedule, ScheduleError, load_schedule, save_schedule

bp = Blueprint("schedule", __name__)


def _error(code: str, message: str, status: int):
    """
    An error in the shape of docs/api.md.
    """
    return jsonify({"error": {"code": code, "message": message}}), status


def _config_path():
    """
    The app.yaml the schedule is read from and written to.
    """
    return current_app.config["NUWAY_CONFIG_PATH"]


def _payload(schedule: Schedule):
    """
    The schedule, plus what the dashboard needs to caption it.

    Returns
    -------
    dict
        `days` in Monday-first order so a client need not know the ordering,
        `schedule` as day to periods with every day present, `timezone` the
        roster is written in, and `configured`, false when nothing at all is
        rostered. An empty schedule is a valid state, not an error.
        `synced` is day to the drives synced from the calendar, every day
        present, and `sync` how that sync stands, null when it is off.
    """
    config = current_app.config["NUWAY_CONFIG"]
    store = current_app.config.get("ROSTER_SYNC_STORE")
    merged = effective_schedule(schedule, store)
    return {
        "days": list(DAYS),
        "timezone": config.timezone,
        "configured": not merged.schedule.is_empty,
        # The fleet a period may name, so the editor can offer it without a
        # second request. A period naming none is for all of them.
        "vehicles": [vehicle.to_dict() for vehicle in config.vehicles],
        "schedule": schedule.to_dict(),
        "synced": {day: [period.to_dict() for period in merged.synced.get(day, [])] for day in DAYS},
        "sync": _sync_status(store, merged) if store else None,
    }


def _sync_status(store, merged):
    """
    How the calendar sync stands, for the admin page's Schedule tab.
    """
    state = store.load()
    stamp = lambda value: value.isoformat() if value else None  # noqa: E731
    return {
        "source": SYNC_SOURCE,
        "synced_at": stamp(state.synced_at),
        "error": state.error,
        "error_at": stamp(state.error_at),
        "drives": sum(len(rows) for rows in merged.synced.values()),
        # Drives left out because they overlap a hand kept period for the
        # same bus; the hand kept one wins.
        "conflicts": [
            {"start": d.start.isoformat(timespec="minutes"), "end": d.end.isoformat(timespec="minutes"),
             "operator": d.operator, "vehicles": list(d.vehicles)}
            for d in merged.conflicts
        ],
    }


@bp.get("/api/schedule")
def get_schedule():
    """
    The service schedule. Public, see the note at the top of this module.

    Returns
    -------
    flask.Response
        JSON in the shape of `_payload`. A fleet with nothing rostered
        answers 200 with empty lists and `configured` false, never 404.
    """
    try:
        schedule = load_schedule(_config_path())
    except ScheduleError as exc:
        return _error("data_unavailable", str(exc), 500)
    return jsonify(_payload(schedule))


@bp.put("/api/schedule")
@admin_required
def replace_schedule():
    """
    Replace the whole schedule. Admin only (S13).

    The whole roster is sent at once rather than a row at a time, because it
    is written back into a config file: one read, one validated write, no
    half applied edit.

    Body: `{"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1"]}]}`,
    or `{"schedule": {...}}`. A day that is absent or empty has no service
    that day, and a period with no `vehicles` is for the whole fleet.

    Returns
    -------
    flask.Response
        200 with the stored schedule in the shape of `_payload`, 401 when not
        signed in, 400 for a malformed roster, or 500 if the config file
        cannot be written.
    """
    body = request.get_json(silent=True)
    if isinstance(body, dict) and "schedule" in body:
        body = body["schedule"]

    try:
        schedule = Schedule.from_dict(body)
    except ScheduleError as exc:
        return _error("invalid_schedule", str(exc), 400)

    # A roster naming a vehicle the fleet does not have is a typo, not a plan.
    known = {vehicle.id for vehicle in current_app.config["NUWAY_CONFIG"].vehicles}
    unknown = sorted(set(schedule.vehicle_ids()) - known)
    if unknown:
        return _error(
            "unknown_vehicle",
            f"No vehicle with id {', '.join(repr(v) for v in unknown)}. Known ids: {', '.join(sorted(known))}.",
            400,
        )

    try:
        save_schedule(_config_path(), schedule)
    except ScheduleError as exc:
        return _error("data_unavailable", str(exc), 500)

    # Re-read so the response is what the file now says, not what we sent.
    # /api/metrics reads the cached config, so refresh it or the figures
    # would not move until the next restart.
    current_app.config["NUWAY_CONFIG"] = load_config(current_app.config["NUWAY_CONFIG_DIR"])
    return jsonify(_payload(load_schedule(_config_path())))


@bp.post("/api/schedule/sync")
@admin_required
def sync_schedule():
    """
    Read the calendar again now, rather than waiting for the next sync.
    Admin only (S13). Read only towards the calendar.

    Returns
    -------
    flask.Response
        200 with the schedule in the shape of `_payload`, its `sync.error`
        set if the calendar could not be read; 404 `sync_off` when no
        calendar is configured.
    """
    sync = current_app.config.get("ROSTER_SYNC")
    if sync is None:
        return _error("sync_off", "No calendar to sync from. Set roster_sync in app.yaml and calendar_online_id in secrets.yaml.", 404)
    sync.sync_once()
    try:
        schedule = load_schedule(_config_path())
    except ScheduleError as exc:
        return _error("data_unavailable", str(exc), 500)
    return jsonify(_payload(schedule))
