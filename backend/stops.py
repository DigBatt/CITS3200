"""
Stops and routes from config/stops.yaml.
"""

from __future__ import annotations
import json
import logging
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Sequence

from backend import polyline
from backend.models import Route, RoutePoint, Stop

log = logging.getLogger(__name__)

_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

_TOP_KEYS = {"stops", "routes"}
_STOP_KEYS = {"id", "name", "latitude", "longitude"}
_ROUTE_KEYS = {"id", "name", "stops", "points", "colour", "loop"}
_POINT_KEYS = {"stop", "guide", "straight", "path"}


class StopsError(Exception):
    """
    config/stops.yaml is invalid. `problems` holds one line per bad entry.
    """

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


@dataclass(frozen=True)
class StopNetwork:
    """
    The configured stops and routes, both in file order.
    """

    stops: dict[str, Stop]
    routes: dict[str, Route]
    _routes_by_stop: dict[str, tuple[Route, ...]] = field(repr=False, compare=False)

    def stop(self, stop_id: str) -> Optional[Stop]:
        return self.stops.get(stop_id)

    def route(self, route_id: str) -> Optional[Route]:
        return self.routes.get(route_id)

    def routes_for_stop(self, stop_id: str) -> tuple[Route, ...]:
        """
        Every route the stop is on, in file order. Empty for an unknown stop.
        """
        return self._routes_by_stop.get(stop_id, ())

    def stops_on_route(self, route_id: str) -> tuple[Stop, ...]:
        """
        The route's stops in service order. Empty for an unknown route.
        """
        route = self.routes.get(route_id)
        return tuple(self.stops[s] for s in route.stop_ids) if route else ()


def parse_stops(
    raw: Any,
    source: str = "config/stops.yaml",
    bounds: Optional[dict[str, Sequence[float]]] = None,
) -> StopNetwork:
    """
    Validate the parsed YAML and build the network.

    Parameters
    ----------
    raw
        The file as loaded by yaml.safe_load.
    source
        Prefixed to every problem so the message says which file.
    bounds
        Optional `{"latitude": [min, max], "longitude": [min, max]}`, as in the
        `logger.bounds` block of config/app.yaml. A stop outside it is rejected.

    Raises
    ------
    StopsError
        Listing every invalid entry.
    """
    problems: list[str] = []

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise StopsError([f"{source}: must be a mapping with 'stops' and 'routes', got {_describe(raw)}"])

    for key in raw.keys() - _TOP_KEYS:
        problems.append(f"{source}: unknown key '{key}', expected 'stops' and 'routes'")

    stop_entries = _as_list(raw.get("stops"), f"{source}: stops", problems)
    route_entries = _as_list(raw.get("routes"), f"{source}: routes", problems)

    declared: dict[str, int] = {}
    stops: dict[str, Stop] = {}
    for index, entry in enumerate(stop_entries):
        stop = _parse_stop(entry, index, source, bounds, declared, problems)
        if stop is not None:
            stops[stop.id] = stop

    route_ids: dict[str, int] = {}
    routes: dict[str, Route] = {}
    for index, entry in enumerate(route_entries):
        route = _parse_route(entry, index, source, declared, route_ids, problems, bounds)
        if route is not None:
            routes[route.id] = route

    if problems:
        raise StopsError(problems)

    by_stop: dict[str, list[Route]] = {stop_id: [] for stop_id in stops}
    for route in routes.values():
        for stop_id in route.stop_ids:
            by_stop[stop_id].append(route)

    for stop_id, on in by_stop.items():
        if not on:
            log.warning("%s: stop '%s' is not on any route", source, stop_id)

    return StopNetwork(
        stops=stops,
        routes=routes,
        _routes_by_stop={stop_id: tuple(on) for stop_id, on in by_stop.items()},
    )


def _parse_stop(entry, index, source, bounds, declared, problems) -> Optional[Stop]:
    where = f"{source}: stops[{index}]"
    if not isinstance(entry, dict):
        problems.append(f"{where}: must be a mapping, got {_describe(entry)}")
        return None

    before = len(problems)
    stop_id = _parse_id(entry, where, problems)
    if stop_id is not None:
        where = f"{where} (id '{stop_id}')"
        if stop_id in declared:
            problems.append(f"{where}: duplicate stop id, first used at stops[{declared[stop_id]}]")
        else:
            declared[stop_id] = index

    _check_keys(entry, _STOP_KEYS, where, problems)
    name = _parse_name(entry, where, problems)
    latitude = _parse_coordinate(entry, "latitude", 90, bounds, where, problems)
    longitude = _parse_coordinate(entry, "longitude", 180, bounds, where, problems)

    if len(problems) > before:
        return None
    return Stop(id=stop_id, name=name, latitude=latitude, longitude=longitude)


def _parse_route(entry, index, source, declared, route_ids, problems, bounds=None) -> Optional[Route]:
    where = f"{source}: routes[{index}]"
    if not isinstance(entry, dict):
        problems.append(f"{where}: must be a mapping, got {_describe(entry)}")
        return None

    before = len(problems)
    route_id = _parse_id(entry, where, problems)
    if route_id is not None:
        where = f"{where} (id '{route_id}')"
        if route_id in route_ids:
            problems.append(f"{where}: duplicate route id, first used at routes[{route_ids[route_id]}]")
        else:
            route_ids[route_id] = index

    _check_keys(entry, _ROUTE_KEYS, where, problems)
    name = _parse_name(entry, where, problems)

    # `points` is the route in full, stops and guide points. A route with
    # only `stops` is the older form: those stops, each leg along the paths.
    if entry.get("points") is not None:
        points = _parse_points(entry.get("points"), where, declared, bounds, problems)
    else:
        points = _parse_stop_list(entry.get("stops"), where, declared, problems)

    stop_ids: list[str] = []
    for point in points:
        if point.is_stop:
            if point.stop_id in stop_ids:
                problems.append(f"{where}: stop '{point.stop_id}' is listed more than once")
            else:
                stop_ids.append(point.stop_id)
    if points and not stop_ids:
        problems.append(f"{where}: a route needs at least one stop, not only guide points")

    loop = entry.get("loop", False)
    if not isinstance(loop, bool):
        problems.append(f"{where}: loop must be true or false, got {_describe(loop)}")
    elif points and not loop and not (points[0].is_stop and points[-1].is_stop):
        problems.append(f"{where}: a route that is not a loop must start and end at a stop")

    # Both given, as the editor writes them: `stops` is a summary of
    # `points`, so a hand edit to one alone is caught rather than ignored.
    if entry.get("points") is not None and entry.get("stops") is not None:
        listed = [_coerce_id(stop) for stop in _as_list(entry.get("stops"), f"{where}: stops", problems)]
        if listed != stop_ids:
            problems.append(f"{where}: stops {listed} do not match the stops in points {stop_ids}")

    colour = entry.get("colour")
    if colour is not None and not (isinstance(colour, str) and _COLOUR.match(colour)):
        problems.append(f"{where}: colour must be #rrggbb, got {_describe(colour)}")

    if len(problems) > before:
        return None
    return Route(id=route_id, name=name, stop_ids=tuple(stop_ids), colour=colour, loop=loop, points=tuple(points))


def _parse_stop_list(raw_stops, where, declared, problems) -> list[RoutePoint]:
    if not isinstance(raw_stops, list) or not raw_stops:
        problems.append(f"{where}: stops must be a non-empty list of stop ids, got {_describe(raw_stops)}")
        return []
    points = []
    for raw_stop in raw_stops:
        stop_id = _coerce_id(raw_stop)
        if stop_id is None:
            problems.append(f"{where}: stop {_describe(raw_stop)} is not a stop id")
        elif stop_id not in declared:
            problems.append(f"{where}: stop '{stop_id}' is not a configured stop")
        else:
            points.append(RoutePoint(stop_id=stop_id))
    return points


def _parse_points(raw_points, where, declared, bounds, problems) -> list[RoutePoint]:
    """
    A route's `points`: each `{stop: id}` or `{guide: [lat, lon]}`, with an
    optional `straight` and the `path` of the leg arriving there.
    """
    if not isinstance(raw_points, list) or not raw_points:
        problems.append(f"{where}: points must be a non-empty list, got {_describe(raw_points)}")
        return []
    points = []
    for number, raw in enumerate(raw_points):
        at = f"{where}: points[{number}]"
        if not isinstance(raw, dict) or ("stop" in raw) == ("guide" in raw):
            problems.append(f"{at}: must be a mapping with either 'stop' or 'guide', got {_describe(raw)}")
            continue
        _check_keys(raw, _POINT_KEYS, at, problems)

        straight = raw.get("straight", False)
        if not isinstance(straight, bool):
            problems.append(f"{at}: straight must be true or false, got {_describe(straight)}")
            continue
        path: tuple = ()
        if raw.get("path") is not None:
            try:
                path = tuple(polyline.decode(str(raw["path"])))
            except ValueError as exc:
                problems.append(f"{at}: path is not an encoded polyline ({exc})")
                continue

        if "stop" in raw:
            stop_id = _coerce_id(raw["stop"])
            if stop_id is None or stop_id not in declared:
                problems.append(f"{at}: stop {_describe(raw['stop'])} is not a configured stop")
                continue
            points.append(RoutePoint(stop_id=stop_id, straight=straight, path=path))
        else:
            guide = raw["guide"]
            if not isinstance(guide, list) or len(guide) != 2:
                problems.append(f"{at}: guide must be [latitude, longitude], got {_describe(guide)}")
                continue
            latitude = _parse_coordinate({"latitude": guide[0]}, "latitude", 90, bounds, at, problems)
            longitude = _parse_coordinate({"longitude": guide[1]}, "longitude", 180, bounds, at, problems)
            if latitude is None or longitude is None:
                continue
            points.append(RoutePoint(latitude=latitude, longitude=longitude, straight=straight, path=path))
    return points


def _parse_id(entry, where, problems) -> Optional[str]:
    if "id" not in entry or entry["id"] is None:
        problems.append(f"{where}: id is missing")
        return None
    value = _coerce_id(entry["id"])
    if value is None or not _ID.match(value):
        problems.append(
            f"{where}: id must be lowercase letters and digits joined by hyphens, got {_describe(entry['id'])}"
        )
        return None
    return value


def _coerce_id(value) -> Optional[str]:
    # Ids are text, but YAML reads an unquoted 1 as an int. bool is an int too.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value).strip()


def _parse_name(entry, where, problems) -> Optional[str]:
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(f"{where}: name must be non-empty text, got {_describe(name)}")
        return None
    return name.strip()


def _parse_coordinate(entry, key, limit, bounds, where, problems) -> Optional[float]:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        problems.append(f"{where}: {key} must be a number between -{limit} and {limit}, got {_describe(value)}")
        return None
    if not -limit <= value <= limit:
        problems.append(f"{where}: {key} must be a number between -{limit} and {limit}, got {value}")
        return None
    box = (bounds or {}).get(key)
    if box and not box[0] <= value <= box[1]:
        problems.append(
            f"{where}: {key} {value} is outside the configured bounds {box[0]} to {box[1]}"
            " (are latitude and longitude swapped?)"
        )
        return None
    return float(value)


def _check_keys(entry, allowed, where, problems) -> None:
    for key in sorted(map(str, entry.keys() - allowed)):
        problems.append(f"{where}: unknown key '{key}', expected one of {', '.join(sorted(allowed))}")


def _as_list(value, where, problems) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"{where} must be a list, got {_describe(value)}")
        return []
    return value


def _describe(value) -> str:
    if value is None:
        return "nothing"
    if isinstance(value, (dict, list)):
        return f"{'an empty' if not value else 'a'} {type(value).__name__}"
    return repr(value)


# ---- Paths and writing back (the admin route editor) ----


def _position(network_stops: dict[str, Stop], point: RoutePoint) -> tuple[float, float]:
    if point.is_stop:
        stop = network_stops[point.stop_id]
        return (stop.latitude, stop.longitude)
    return (point.latitude, point.longitude)


def _rounded(path) -> tuple[tuple[float, float], ...]:
    # The precision the path is written at, so a saved file reads back equal.
    out: list[tuple[float, float]] = []
    for lat, lon in path:
        point = (round(lat, polyline.PRECISION), round(lon, polyline.PRECISION))
        if not out or out[-1] != point:
            out.append(point)
    return tuple(out)


def resolve_paths(network: StopNetwork, paths=None, force: bool = False) -> StopNetwork:
    """
    Fill in the path of every leg that has none, or whose ends no longer
    meet its points (a stop moved by hand in the file).

    Parameters
    ----------
    network : StopNetwork
    paths : backend.path_network.PathNetwork, optional
        The campus path network legs follow. Without it every leg is a
        straight line, which is still a usable route on the map.
    force : bool
        Work out every leg again, e.g. after the path network is refreshed.

    Returns
    -------
    StopNetwork
        The same stops, with every route's points carrying a path.
    """
    routes = {}
    for route in network.routes.values():
        points = list(route.points)
        resolved = []
        for index, point in enumerate(points):
            if index == 0 and not route.loop:
                resolved.append(replace(point, path=()))
                continue
            previous = points[index - 1]
            start, end = _position(network.stops, previous), _position(network.stops, point)
            path = point.path
            stale = not path or not _near(path[0], start) or not _near(path[-1], end)
            if force or stale:
                if paths is not None:
                    path = paths.leg(start, end, point.straight).path
                else:
                    path = (start, end)
            resolved.append(replace(point, path=_rounded(path)))
        routes[route.id] = replace(route, points=tuple(resolved))
    return replace(network, routes=routes)


def _near(a, b, metres: float = 0.5) -> bool:
    from backend.path_network import distance_m

    return distance_m(tuple(a), tuple(b)) <= metres


def dump_stops(network: StopNetwork, header: str = "") -> str:
    """
    The network as config/stops.yaml text.

    Laid out by hand rather than by a YAML dumper so the file stays the one
    people read and diff: a stop to a block, a route's `stops` on one line
    as a summary, then its `points`, each leg's path an encoded polyline.
    """
    def text(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [header.rstrip("\n"), ""] if header.strip() else []
    lines.append("stops:")
    for stop in network.stops.values():
        lines += [
            f"  - id: {stop.id}",
            f"    name: {text(stop.name)}",
            f"    latitude: {stop.latitude!r}",
            f"    longitude: {stop.longitude!r}",
            "",
        ]
    lines.append("routes:")
    for route in network.routes.values():
        lines += [f"  - id: {route.id}", f"    name: {text(route.name)}"]
        if route.colour:
            lines.append(f"    colour: {text(route.colour)}")
        lines.append(f"    loop: {'true' if route.loop else 'false'}")
        lines.append(f"    stops: [{', '.join(route.stop_ids)}]")
        lines.append("    points:")
        for point in route.points:
            if point.is_stop:
                lines.append(f"      - stop: {point.stop_id}")
            else:
                lines.append(f"      - guide: [{point.latitude!r}, {point.longitude!r}]")
            if point.straight:
                lines.append("        straight: true")
            if point.path:
                # Single quoted: a polyline can hold a backslash, never a quote.
                lines.append(f"        path: '{polyline.encode(point.path)}'")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def file_header(text: str) -> str:
    """
    The comment block at the top of a stops.yaml, kept when it is rewritten.
    """
    header = []
    for line in text.splitlines():
        if line.startswith("#") or (header and not line.strip()):
            header.append(line)
        else:
            break
    return "\n".join(header).rstrip("\n")


def save_stops(path, network: StopNetwork, bounds=None) -> None:
    """
    Write the network to a stops.yaml, in place and atomically.

    The new text is parsed back and compared with what was asked for before
    it replaces anything, so a bug here cannot leave a file that stops the
    server starting.

    Raises
    ------
    StopsError
        If the written text would not read back as `network`.
    OSError
        If the file cannot be written; the old one is left as it was.
    """
    from pathlib import Path

    import yaml

    from backend.files import write_text_atomic

    path = Path(path)
    header = file_header(path.read_text(encoding="utf-8")) if path.exists() else ""
    text = dump_stops(network, header)
    written = parse_stops(yaml.safe_load(text), str(path), bounds)
    if written != network:
        raise StopsError([f"{path}: refusing to write, the result would not read back as the network given"])
    write_text_atomic(path, text)
