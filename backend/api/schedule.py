"""
/api/schedule, the shuttle service schedule (S21).

The roster lives in `utilisation.service_hours` of config/app.yaml, so it is
configuration, and editing it here is the same as editing the file: the
figures recalculate on the next /api/metrics with no code change.

AUTHENTICATION (S13), not implemented yet:

    GET is public, and stays public. The dashboard shows scheduled time to
    anyone, so anyone may read the roster behind it.

    PUT is an operator and administrator action. Until S13 lands it is open,
    exactly like the /api/downtime writes. When S13 arrives, the guard goes
    on `replace_schedule` below and nowhere else, since it is the only write
    in this module. See the marker in that function.
"""

from __future__ import annotations
from flask import Blueprint, current_app, jsonify, request

from backend.config import load_config
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
    """
    config = current_app.config["NUWAY_CONFIG"]
    return {
        "days": list(DAYS),
        "timezone": config.timezone,
        "configured": not schedule.is_empty,
        # The fleet a period may name, so the editor can offer it without a
        # second request. A period naming none is for all of them.
        "vehicles": [vehicle.to_dict() for vehicle in config.vehicles],
        "schedule": schedule.to_dict(),
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
def replace_schedule():
    """
    Replace the whole schedule.

    The whole roster is sent at once rather than a row at a time, because it
    is written back into a config file: one read, one validated write, no
    half applied edit.

    Body: `{"monday": [{"start": "08:00", "end": "17:00", "vehicles": ["1"]}]}`,
    or `{"schedule": {...}}`. A day that is absent or empty has no service
    that day, and a period with no `vehicles` is for the whole fleet.

    Returns
    -------
    flask.Response
        200 with the stored schedule in the shape of `_payload`, or 400 for
        a malformed roster, or 500 if the config file cannot be written.
    """
    # AUTH (S13): the guard belongs here. Reject anyone who is not a signed in
    # operator or administrator before the body is read, and leave GET open.
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
