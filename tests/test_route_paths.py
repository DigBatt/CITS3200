import json
"""Stored route paths meet real stops, join up, and are drawn once each."""
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.config import load_config
from backend.path_network import distance_m

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@pytest.fixture(scope='module')
def network():
    return load_config().stops


def test_all_five_existing_routes_have_paths(network):
    assert len(network.routes) == 5
    assert all(len(route.path) > 1 for route in network.routes.values())
    assert not any(route.name.startswith('Demo:') for route in network.routes.values())


def test_every_route_passes_through_its_stops(network):
    # Paths are kept to 6 decimals (about 0.1 m), so they meet a stop's
    # marker rather than its exact configured coordinate.
    for route in network.routes.values():
        for stop_id in route.stop_ids:
            stop = network.stops[stop_id]
            assert min(distance_m((stop.latitude, stop.longitude), p) for p in route.path) < 0.2, (route.id, stop_id)


def test_each_leg_starts_where_the_last_one_ended(network):
    for route in network.routes.values():
        points = list(route.points)
        ordered = points[1:] + (points[:1] if route.loop else [])
        for before, after in zip(ordered, ordered[1:]):
            assert distance_m(before.path[-1], after.path[0]) < 0.2, route.id


def test_a_loop_closes_and_a_line_does_not(network):
    for route in network.routes.values():
        ends_meet = distance_m(route.path[0], route.path[-1]) < 0.2
        assert ends_meet == route.loop, route.id


def test_legs_run_stop_to_stop(network):
    route = network.routes['james-oval-loop']
    legs = route.legs()
    assert [(leg.from_stop, leg.to_stop) for leg in legs] == list(
        zip(route.stop_ids, route.stop_ids[1:] + route.stop_ids[:1]))
    assert len(route.path) > 30


def test_the_hand_traced_shapes_are_kept_as_guide_points(network):
    # The paths traced from the October route sketches became guide points
    # with hand drawn legs, so the map draws them as before.
    for route in network.routes.values():
        assert any(not point.is_stop for point in route.points), route.id
        assert all(point.straight for point in route.points), route.id


def test_config_file_lists_stops_as_a_summary_of_points():
    raw = json.loads((ROOT / 'config/stops.json').read_text())
    for route in raw['routes']:
        assert route['stops'] == [p['stop'] for p in route['points'] if 'stop' in p]


@pytest.mark.skipif(NODE is None, reason='Node.js is needed to run map.js')
def test_renderer_replaces_clears_and_toggles_route_layers():
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const group = () => ({items: [], visible: true,
  clearLayers() { this.items = []; }, addTo() { this.visible = true; }});
const routes = group(), stops = group();
const ctx = { window: {}, routesGroup: routes, stopsGroup: stops,
  fakeMap: {removeLayer(layer) {layer.visible = false;}},
  L: {polyline(points, options) {return {addTo(layer) {layer.items.push({points, options});}};}} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'), ctx);
vm.runInContext('layers.routes = routesGroup; layers.stops = stopsGroup; map = fakeMap;', ctx);
ctx.drawRoutePath({colour:'#123456', path: [[1,2],[3,4]]});
assert.equal(routes.items.length, 1);
assert.equal(routes.items[0].options.dashArray, '1 8');
assert.equal(routes.items[0].options.smoothFactor, 0);
ctx.drawRoutePath({colour:'#abcdef', path: [[1,2],[3,4]]});
assert.equal(routes.items.length, 1);
assert.equal(routes.items[0].options.color, '#abcdef');
// Out along a spur and back: the stretch is drawn once, not twice.
ctx.drawRoutePath({colour:'#abcdef', path: [[0,0],[1,1],[2,2],[1,1],[0,0],[0,5]]});
const drawn = routes.items.flatMap(item => item.points.slice(1).map((p, i) => [item.points[i], p]));
assert.equal(drawn.length, 3);
ctx.setStopsVisible(false);
assert.equal(routes.visible, false);
assert.equal(stops.visible, false);
ctx.setStopsVisible(true);
assert.equal(routes.visible, true);
ctx.drawRoutePath(null);
assert.equal(routes.items.length, 0);
"""
    # No cwd and close_fds=False let Python start Node with posix_spawn
    # rather than fork. On macOS a fork after test_fetch.py's HTTP requests
    # can crash the child (SIGSEGV) before Node even starts.
    subprocess.run([NODE, '-e', script, str(ROOT / 'frontend/js/map.js')], close_fds=False,
                   check=True, capture_output=True, text=True)
