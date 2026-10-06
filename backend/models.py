from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

UTC = timezone.utc
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def parse_timestamp(value: str | datetime) -> datetime:
    """
    Parse an ISO 8601 into a UTC datetime.
    """
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"

    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        while tail and tail[0].isdigit():
            digits, tail = digits + tail[0], tail[1:]
        text = f"{head}.{digits[:6]:0<6}{tail}"

    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def format_timestamp(value: datetime) -> str:
    """
    Render a datetime in the canonical form.
    """
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT) + "Z"


@dataclass(frozen=True)
class Vehicle:
    """
    A shuttle as declared in config/vehicles.yaml.
    """

    id: str
    name: Optional[str] = None
    colour: Optional[str] = None
    positions_file: Optional[str] = None
    source_url: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "colour": self.colour}


@dataclass(frozen=True)
class Stop:
    """
    A pickup point as declared in config/stops.json.

    `snap` is for the route editor only: False when the stop was placed off
    the campus paths on purpose, so dragging it does not pull it back on.
    """

    id: str
    name: str
    latitude: float
    longitude: float
    snap: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "latitude": self.latitude, "longitude": self.longitude}


@dataclass(frozen=True)
class RoutePoint:
    """
    One point a route passes through, in order.

    Either a stop, which is a node of the network shared by every route that
    serves it and where riders are picked up, or a guide point, which only
    shapes this route's path and is never a stop.

    Parameters
    ----------
    stop_id : str, optional
        Set for a stop; its position is the stop's.
    latitude, longitude : float, optional
        Set for a guide point.
    snap : bool
        For a guide point, False when it was placed off the campus paths on
        purpose, so the editor does not pull it back on when dragged. A
        stop's is on the stop. Editor only; it changes no path.
    straight : bool
        The leg arriving at this point is drawn as a straight line rather
        than following the campus path network, for a way that is not on the
        map. On the first point of a loop it is the closing leg's.
    path : tuple of (lat, lon)
        The leg arriving at this point, from the point before it (on the
        first point of a loop, from the last). Empty for the first point of
        a route that is not a loop, and when not yet worked out.
    """

    stop_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    straight: bool = False
    path: tuple[tuple[float, float], ...] = ()
    snap: bool = True

    @property
    def is_stop(self) -> bool:
        return self.stop_id is not None

    def to_dict(self) -> dict[str, Any]:
        point: dict[str, Any] = (
            {"stop_id": self.stop_id} if self.is_stop else {"latitude": self.latitude, "longitude": self.longitude}
        )
        point["straight"] = self.straight
        if not self.is_stop:
            point["snap"] = self.snap
        point["path"] = [list(p) for p in self.path]
        return point


@dataclass(frozen=True)
class RouteLeg:
    """
    The way from one stop to the next along a route: the edge between two
    nodes, with the guide points that shape it and the path it follows.
    """

    from_stop: str
    to_stop: str
    guides: tuple[tuple[float, float], ...]
    path: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Route:
    """
    A path through stops, as declared in config/stops.json.

    `points` are what the route passes through in order, stops and guide
    points both. `stop_ids` are its stops alone, in service order, which is
    all the pickup and rider code needs.
    """

    id: str
    name: str
    stop_ids: tuple[str, ...]
    colour: Optional[str] = None
    loop: bool = False
    points: tuple[RoutePoint, ...] = ()

    @property
    def path(self) -> tuple[tuple[float, float], ...]:
        """
        The whole route as one line, in order, closing the loop if it is one.
        """
        ordered = list(self.points[1:]) + ([self.points[0]] if self.loop and self.points else [])
        line: list[tuple[float, float]] = []
        for point in ordered:
            for coordinate in point.path:
                if not line or line[-1] != coordinate:
                    line.append(coordinate)
        return tuple(line)

    def legs(self) -> list[RouteLeg]:
        """
        The route as stop to stop legs, each with the guide points between.
        """
        ordered = list(self.points) + ([self.points[0]] if self.loop and self.points else [])
        legs: list[RouteLeg] = []
        start, guides, path = None, [], []
        for index, point in enumerate(ordered):
            if index and point.path:
                path.extend(c for c in point.path if not path or path[-1] != c)
            if point.is_stop:
                if start is not None:
                    legs.append(RouteLeg(start, point.stop_id, tuple(guides), tuple(path)))
                start, guides, path = point.stop_id, [], []
            else:
                guides.append((point.latitude, point.longitude))
        return legs

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "colour": self.colour,
            "loop": self.loop,
            "stop_ids": list(self.stop_ids),
            "points": [point.to_dict() for point in self.points],
            "path": [list(p) for p in self.path],
        }


@dataclass(frozen=True)
class Position:
    """
    A telemetry sample for one vehicle at one instant.
    """

    vehicle_id: str
    timestamp: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    heading_deg: Optional[float] = None
    speed_mps: Optional[float] = None
    gps_status: Optional[int] = None
    battery_percent: Optional[float] = None

    NO_FIX = -1

    @property
    def has_fix(self) -> bool:
        return self.gps_status is not None and self.gps_status >= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "timestamp": format_timestamp(self.timestamp),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude_m": self.altitude_m,
            "heading_deg": self.heading_deg,
            "speed_mps": self.speed_mps,
            "gps_status": self.gps_status,
            "battery_percent": self.battery_percent,
        }


@dataclass(frozen=True)
class PickupRequest:
    """
    A rider's request to be picked up at a stop (docs/api.md, S08)
    """

    id: str
    stop_id: str
    rider_token: str
    status: str
    created_at: datetime
    cleared_at: Optional[datetime] = None
    # Set only once collected (backend/api/pickup_requests.py:collect_at_stop()),
    # from whichever vehicle and route the operator said they were running at
    # the time -- there is no schedule yet to look this up from instead. A
    # review (Review below) is attributed to a pickup through these.
    vehicle_id: Optional[str] = None
    route_id: Optional[str] = None

    OPEN = "open"
    COLLECTED = "collected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stop_id": self.stop_id,
            "status": self.status,
            "created_at": format_timestamp(self.created_at),
            "cleared_at": format_timestamp(self.cleared_at) if self.cleared_at else None,
            "vehicle_id": self.vehicle_id,
            "route_id": self.route_id,
        }


@dataclass(frozen=True)
class Review:
    """
    A rider's review of one completed pickup (S15 follow-up).

    `vehicle_id`, `route_id` and `wait_minutes` are not asked of the rider:
    they are read off the `PickupRequest` the review is attributed to
    (`pickup_request_id`) at the moment it is saved
    (backend/api/reviews.py:create_review()), since that is the operator's
    own record of which vehicle and route it was and exactly how long the
    wait was -- more reliable than asking the rider to recall either.

    Every field below `created_at` besides `safety_rating` and `app_rating`
    is optional: an empty string (not stored as null, so the file's shape is
    uniform) rather than forcing a rider through a long form to leave a
    quick rating.
    """

    id: str
    pickup_request_id: str
    stop_id: str
    vehicle_id: Optional[str]
    route_id: Optional[str]
    wait_minutes: Optional[float]
    created_at: datetime

    # Safety & comfort
    safety_rating: int  # 1-5
    vehicle_behaviour: str
    obstacle_interaction: str

    # Efficiency & operations
    punctuality: str  # "early" | "on_time" | "late" | ""
    ride_duration_ok: str  # "yes" | "no" | ""
    purpose: str

    # Route & accessibility
    stop_quality: str  # "good" | "could_be_better" | ""
    ramp_needed: str  # "yes" | "no" | ""

    # Tech & interface
    app_rating: int  # 1-5
    app_comment: str

    # Rider demographics. The rider's browser remembers these between
    # reviews (a cookie, js/rider.js), so a returning rider does not have to
    # re-answer them -- not sent to or read back from the server at all.
    role: str  # "undergrad" | "postgrad" | "staff" | "visitor" | ""
    usage_frequency: str  # "daily" | "weekly" | "occasional" | "first_time" | ""

    # Recommendations / improvements
    comments: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pickup_request_id": self.pickup_request_id,
            "stop_id": self.stop_id,
            "vehicle_id": self.vehicle_id,
            "route_id": self.route_id,
            "wait_minutes": self.wait_minutes,
            "created_at": format_timestamp(self.created_at),
            "safety_rating": self.safety_rating,
            "vehicle_behaviour": self.vehicle_behaviour,
            "obstacle_interaction": self.obstacle_interaction,
            "punctuality": self.punctuality,
            "ride_duration_ok": self.ride_duration_ok,
            "purpose": self.purpose,
            "stop_quality": self.stop_quality,
            "ramp_needed": self.ramp_needed,
            "app_rating": self.app_rating,
            "app_comment": self.app_comment,
            "role": self.role,
            "usage_frequency": self.usage_frequency,
            "comments": self.comments,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Review":
        return cls(
            id=str(raw["id"]),
            pickup_request_id=str(raw["pickup_request_id"]),
            stop_id=str(raw["stop_id"]),
            vehicle_id=raw.get("vehicle_id"),
            route_id=raw.get("route_id"),
            wait_minutes=raw.get("wait_minutes"),
            created_at=parse_timestamp(raw["created_at"]),
            safety_rating=int(raw["safety_rating"]),
            vehicle_behaviour=str(raw.get("vehicle_behaviour") or ""),
            obstacle_interaction=str(raw.get("obstacle_interaction") or ""),
            punctuality=str(raw.get("punctuality") or ""),
            ride_duration_ok=str(raw.get("ride_duration_ok") or ""),
            purpose=str(raw.get("purpose") or ""),
            stop_quality=str(raw.get("stop_quality") or ""),
            ramp_needed=str(raw.get("ramp_needed") or ""),
            app_rating=int(raw["app_rating"]),
            app_comment=str(raw.get("app_comment") or ""),
            role=str(raw.get("role") or ""),
            usage_frequency=str(raw.get("usage_frequency") or ""),
            comments=str(raw.get("comments") or ""),
        )


@dataclass(frozen=True)
class Downtime:
    """
    A period an administrator recorded a shuttle as out of service (S18).
    """

    id: str
    vehicle_id: str
    start: datetime
    end: datetime
    reason: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vehicle_id": self.vehicle_id,
            "start": format_timestamp(self.start),
            "end": format_timestamp(self.end),
            "reason": self.reason,
            "created_at": format_timestamp(self.created_at),
            "updated_at": format_timestamp(self.updated_at),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Downtime":
        return cls(
            id=str(raw["id"]),
            vehicle_id=str(raw["vehicle_id"]),
            start=parse_timestamp(raw["start"]),
            end=parse_timestamp(raw["end"]),
            reason=str(raw["reason"]),
            created_at=parse_timestamp(raw["created_at"]),
            updated_at=parse_timestamp(raw["updated_at"]),
        )
