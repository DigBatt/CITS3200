"""
Stops and routes: backend.stops, config/stops.yaml, and the /api/stops and
/api/routes endpoints (S06).
"""

from __future__ import annotations
import logging
import math
import shutil
from pathlib import Path

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR, ConfigError, load_config
from backend.stops import StopsError, parse_stops

BOUNDS = {"latitude": [-36.0, -13.0], "longitude": [112.0, 130.0]}

# The three stops the Client named, at the coordinates agreed for S06.2.
CLIENT_STOPS = {
    "reid-library": (-31.97901221771226, 115.8183554056777),
    "civ-mech": (-31.980743857374474, 115.81720535774184),
    "business-school": (-31.985583444723204, 115.82089500479223),
}


def stop(stop_id, latitude=-31.98, longitude=115.82, name=None):
    name = str(stop_id).title() if name is None else name
    return {"id": stop_id, "name": name, "latitude": latitude, "longitude": longitude}


# Stop b is on both routes, c on neither.
NETWORK = {
    "stops": [stop("a"), stop("b"), stop("c"), stop("d")],
    "routes": [
        {"id": "north", "name": "North", "stops": ["a", "b"]},
        {"id": "south", "name": "South", "colour": "#123abc", "loop": True, "stops": ["d", "b"]},
    ],
}


def metres_between(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


@pytest.fixture
def config_dir(tmp_path):
    """
    A copy of the real config directory whose stops.yaml a test can rewrite.
    """
    for name in ("app.yaml", "vehicles.yaml", "stops.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    return tmp_path


def write_stops(config_dir: Path, raw) -> None:
    (config_dir / "stops.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


@pytest.fixture
def client(config_dir):
    write_stops(config_dir, NETWORK)
    return create_app(config_dir).test_client()


# ---- The committed config ----


def test_client_stops_present_and_correctly_placed():
    network = load_config().stops
    for stop_id, expected in CLIENT_STOPS.items():
        found = network.stop(stop_id)
        assert found is not None, f"{stop_id} missing from config/stops.yaml"
        assert metres_between((found.latitude, found.longitude), expected) < 25


def test_committed_config_has_a_route():
    network = load_config().stops
    assert network.routes
    for route in network.routes.values():
        assert network.stops_on_route(route.id)


# ---- Parsing ----


def test_stop_on_several_routes_is_in_each():
    network = parse_stops(NETWORK)
    assert [s.id for s in network.stops_on_route("north")] == ["a", "b"]
    assert [s.id for s in network.stops_on_route("south")] == ["d", "b"]
    assert [r.id for r in network.routes_for_stop("b")] == ["north", "south"]


def test_route_keeps_service_order():
    network = parse_stops(NETWORK)
    assert network.route("south").stop_ids == ("d", "b")


def test_route_defaults():
    network = parse_stops(NETWORK)
    assert network.route("north").colour is None
    assert network.route("north").loop is False
    assert network.route("south").loop is True


def test_stop_on_no_route_is_kept_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="backend.stops"):
        network = parse_stops(NETWORK)
    assert network.stop("c") is not None
    assert network.routes_for_stop("c") == ()
    assert "'c' is not on any route" in caplog.text


def test_unknown_ids_give_empty_lookups():
    network = parse_stops(NETWORK)
    assert network.stop("zzz") is None
    assert network.route("zzz") is None
    assert network.routes_for_stop("zzz") == ()
    assert network.stops_on_route("zzz") == ()


def test_numeric_id_is_read_as_text():
    network = parse_stops({"stops": [stop(7)], "routes": [{"id": "r", "name": "R", "stops": [7]}]})
    assert network.stop("7").id == "7"
    assert network.route("r").stop_ids == ("7",)


def test_empty_file_is_an_empty_network():
    network = parse_stops(None)
    assert network.stops == {} and network.routes == {}


# ---- Malformed files ----


def with_stop(**fields):
    entry = {**stop("bad"), **fields}
    return {"stops": [entry]}


def with_route(**fields):
    entry = {"id": "r", "name": "R", "stops": ["a"], **fields}
    return {"stops": [stop("a")], "routes": [entry]}


@pytest.mark.parametrize(
    "raw, expected",
    [
        (with_stop(latitude="abc"), "stops[0] (id 'bad'): latitude must be a number"),
        (with_stop(latitude=True), "stops[0] (id 'bad'): latitude must be a number"),
        (with_stop(latitude=-91), "stops[0] (id 'bad'): latitude must be a number between -90 and 90"),
        (with_stop(latitude=None), "stops[0] (id 'bad'): latitude must be a number"),
        (with_stop(latitude=115.8, longitude=-31.9), "(are latitude and longitude swapped?)"),
        (with_stop(name=""), "stops[0] (id 'bad'): name must be non-empty text"),
        (with_stop(id=None), "stops[0]: id is missing"),
        (with_stop(id="Reid Library"), "stops[0]: id must be lowercase letters and digits joined by hyphens"),
        (with_stop(lat=-31.9), "stops[0] (id 'bad'): unknown key 'lat'"),
        ({"stops": [stop("a"), stop("a")]}, "stops[1] (id 'a'): duplicate stop id, first used at stops[0]"),
        ({"stops": ["reid-library"]}, "stops[0]: must be a mapping"),
        ({"stops": {"a": 1}}, "stops must be a list"),
        ({"stop": []}, "unknown key 'stop'"),
        (with_route(stops=["a", "zz"]), "routes[0] (id 'r'): stop 'zz' is not a configured stop"),
        (with_route(stops=["a", "a"]), "routes[0] (id 'r'): stop 'a' is listed more than once"),
        (with_route(stops=[]), "routes[0] (id 'r'): stops must be a non-empty list"),
        (with_route(stops=None), "routes[0] (id 'r'): stops must be a non-empty list"),
        (with_route(colour="red"), "routes[0] (id 'r'): colour must be #rrggbb"),
        (with_route(loop="yes"), "routes[0] (id 'r'): loop must be true or false"),
        (
            {"stops": [stop("a")], "routes": [{"id": "r", "name": "R", "stops": ["a"]}] * 2},
            "routes[1] (id 'r'): duplicate route id, first used at routes[0]",
        ),
        ([1, 2], "must be a mapping with 'stops' and 'routes'"),
    ],
)
def test_malformed_entry_is_named(raw, expected):
    with pytest.raises(StopsError) as caught:
        parse_stops(raw, bounds=BOUNDS)
    assert expected in str(caught.value)


def test_every_problem_is_reported_together():
    raw = {
        "stops": [stop("a", latitude="abc"), stop("b", name="")],
        "routes": [{"id": "r", "name": "R", "stops": ["zz"]}],
    }
    with pytest.raises(StopsError) as caught:
        parse_stops(raw)
    assert len(caught.value.problems) == 3


def test_route_naming_a_broken_stop_is_not_also_unknown():
    raw = {"stops": [stop("a", latitude="abc")], "routes": [{"id": "r", "name": "R", "stops": ["a"]}]}
    with pytest.raises(StopsError) as caught:
        parse_stops(raw)
    assert caught.value.problems == ["config/stops.yaml: stops[0] (id 'a'): latitude must be a number between -90 and 90, got 'abc'"]


def test_malformed_file_stops_startup(config_dir):
    write_stops(config_dir, with_stop(latitude="abc"))
    with pytest.raises(ConfigError, match=r"stops\[0\] \(id 'bad'\): latitude"):
        create_app(config_dir)


def test_startup_uses_logger_bounds(config_dir):
    write_stops(config_dir, with_stop(latitude=-31.9, longitude=-115.8))
    with pytest.raises(ConfigError, match="outside the configured bounds"):
        load_config(config_dir)


def test_missing_file_stops_startup(config_dir):
    (config_dir / "stops.yaml").unlink()
    with pytest.raises(ConfigError, match="Missing config file"):
        load_config(config_dir)


def test_invalid_yaml_stops_startup(config_dir):
    (config_dir / "stops.yaml").write_text("stops: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Could not read"):
        load_config(config_dir)


# ---- API ----


def test_list_stops(client):
    body = client.get("/api/stops").get_json()
    assert [s["id"] for s in body["stops"]] == ["a", "b", "c", "d"]
    assert body["stops"][1] == {"id": "b", "name": "B", "latitude": -31.98, "longitude": 115.82, "routes": ["north", "south"]}
    assert body["stops"][2]["routes"] == []


def test_get_stop(client):
    response = client.get("/api/stops/d")
    assert response.status_code == 200
    assert response.get_json()["routes"] == ["south"]


def test_unknown_stop_is_404(client):
    response = client.get("/api/stops/zzz")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "unknown_stop"


def test_list_routes(client):
    body = client.get("/api/routes").get_json()
    assert body["routes"] == [
        {"id": "north", "name": "North", "colour": None, "loop": False, "stop_ids": ["a", "b"]},
        {"id": "south", "name": "South", "colour": "#123abc", "loop": True, "stop_ids": ["d", "b"]},
    ]


def test_get_route_returns_stops_in_order(client):
    body = client.get("/api/routes/south").get_json()
    assert "stop_ids" not in body
    assert [s["id"] for s in body["stops"]] == ["d", "b"]
    assert body["stops"][1]["routes"] == ["north", "south"]


def test_unknown_route_is_404(client):
    response = client.get("/api/routes/zzz")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "unknown_route"


def test_new_stop_appears_with_no_code_change(config_dir):
    raw = yaml.safe_load((config_dir / "stops.yaml").read_text(encoding="utf-8"))
    raw["stops"].append(stop("new-stop", name="New Stop"))
    raw["routes"][0]["stops"].append("new-stop")
    write_stops(config_dir, raw)

    client = create_app(config_dir).test_client()
    stops = {s["id"]: s for s in client.get("/api/stops").get_json()["stops"]}
    assert stops["new-stop"]["name"] == "New Stop"
    assert stops["new-stop"]["routes"] == [raw["routes"][0]["id"]]
    assert set(CLIENT_STOPS) <= set(stops)
