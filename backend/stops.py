"""
Stops and routes from config/stops.yaml.
"""

from __future__ import annotations
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from backend.models import Route, Stop

log = logging.getLogger(__name__)

_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

_TOP_KEYS = {"stops", "routes"}
_STOP_KEYS = {"id", "name", "latitude", "longitude"}
_ROUTE_KEYS = {"id", "name", "stops", "colour", "loop"}


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
        route = _parse_route(entry, index, source, declared, route_ids, problems)
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


def _parse_route(entry, index, source, declared, route_ids, problems) -> Optional[Route]:
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

    stop_ids: list[str] = []
    raw_stops = entry.get("stops")
    if not isinstance(raw_stops, list) or not raw_stops:
        problems.append(f"{where}: stops must be a non-empty list of stop ids, got {_describe(raw_stops)}")
    else:
        for raw_stop in raw_stops:
            stop_id = _coerce_id(raw_stop)
            if stop_id is None:
                problems.append(f"{where}: stop {_describe(raw_stop)} is not a stop id")
            elif stop_id not in declared:
                problems.append(f"{where}: stop '{stop_id}' is not a configured stop")
            elif stop_id in stop_ids:
                problems.append(f"{where}: stop '{stop_id}' is listed more than once")
            else:
                stop_ids.append(stop_id)

    colour = entry.get("colour")
    if colour is not None and not (isinstance(colour, str) and _COLOUR.match(colour)):
        problems.append(f"{where}: colour must be #rrggbb, got {_describe(colour)}")

    loop = entry.get("loop", False)
    if not isinstance(loop, bool):
        problems.append(f"{where}: loop must be true or false, got {_describe(loop)}")

    if len(problems) > before:
        return None
    return Route(id=route_id, name=name, stop_ids=tuple(stop_ids), colour=colour, loop=loop)


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
