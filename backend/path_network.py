"""
The campus path network: the roads and paths a route can follow.

A route between two stops follows the shortest way along this network unless
the admin draws that stretch by hand (backend/models.py `RoutePoint.straight`).
It is a snapshot of OpenStreetMap, saved in config/campus_paths.json so the
editor works offline, routes the same way every time, and never depends on a
third party's server while someone is editing.

Refresh it when campus paths change:

    python -m backend.path_network refresh

which asks the Overpass API once for every way of the kinds in
`HIGHWAY_KINDS` within `PADDING_M` of the configured stops. Steps are left out
on purpose: the shuttle cannot take them.

Map data © OpenStreetMap contributors, under the Open Database Licence
(https://www.openstreetmap.org/copyright). The attribution travels with the
file and is shown on the editor's map.
"""

from __future__ import annotations
import heapq
import json
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

FILE_NAME = "campus_paths.json"
FILE_VERSION = 1
ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "FMS_Dashboard route editor (UWA CITS3200)"

#: Way kinds the shuttle may use. No steps, motorways or trunk roads.
HIGHWAY_KINDS = (
    "footway", "path", "pedestrian", "cycleway", "service", "living_street", "residential",
    "unclassified", "tertiary", "secondary", "track", "corridor", "bridleway",
)
#: How far past the outermost stops the snapshot reaches.
PADDING_M = 450

EARTH_RADIUS_M = 6_371_008.8

LatLon = tuple[float, float]


class PathNetworkError(Exception):
    """
    The snapshot is missing or unreadable, or could not be refreshed.
    """


def distance_m(a: LatLon, b: LatLon) -> float:
    """
    Metres between two points. Equirectangular, which over a campus is
    within millimetres of the great circle and much cheaper.
    """
    mean_lat = math.radians((a[0] + b[0]) / 2)
    dy = math.radians(b[0] - a[0])
    dx = math.radians(b[1] - a[1]) * math.cos(mean_lat)
    return EARTH_RADIUS_M * math.hypot(dx, dy)


@dataclass(frozen=True)
class Snap:
    """
    Where a point lands on the network: on the edge `u`-`v`, a fraction `t`
    of the way from `u`, at `point`, `offset_m` from where it was asked.
    """

    u: int
    v: int
    t: float
    point: LatLon
    offset_m: float


@dataclass(frozen=True)
class Leg:
    """
    The way from one point to the next, and whether it follows the network.

    `routed` is False when it is a straight line: drawn by hand, or because
    the network did not connect the two ends.
    """

    path: tuple[LatLon, ...]
    routed: bool

    @property
    def length_m(self) -> float:
        return sum(distance_m(a, b) for a, b in zip(self.path, self.path[1:]))


class PathNetwork:
    """
    An undirected graph of campus paths, routed with Dijkstra.

    Parameters
    ----------
    nodes : sequence of (lat, lon)
    ways : sequence of sequences of int
        Each an ordered run of node indices along one way.
    """

    def __init__(self, nodes: Sequence[LatLon], ways: Iterable[Sequence[int]], meta: Optional[dict] = None):
        self.nodes = [tuple(map(float, node)) for node in nodes]
        self.meta = meta or {}
        self.adjacency: list[dict[int, float]] = [dict() for _ in self.nodes]
        self.edges: list[tuple[int, int]] = []
        for way in ways:
            for u, v in zip(way, way[1:]):
                if u == v or v in self.adjacency[u]:
                    continue
                length = distance_m(self.nodes[u], self.nodes[v])
                self.adjacency[u][v] = self.adjacency[v][u] = length
                self.edges.append((u, v))

    # ---- Loading ----

    @classmethod
    def load(cls, path: Path | str) -> "PathNetwork":
        """
        Raises
        ------
        PathNetworkError
            If the file is missing or not a snapshot.
        """
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(raw["nodes"], raw["ways"], {k: raw.get(k) for k in ("source", "fetched_at", "attribution", "bbox")})
        except FileNotFoundError as exc:
            raise PathNetworkError(f"No path network at {path}. Run: python -m backend.path_network refresh") from exc
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise PathNetworkError(f"Could not read the path network {path}: {exc}") from exc

    def to_geojson_lines(self) -> list[list[LatLon]]:
        """
        Every edge as a two point line, for drawing the network under the
        editor so an admin can see where a route can go.
        """
        return [[self.nodes[u], self.nodes[v]] for u, v in self.edges]

    # ---- Snapping ----

    def snap(self, point: LatLon) -> Optional[Snap]:
        """
        The nearest place on any edge to `point`, or None for an empty network.
        """
        best: Optional[Snap] = None
        # Project in a local flat frame around the point: metres east, north.
        cos_lat = math.cos(math.radians(point[0]))
        to_xy = lambda p: (math.radians(p[1] - point[1]) * cos_lat * EARTH_RADIUS_M,  # noqa: E731
                           math.radians(p[0] - point[0]) * EARTH_RADIUS_M)
        for u, v in self.edges:
            ax, ay = to_xy(self.nodes[u])
            bx, by = to_xy(self.nodes[v])
            dx, dy = bx - ax, by - ay
            span = dx * dx + dy * dy
            t = 0.0 if span == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / span))
            px, py = ax + t * dx, ay + t * dy
            offset = math.hypot(px, py)
            if best is None or offset < best.offset_m:
                a, b = self.nodes[u], self.nodes[v]
                best = Snap(u, v, t, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), offset)
        return best

    # ---- Routing ----

    def shortest_path(self, start: LatLon, end: LatLon) -> Optional[list[LatLon]]:
        """
        The shortest way from `start` to `end` along the network.

        Both ends are snapped onto their nearest edge, and the path runs from
        the exact points given, so it always meets the stop markers.

        Returns
        -------
        list of (lat, lon), or None
            None when the network does not connect the two.
        """
        a, b = self.snap(start), self.snap(end)
        if a is None or b is None:
            return None

        # Both on the same edge: straight along it, no search needed.
        if {a.u, a.v} == {b.u, b.v}:
            return _dedupe([start, a.point, b.point, end])

        START, END = -1, -2
        entry = {a.u: a.t * self.adjacency[a.u][a.v], a.v: (1 - a.t) * self.adjacency[a.u][a.v]}
        exit_ = {b.u: b.t * self.adjacency[b.u][b.v], b.v: (1 - b.t) * self.adjacency[b.u][b.v]}

        best = {START: 0.0}
        previous: dict[int, int] = {}
        queue = [(0.0, START)]
        while queue:
            cost, node = heapq.heappop(queue)
            if node == END:
                break
            if cost > best.get(node, math.inf):
                continue
            neighbours = entry.items() if node == START else self.adjacency[node].items()
            for nxt, length in neighbours:
                step = cost + length
                if step < best.get(nxt, math.inf):
                    best[nxt], previous[nxt] = step, node
                    heapq.heappush(queue, (step, nxt))
            if node in exit_:
                step = cost + exit_[node]
                if step < best.get(END, math.inf):
                    best[END], previous[END] = step, node
                    heapq.heappush(queue, (step, END))

        if END not in previous:
            return None
        chain, node = [], previous[END]
        while node != START:
            chain.append(node)
            node = previous[node]
        chain.reverse()
        return _dedupe([start, a.point, *(self.nodes[n] for n in chain), b.point, end])

    def leg(self, start: LatLon, end: LatLon, straight: bool = False) -> Leg:
        """
        One leg of a route: along the network, or straight when asked for or
        when the network does not connect the ends.
        """
        if not straight:
            path = self.shortest_path(start, end)
            if path is not None:
                return Leg(tuple(path), True)
        return Leg((tuple(start), tuple(end)), False)


def _dedupe(points: Iterable[Sequence[float]]) -> list[LatLon]:
    """
    Drop repeated consecutive points, rounded to about a centimetre.
    """
    out: list[LatLon] = []
    for point in points:
        point = (round(float(point[0]), 7), round(float(point[1]), 7))
        if not out or out[-1] != point:
            out.append(point)
    return out


# ---- Refreshing from OpenStreetMap ----


def bbox_around(points: Iterable[LatLon], padding_m: float = PADDING_M) -> tuple[float, float, float, float]:
    """
    (south, west, north, east) around the points, padded by `padding_m`.
    """
    points = list(points)
    if not points:
        raise PathNetworkError("No stops to build a path network around")
    south, north = min(p[0] for p in points), max(p[0] for p in points)
    west, east = min(p[1] for p in points), max(p[1] for p in points)
    dlat = math.degrees(padding_m / EARTH_RADIUS_M)
    dlon = dlat / math.cos(math.radians((south + north) / 2))
    return (south - dlat, west - dlon, north + dlat, east + dlon)


def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    kinds = "|".join(HIGHWAY_KINDS)
    box = ",".join(f"{value:.6f}" for value in bbox)
    return (
        f'[out:json][timeout:60];'
        f'way["highway"~"^({kinds})$"]["area"!="yes"]({box});'
        f'(._;>;);out body;'
    )


def from_overpass(raw: dict, bbox: tuple[float, float, float, float]) -> dict:
    """
    An Overpass answer as the compact snapshot this module loads.
    """
    elements = raw.get("elements") or []
    coords = {e["id"]: (e["lat"], e["lon"]) for e in elements if e.get("type") == "node"}
    index: dict[int, int] = {}
    nodes: list[list[float]] = []
    ways: list[list[int]] = []
    for element in elements:
        if element.get("type") != "way":
            continue
        run = []
        for osm_id in element.get("nodes") or []:
            if osm_id not in coords:
                continue
            if osm_id not in index:
                index[osm_id] = len(nodes)
                nodes.append([round(coords[osm_id][0], 7), round(coords[osm_id][1], 7)])
            run.append(index[osm_id])
        if len(run) >= 2:
            ways.append(run)
    return {
        "version": FILE_VERSION,
        "source": "OpenStreetMap via the Overpass API",
        "attribution": ATTRIBUTION,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bbox": [round(value, 6) for value in bbox],
        "highway_kinds": list(HIGHWAY_KINDS),
        "nodes": nodes,
        "ways": ways,
    }


def refresh(config_dir: Path | str, timeout: float = 90) -> Path:
    """
    Download the network around the configured stops and save it.

    Raises
    ------
    PathNetworkError
        If Overpass cannot be reached or answers with nothing usable. The
        old snapshot is left as it was.
    """
    from backend.config import load_config
    from backend.files import write_json_atomic

    config = load_config(config_dir)
    bbox = bbox_around((s.latitude, s.longitude) for s in config.stops.stops.values())
    body = urlencode({"data": overpass_query(bbox)}).encode()
    request = Request(OVERPASS_URL, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read())
    except (OSError, ValueError) as exc:
        raise PathNetworkError(f"Could not download from Overpass: {exc}") from exc

    snapshot = from_overpass(raw, bbox)
    if not snapshot["ways"]:
        raise PathNetworkError("Overpass returned no paths; the old snapshot is kept")
    path = Path(config_dir) / FILE_NAME
    write_json_atomic(path, snapshot)
    return path


if __name__ == "__main__":
    from backend.config import DEFAULT_CONFIG_DIR

    if sys.argv[1:] != ["refresh"]:
        sys.exit("usage: python -m backend.path_network refresh")
    try:
        saved = refresh(DEFAULT_CONFIG_DIR)
    except PathNetworkError as exc:
        sys.exit(f"{exc}. Overpass is often busy; try again in a few minutes.")
    network = PathNetwork.load(saved)
    print(f"Saved {len(network.nodes)} nodes, {len(network.edges)} edges to {saved}")
