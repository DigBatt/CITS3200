"""Configured route paths meet real stops and stay connected to the sketches."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='Node.js is needed to check map geometry')


@pytest.fixture(scope='module')
def geometry():
    network = yaml.safe_load((ROOT / 'config/stops.yaml').read_text())
    script = """
const fs = require('fs'), vm = require('vm');
const network = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = {window: {}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('frontend/js/route-paths.js', 'utf8'), context);
console.log(JSON.stringify(Object.fromEntries(network.routes.map(route =>
  [route.id, context.window.RoutePaths.pathsFor(route, network.stops)]))));
"""
    result = subprocess.run([NODE, '-e', script], input=json.dumps(network),
                            text=True, capture_output=True, cwd=ROOT, check=True)
    return network, json.loads(result.stdout)


def test_all_five_existing_routes_have_paths(geometry):
    network, paths = geometry
    assert len(network['routes']) == 5
    assert all(paths.values())
    assert not any(r['name'].startswith('Demo:') for r in network['routes'])


def test_every_route_passes_exactly_through_its_stops(geometry):
    network, paths = geometry
    stops = {s['id']: [s['latitude'], s['longitude']] for s in network['stops']}
    for route in network['routes']:
        vertices = [p for path in paths[route['id']] for p in path]
        for stop_id in route['stops']:
            assert stops[stop_id] in vertices, (route['id'], stop_id)


def test_path_parts_are_connected(geometry):
    _, paths = geometry
    for route_id, parts in paths.items():
        # A branch must share a point with the route, not float separately.
        reached = set(map(tuple, parts[0]))
        remaining = list(parts[1:])
        while remaining:
            touching = [p for p in remaining if reached.intersection(map(tuple, p))]
            assert touching, route_id
            for part in touching:
                reached.update(map(tuple, part))
                remaining.remove(part)


def test_oval_is_closed_without_an_automatic_diagonal(geometry):
    _, paths = geometry
    oval = paths['james-oval-loop'][0]
    assert oval[0] == oval[-1]
    assert len(oval) > 30


def test_renderer_replaces_clears_and_toggles_route_layers():
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const group = () => ({items: [], visible: true,
  clearLayers() { this.items = []; }, addTo() { this.visible = true; }});
const routes = group(), stops = group();
const ctx = { window: {}, routesGroup: routes, stopsGroup: stops,
  fakeMap: {removeLayer(layer) {layer.visible = false;}},
  RoutePaths: {pathsFor(route) {return route ? [[[1,2],[3,4]]] : [];}},
  L: {polyline(points, options) {return {addTo(layer) {layer.items.push({points, options});}};}} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('frontend/js/map.js','utf8'), ctx);
vm.runInContext('layers.routes = routesGroup; layers.stops = stopsGroup; map = fakeMap;', ctx);
ctx.drawRoutePath({colour:'#123456'}, []);
assert.equal(routes.items.length, 1);
assert.equal(routes.items[0].options.dashArray, '1 8');
assert.equal(routes.items[0].options.smoothFactor, 0);
ctx.drawRoutePath({colour:'#abcdef'}, []);
assert.equal(routes.items.length, 1);
assert.equal(routes.items[0].options.color, '#abcdef');
ctx.setStopsVisible(false);
assert.equal(routes.visible, false);
assert.equal(stops.visible, false);
ctx.setStopsVisible(true);
assert.equal(routes.visible, true);
ctx.drawRoutePath(null, []);
assert.equal(routes.items.length, 0);
"""
    subprocess.run([NODE, '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)
