"""
The route editor: encoded polylines, routing along the campus path network,
filling in and writing back route paths, and /api/network.
"""

from __future__ import annotations
import shutil
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import yaml

from backend import polyline
from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR, load_config
from backend.path_network import PathNetwork, distance_m
from backend.stops import dump_stops, file_header, parse_stops, resolve_paths, save_stops
from tests.admin_support import sign_in, write_admin_secrets

NOW = datetime(2026, 10, 6, 1, tzinfo=timezone.utc)


# ---- Encoded polylines ----


def test_a_polyline_round_trips_at_six_decimals():
    points = [(-31.979012, 115.818355), (-31.98, 115.8172), (-31.984881, 115.820102)]
    assert polyline.decode(polyline.encode(points)) == points


def test_an_encoded_polyline_never_needs_quoting_in_single_quotes():
    text = polyline.encode([(-31.97 - i / 997, 115.81 + i / 1013) for i in range(400)])
    assert "'" not in text


def test_garbage_is_not_a_polyline():
    with pytest.raises(ValueError):
        polyline.decode("abc def")


# ---- Routing on a small network ----
#
#   a ---- b ---- c        d (on its own)
#          |
#          e


@pytest.fixture
def grid():
    nodes = [(-31.980, 115.810), (-31.980, 115.812), (-31.980, 115.814), (-31.990, 115.830), (-31.982, 115.812)]
    return PathNetwork(nodes, [[0, 1, 2], [1, 4], [3, 3]])


def test_a_leg_follows_the_paths_and_meets_its_ends(grid):
    start, end = (-31.9801, 115.8100), (-31.9819, 115.8121)
    leg = grid.leg(start, end)
    assert leg.routed
    assert leg.path[0] == start and leg.path[-1] == end
    # Along a-b then down b-e, so it turns at b.
    assert (-31.98, 115.812) in leg.path


def test_a_straight_leg_is_two_points(grid):
    leg = grid.leg((-31.9801, 115.8100), (-31.9819, 115.8121), straight=True)
    assert leg.path == ((-31.9801, 115.8100), (-31.9819, 115.8121)) and not leg.routed


def test_ends_on_one_edge_run_along_it(grid):
    leg = grid.leg((-31.9801, 115.8105), (-31.9801, 115.8115))
    assert leg.routed and len(leg.path) == 4


def test_unconnected_ends_fall_back_to_a_straight_leg():
    network = PathNetwork([(-31.98, 115.81), (-31.98, 115.811), (-31.99, 115.83), (-31.99, 115.831)], [[0, 1], [2, 3]])
    leg = network.leg((-31.98, 115.8105), (-31.99, 115.8305))
    assert not leg.routed and len(leg.path) == 2


def test_snapping_finds_the_nearest_point_on_an_edge(grid):
    snap = grid.snap((-31.9805, 115.813))
    assert snap.point == pytest.approx((-31.98, 115.813))
    assert 50 < snap.offset_m < 60


def test_the_projects_campus_paths_route_between_real_stops():
    network = PathNetwork.load(DEFAULT_CONFIG_DIR / "campus_paths.json")
    stops = load_config().stops.stops
    a, b = stops["civ-mech"], stops["business-school"]
    leg = network.leg((a.latitude, a.longitude), (b.latitude, b.longitude))
    assert leg.routed
    assert leg.length_m >= distance_m((a.latitude, a.longitude), (b.latitude, b.longitude))


# ---- Filling in and writing back ----


RAW = {
    "stops": [
        {"id": "a", "name": "A", "latitude": -31.980, "longitude": 115.810},
        {"id": "b", "name": "B", "latitude": -31.982, "longitude": 115.812},
    ],
    "routes": [{"id": "r", "name": "R", "stops": ["a", "b"]}],
}


def test_a_route_written_as_stops_gets_a_path_through_them(grid):
    network = resolve_paths(parse_stops(RAW), grid)
    route = network.routes["r"]
    assert [p.stop_id for p in route.points] == ["a", "b"]
    assert route.points[0].path == ()
    assert route.path[0] == (-31.98, 115.81) and route.path[-1] == (-31.982, 115.812)


def test_without_a_path_network_legs_are_straight():
    route = resolve_paths(parse_stops(RAW)).routes["r"]
    assert route.path == ((-31.98, 115.81), (-31.982, 115.812))


def test_a_path_whose_ends_no_longer_meet_its_stops_is_worked_out_again(grid):
    network = resolve_paths(parse_stops(RAW), grid)
    moved = replace(network, stops={**network.stops, "b": replace(network.stops["b"], latitude=-31.9815)})
    route = resolve_paths(moved, grid).routes["r"]
    assert route.path[-1] == (-31.9815, 115.812)


def test_a_guide_point_shapes_the_route_and_is_not_a_stop():
    raw = {**RAW, "routes": [{"id": "r", "name": "R", "points": [
        {"stop": "a"}, {"guide": [-31.981, 115.8105], "straight": True}, {"stop": "b", "straight": True}]}]}
    route = resolve_paths(parse_stops(raw)).routes["r"]
    assert route.stop_ids == ("a", "b")
    assert (-31.981, 115.8105) in route.path
    [leg] = route.legs()
    assert (leg.from_stop, leg.to_stop, leg.guides) == ("a", "b", ((-31.981, 115.8105),))


@pytest.mark.parametrize("points, problem", [
    ([{"stop": "a"}, {"guide": [-31.981, 115.81]}], "must start and end at a stop"),
    ([{"guide": [-31.981, 115.81]}], "at least one stop"),
    ([{"stop": "a"}, {"stop": "zz"}], "not a configured stop"),
    ([{"stop": "a"}, {"guide": [115.81, -31.98]}, {"stop": "b"}], "between -90 and 90"),
    ([{"stop": "a", "guide": [1, 2]}], "either 'stop' or 'guide'"),
    ([{"stop": "a"}, {"stop": "b", "path": "!!"}], "not an encoded polyline"),
])
def test_bad_points_are_refused(points, problem):
    raw = {**RAW, "routes": [{"id": "r", "name": "R", "points": points}]}
    with pytest.raises(Exception) as caught:
        parse_stops(raw)
    assert problem in str(caught.value.problems)


def test_a_loop_may_start_at_a_guide_point():
    raw = {**RAW, "routes": [{"id": "r", "name": "R", "loop": True, "points": [
        {"guide": [-31.981, 115.81]}, {"stop": "a"}, {"stop": "b"}]}]}
    assert parse_stops(raw).routes["r"].stop_ids == ("a", "b")


def test_the_written_file_reads_back_the_same(tmp_path, grid):
    path = tmp_path / "stops.yaml"
    path.write_text("# Stops and routes.\n# Second line.\n\nstops: []\nroutes: []\n")
    network = resolve_paths(parse_stops({**RAW, "stops": [{**RAW["stops"][0], "name": 'Odd: "name" #1'}, RAW["stops"][1]]}), grid)
    save_stops(path, network)
    text = path.read_text()
    assert text.startswith("# Stops and routes.\n# Second line.\n")
    assert parse_stops(yaml.safe_load(text)) == network
    assert yaml.safe_load(text)["routes"][0]["stops"] == ["a", "b"]


def test_the_projects_own_routes_survive_a_rewrite():
    network = load_config().stops
    text = dump_stops(network, file_header((DEFAULT_CONFIG_DIR / "stops.yaml").read_text()))
    assert parse_stops(yaml.safe_load(text)) == network


# ---- /api/network ----


@pytest.fixture
def config_dir(tmp_path):
    target = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, target)
    write_admin_secrets(target)
    return target


@pytest.fixture
def client(config_dir):
    app = create_app(config_dir=config_dir)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        test_client.config_dir = config_dir
        yield sign_in(test_client)


def editor_body(client):
    """
    GET /api/network as the editor would send it back, unchanged.
    """
    data = client.get("/api/network").get_json()
    return {
        "stops": [{k: s[k] for k in ("id", "name", "latitude", "longitude")} for s in data["stops"]],
        "routes": [{
            "id": r["id"], "name": r["name"], "colour": r["colour"], "loop": r["loop"],
            "points": [({"stop": p["stop_id"]} if "stop_id" in p else {"latitude": p["latitude"], "longitude": p["longitude"]})
                       | {"straight": p["straight"]} for p in r["points"]],
        } for r in data["routes"]],
    }


def test_every_network_endpoint_is_admin_only(config_dir):
    with create_app(config_dir=config_dir).test_client() as anonymous:
        assert anonymous.get("/api/network").status_code == 401
        assert anonymous.get("/api/network/paths").status_code == 401
        assert anonymous.post("/api/network/legs", json={"points": []}).status_code == 401
        assert anonymous.put("/api/network", json={"stops": [], "routes": []}).status_code == 401


def test_the_editor_gets_stops_routes_and_the_path_network(client):
    data = client.get("/api/network").get_json()
    assert {s["id"] for s in data["stops"]} >= {"reid-library", "civ-mech"}
    route = next(r for r in data["routes"] if r["id"] == "nth-south")
    assert route["points"][0]["stop_id"] == "reid-library" and len(route["path"]) > 2
    assert data["paths"]["available"] and "OpenStreetMap" in data["paths"]["attribution"]
    paths = client.get("/api/network/paths").get_json()
    assert len(paths["nodes"]) > 1000 and len(paths["edges"]) > 1000


def test_without_a_snapshot_paths_are_unavailable_and_legs_straight(config_dir):
    (config_dir / "campus_paths.json").unlink()
    app = create_app(config_dir=config_dir)
    with app.test_client() as test_client:
        sign_in(test_client)
        assert test_client.get("/api/network/paths").status_code == 404
        legs = test_client.post("/api/network/legs", json={"points": [
            {"latitude": -31.98, "longitude": 115.817}, {"latitude": -31.983, "longitude": 115.819}]}).get_json()["legs"]
    assert legs[0] is None and legs[1] == {"path": [[-31.98, 115.817], [-31.983, 115.819]], "routed": False}


def test_legs_follow_the_paths_unless_straight(client):
    points = [{"latitude": -31.980744, "longitude": 115.817205}, {"latitude": -31.984881, "longitude": 115.820102}]
    legs = client.post("/api/network/legs", json={"points": points}).get_json()["legs"]
    assert legs[0] is None and legs[1]["routed"] and len(legs[1]["path"]) > 2
    points[1]["straight"] = True
    legs = client.post("/api/network/legs", json={"points": points, "loop": True}).get_json()["legs"]
    assert legs[0]["routed"] and len(legs[1]["path"]) == 2


def test_bad_points_for_legs_are_a_400(client):
    assert client.post("/api/network/legs", json={"points": [{"latitude": "x"}]}).status_code == 400
    assert client.post("/api/network/legs", json={"points": "no"}).status_code == 400


def test_saving_unchanged_keeps_every_id_and_route(client):
    before = client.get("/api/routes").get_json()
    response = client.put("/api/network", json=editor_body(client))
    assert response.status_code == 200
    after = client.get("/api/routes").get_json()
    assert [(r["id"], r["stop_ids"]) for r in after["routes"]] == [(r["id"], r["stop_ids"]) for r in before["routes"]]


def test_a_new_stop_and_route_get_ids_and_apply_at_once(client):
    body = editor_body(client)
    body["stops"].append({"id": None, "key": "new-1", "name": "Pharmacy Lawn", "latitude": -31.9815, "longitude": 115.8180})
    body["routes"].append({"id": None, "name": "Lawn Shuttle", "colour": "#00838F", "loop": False, "points": [
        {"stop": "reid-library"}, {"latitude": -31.9805, "longitude": 115.8183}, {"stop": "new-1"}]})
    response = client.put("/api/network", json=body)
    assert response.status_code == 200

    route = client.get("/api/routes/lawn-shuttle").get_json()
    assert [s["id"] for s in route["stops"]] == ["reid-library", "pharmacy-lawn"]
    assert len(route["path"]) > 3
    written = yaml.safe_load((client.config_dir / "stops.yaml").read_text())
    assert any(r["id"] == "lawn-shuttle" for r in written["routes"])


def test_renaming_a_stop_keeps_its_id(client):
    body = editor_body(client)
    next(s for s in body["stops"] if s["id"] == "civ-mech")["name"] = "Civil Engineering"
    client.put("/api/network", json=body)
    assert client.get("/api/stops/civ-mech").get_json()["name"] == "Civil Engineering"


def test_an_invalid_network_is_a_400_listing_problems_and_writes_nothing(client):
    before = (client.config_dir / "stops.yaml").read_text()
    body = editor_body(client)
    body["routes"][2]["points"].append({"latitude": -31.98, "longitude": 115.81})  # nth-south, not a loop
    response = client.put("/api/network", json=body)
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error["code"] == "invalid_network"
    assert any("must start and end at a stop" in p for p in error["problems"])
    assert (client.config_dir / "stops.yaml").read_text() == before


def test_a_stop_outside_the_bounds_is_refused(client):
    body = editor_body(client)
    body["stops"][0]["latitude"] = -10.0
    assert client.put("/api/network", json=body).status_code == 400


def test_a_stop_riders_are_waiting_at_cannot_be_removed(client):
    client.application.config["PICKUP_REQUEST_STORE"].create("marine-research", "rider-1", NOW)
    before = (client.config_dir / "stops.yaml").read_text()
    body = editor_body(client)
    body["stops"] = [s for s in body["stops"] if s["id"] != "marine-research"]
    for route in body["routes"]:
        route["points"] = [p for p in route["points"] if p.get("stop") != "marine-research"]
    response = client.put("/api/network", json=body)
    assert response.status_code == 409
    assert response.get_json()["error"]["stops"] == ["marine-research"]
    assert (client.config_dir / "stops.yaml").read_text() == before


def test_a_malformed_body_is_a_400(client):
    assert client.put("/api/network", json={"stops": "x"}).status_code == 400
    assert client.put("/api/network", json={"stops": [], "routes": [{"name": "x"}]}).status_code == 400
