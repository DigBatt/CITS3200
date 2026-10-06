"""
/api/network, the admin page's route editor.

Stops are the nodes of the network, shared by every route that serves them.
A route is a path through them, in order, shaped by guide points; each leg
follows the campus path network (backend/path_network.py) unless the admin
draws it by hand. Saving rewrites config/stops.json, which stays the source
of truth, and applies at once with no restart.

AUTHENTICATION (S13): every endpoint here is admin only. Riders and the
dashboard read stops and routes through the public /api/stops and /api/routes.
"""

from __future__ import annotations
import re
from dataclasses import replace
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from backend.auth import admin_required
from backend.config import load_config
from backend.models import PickupRequest
from backend.stops import STOPS_FILE, StopsError, parse_stops, resolve_paths, save_stops

bp = Blueprint("network", __name__)

_SLUG = re.compile(r"[^a-z0-9]+")
#: Most points a route may have, so a stuck mouse cannot write a huge file.
MAX_POINTS = 500


def _error(code: str, message: str, status: int, **extra):
    return jsonify({"error": {"code": code, "message": message, **extra}}), status


def _paths():
    return current_app.config.get("PATH_NETWORK")


def _payload():
    """
    Every stop and route in full, plus where the path network came from.
    """
    network = current_app.config["NUWAY_CONFIG"].stops
    paths = _paths()
    return {
        "stops": [
            {**stop.to_dict(), "snap": stop.snap, "routes": [r.id for r in network.routes_for_stop(stop.id)]}
            for stop in network.stops.values()
        ],
        "routes": [route.to_dict() for route in network.routes.values()],
        "paths": {
            "available": paths is not None,
            "attribution": (paths.meta.get("attribution") if paths else None),
            "fetched_at": (paths.meta.get("fetched_at") if paths else None),
        },
    }


@bp.get("/api/network")
@admin_required
def get_network():
    """
    The stops and routes for the editor, each route with its points and path.
    """
    return jsonify(_payload())


@bp.get("/api/network/paths")
@admin_required
def get_paths():
    """
    The campus path network, drawn faintly under the editor so an admin can
    see where a route can go, and snapped to when placing points.

    Returns
    -------
    flask.Response
        `nodes` as [lat, lon] and `ways` as runs of node indices, the
        compact form of config/campus_paths.json; 404 `paths_unavailable`
        when there is no snapshot, in which case every leg is drawn straight.
    """
    paths = _paths()
    if paths is None:
        return _error("paths_unavailable", "No campus path network. Run: python -m backend.path_network refresh", 404)
    return jsonify({
        "nodes": [list(node) for node in paths.nodes],
        "edges": [list(edge) for edge in paths.edges],
        "attribution": paths.meta.get("attribution"),
    })


def _coordinate(value: Any, limit: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not -limit <= value <= limit:
        raise ValueError
    return float(value)


@bp.post("/api/network/legs")
@admin_required
def legs():
    """
    The path of each leg of a route being edited, worked out as the admin
    places and drags points.

    Body: `{"loop": bool, "points": [{"latitude", "longitude", "straight"}]}`.

    Returns
    -------
    flask.Response
        `legs`, one per point: the leg arriving at it as `path` and whether
        it follows the path network (`routed`). The first is null on a route
        that is not a loop. 400 `invalid_points` for a malformed body.
    """
    body = request.get_json(silent=True) or {}
    raw = body.get("points")
    if not isinstance(raw, list) or len(raw) > MAX_POINTS:
        return _error("invalid_points", f"points must be a list of at most {MAX_POINTS}", 400)
    try:
        points = [(_coordinate(p["latitude"], 90), _coordinate(p["longitude"], 180), bool(p.get("straight"))) for p in raw]
    except (KeyError, TypeError, ValueError):
        return _error("invalid_points", "Each point needs a latitude and a longitude", 400)

    loop = bool(body.get("loop"))
    paths = _paths()
    out = []
    for index, (lat, lon, straight) in enumerate(points):
        if index == 0 and not loop:
            out.append(None)
            continue
        before = points[index - 1]
        start, end = (before[0], before[1]), (lat, lon)
        if paths is None:
            out.append({"path": [list(start), list(end)], "routed": False})
        else:
            leg = paths.leg(start, end, straight)
            out.append({"path": [list(p) for p in leg.path], "routed": leg.routed})
    return jsonify({"legs": out})


def _slug(name: str, taken: set[str], fallback: str) -> str:
    """
    A new permanent id from a name: lowercase words joined by hyphens,
    numbered if already taken. Existing ids are never changed (docs/stops-and-routes.md, 4).
    """
    base = _SLUG.sub("-", name.lower()).strip("-") or fallback
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    taken.add(candidate)
    return candidate


def _to_config(body: dict) -> dict:
    """
    The editor's body as the stops.json structure, giving new stops and
    routes their ids.

    A new stop has no `id` but a `key` the routes use to point at it until
    it has one.

    Raises
    ------
    ValueError
        With a message for the admin, for a body of the wrong shape.
    """
    if not isinstance(body, dict) or not isinstance(body.get("stops"), list) or not isinstance(body.get("routes"), list):
        raise ValueError("Expected {stops: [...], routes: [...]}")
    existing = current_app.config["NUWAY_CONFIG"].stops

    stop_ids = set(existing.stops)
    keys: dict[str, str] = {}
    stops = []
    for stop in body["stops"]:
        if not isinstance(stop, dict):
            raise ValueError("Each stop must be an object")
        stop_id = stop.get("id")
        if stop_id is None:
            stop_id = _slug(str(stop.get("name") or ""), stop_ids, "stop")
        if stop.get("key") is not None:
            keys[str(stop["key"])] = stop_id
        stops.append({k: stop.get(k) for k in ("name", "latitude", "longitude")} | {"id": stop_id}
                     | ({} if stop.get("snap", True) else {"snap": False}))

    route_ids = set(existing.routes)
    routes = []
    for route in body["routes"]:
        if not isinstance(route, dict) or not isinstance(route.get("points"), list):
            raise ValueError("Each route must be an object with a list of points")
        if len(route["points"]) > MAX_POINTS:
            raise ValueError(f"A route may have at most {MAX_POINTS} points")
        points = []
        for point in route["points"]:
            if not isinstance(point, dict):
                raise ValueError("Each point must be an object")
            if point.get("stop") is not None:
                entry: dict[str, Any] = {"stop": keys.get(str(point["stop"]), point["stop"])}
            else:
                entry = {"guide": [point.get("latitude"), point.get("longitude")]}
                if point.get("snap") is False:
                    entry["snap"] = False
            if point.get("straight"):
                entry["straight"] = True
            points.append(entry)
        route_id = route.get("id") or _slug(str(route.get("name") or ""), route_ids, "route")
        entry = {"id": route_id, "name": route.get("name"), "loop": bool(route.get("loop")), "points": points}
        if route.get("colour"):
            entry["colour"] = route["colour"]
        routes.append(entry)
    return {"stops": stops, "routes": routes}


@bp.put("/api/network")
@admin_required
def save_network():
    """
    Replace every stop and route, and write config/stops.json. Admin only.

    Body: `{"stops": [{id?, key?, name, latitude, longitude}], "routes":
    [{id?, name, colour?, loop, points: [{stop} | {latitude, longitude},
    straight?]}]}`. Paths are worked out here, not taken from the body, so
    what is saved is what the path network gives.

    Returns
    -------
    flask.Response
        200 with the saved network in the shape of GET; 400
        `invalid_network` listing every problem; 409 `stop_in_use` if a
        removed stop has riders waiting at it; 500 if the file cannot be
        written.
    """
    try:
        raw = _to_config(request.get_json(silent=True))
    except ValueError as exc:
        return _error("invalid_network", str(exc), 400, problems=[str(exc)])

    config = current_app.config["NUWAY_CONFIG"]
    bounds = (config.logger or {}).get("bounds")
    try:
        network = parse_stops(raw, "routes", bounds)
    except StopsError as exc:
        problems = [p.removeprefix("routes: ") for p in exc.problems]
        return _error("invalid_network", "; ".join(problems), 400, problems=problems)

    # A rider waiting at a stop that disappears would never be collected.
    removed = set(config.stops.stops) - set(network.stops)
    waiting = sorted({r.stop_id for r in current_app.config["PICKUP_REQUEST_STORE"].list(PickupRequest.OPEN)} & removed)
    if waiting:
        names = ", ".join(config.stops.stops[s].name for s in waiting)
        return _error("stop_in_use", f"Riders are waiting at {names}. Remove the stop once they are collected.", 409,
                      stops=waiting)

    network = resolve_paths(network, _paths(), force=True)
    try:
        save_stops(current_app.config["NUWAY_CONFIG_DIR"], network, bounds)
    except (StopsError, OSError) as exc:
        return _error("data_unavailable", f"Could not write {STOPS_FILE}: {exc}", 500)

    # Re-read, so what is served is what the file now says.
    current_app.config["NUWAY_CONFIG"] = load_resolved(current_app.config["NUWAY_CONFIG_DIR"], _paths())
    return jsonify(_payload())


def load_resolved(config_dir, paths):
    """
    The config with every route's legs given a path, as the app serves it.
    """
    config = load_config(config_dir)
    return replace(config, stops=resolve_paths(config.stops, paths))

