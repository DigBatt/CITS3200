// Run with: node tests/test_campus3d.cjs
// Exercise the production renderer with deterministic map/WebGL adapters.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let map, renders = 0, disposed = 0;
const markers = new Set();
class Scene {
  constructor() { this.children = []; }
  add(...items) { this.children.push(...items); }
  traverse(fn) { this.children.forEach(fn); }
}
class Matrix {
  makeTranslation() { return this; } scale() { return this; }
  multiply() { return this; } makeRotationX() { return this; }
  makeRotationY() { return this; } fromArray() { return this; }
}
const colour = () => ({ set() {} });
const mesh = () => ({ geometry: { dispose() { disposed++; } }, material: { color: colour(), dispose() {} } });
class FakeMap {
  constructor() { map = this; this.sources = {}; this.layers = {}; this.fits = []; this.jumps = []; }
  on() {} loaded() { return true; } getLayer() { return null; }
  addSource(id, source) { this.sources[id] = { data: source.data, setData(data) { this.data = data; } }; }
  getSource(id) { return this.sources[id]; }
  addLayer(layer) { this.layers[layer.id] = layer; layer.onAdd?.(this, {}); }
  getCanvas() { return {}; } triggerRepaint() {} getBearing() { return 0; }
  jumpTo(view) { this.jumps.push(view); } fitBounds(bounds) { this.fits.push(bounds); }
  resize() {} remove() {} areTilesLoaded() { return true; }
}
class Marker {
  constructor(options) { this.label = options.element; }
  setLngLat(point) { this.point = point; return this; }
  addTo() { markers.add(this); return this; }
  remove() { markers.delete(this); }
}
const context = vm.createContext({
  console, Map, Set, performance: { now: () => 0 },
  document: { hidden: false, createElement: () => ({ style: {} }), addEventListener() {}, removeEventListener() {} },
  window: { maplibregl: {
    Map: FakeMap, Marker,
    LngLatBounds: class { constructor() { this.points = []; } extend(p) { this.points.push(p); return this; } },
    MercatorCoordinate: { fromLngLat: () => ({ x: 0, y: 0, z: 0, meterInMercatorCoordinateUnits: () => 1 }) },
  }, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) },
  THREE: { Scene, Camera: class {}, Matrix4: Matrix, Vector3: class {},
    HemisphereLight: class {}, DirectionalLight: class { position = { set() {} }; },
    MathUtils: { degToRad: n => n },
    WebGLRenderer: class { resetState() {} render() { renders++; } },
  },
  buildBus: () => ({ solid: mesh(), ghost: mesh(), ghostEdges: { color: colour() } }), buildRing: mesh,
  loadModel: async () => ({}),
  IntersectionObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame: () => 1, cancelAnimationFrame() {}, setTimeout, clearTimeout,
});
let source = fs.readFileSync(path.join(__dirname, '../frontend/js/campus3d.js'), 'utf8');
source = source.replace(/^import .*;\n/gm, '').replace('export async function mount', 'async function mount');
vm.runInContext(source + '\nglobalThis.mount = mount;', context);
const bus = (id, lng) => ({ id, name: `nUWAy ${id}`, lng, lat: -31.98, colour: id === '1' ? '#ff0000' : '#0000ff', trail: [[lng - .001, -31.98], [lng, -31.98]] });
(async () => {
  const api = await context.mount({}, { spin: false });
  const first = bus('1', 115.81), second = bus('2', 115.82);
  api.showAll([first]);
  api.showAll([first, second]);
  assert.equal(markers.size, 2, 'adding a selection retains both models/labels');
  assert.equal(map.sources['nuway-trail'].data.features.length, 2, 'both trails reach the map');
  assert.equal(map.fits.length, 1, 'multiple buses are framed together');
  assert.equal(map.fits[0].points.length, 6, 'bounds contain positions and both trails');
  map.layers['nuway-bus'].render({}, []);
  assert.equal(renders, 4, 'each bus renders its solid and ghost model');
  api.showAll([second, first]);
  assert.equal(map.fits.length, 1, 'reordering does not reset the camera');
  api.showAll([first, second], '2', true);
  assert.equal(markers.size, 2, 'focusing one keeps the other visible');
  assert.equal(map.jumps.at(-1).center[0], second.lng);
  api.showAll([first, { ...second, lng: 115.83 }]);
  assert.equal([...markers].find(m => m.label.textContent === 'nUWAy 2').point[0], 115.83, 'position updates apply per bus');
  api.showAll([second]);
  assert.equal(markers.size, 1);
  assert.equal(map.sources['nuway-trail'].data.features.length, 1);
  assert.ok(disposed > 0, 'deselected models release resources');
  api.showAll([]);
  assert.equal(markers.size, 0);
  assert.equal(map.sources['nuway-trail'].data.features.length, 0);
  api.showAll([second, first]);
  assert.equal(markers.size, 2, 'reverse selection order also shows both buses');
  api.destroy();
  assert.equal(markers.size, 0);
  console.log('PASS: multiple buses, trails, framing, focus, updates, deselection and cleanup');
})().catch(error => { console.error(error); process.exitCode = 1; });

// The controller must send the whole selection, not just its current bus.
(async () => {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { checked: false, hidden: true, style: {},
      classList: { toggle() {}, add() {}, remove() {} },
      handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; } });
    return nodes.get(id);
  };
  let lastFixes, focused;
  const api = { showAll(fixes, id, requested) { lastFixes = fixes; focused = requested; }, resize() {}, setPaused() {} };
  const scope = vm.createContext({ console, URL,
    document: { baseURI: 'http://localhost/', querySelector: node, getElementById: node, querySelectorAll: () => [] },
    window: { addEventListener() {}, matchMedia: () => ({ matches: true }) },
    localStorage: { getItem: () => null }, navigator: {},
    splitAtGaps: fixes => [fixes], formatInstant: value => value,
    request: async () => ({ available: false }), showMap() {},
    __loadView: async () => ({ mount: async () => api }),
  });
  const source = fs.readFileSync(path.join(__dirname, '../frontend/js/view3d.js'), 'utf8')
    .replace('import(new URL(MODULES[name], document.baseURI).href)', '__loadView()');
  vm.runInContext(source, scope);
  const vehicle = id => ({ vehicle_id: id, positions: [{ latitude: -31.98, longitude: 115.81,
    timestamp: '2026-10-11T06:00:00Z' }] });
  scope.window.View3D.update([vehicle('2'), vehicle('1'), { vehicle_id: '3', positions: [] }]);
  node('map-3d-toggle').checked = true;
  node('map-3d-toggle').handlers.change();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(Array.from(lastFixes, fix => fix.id), ['2', '1']);
  assert.equal(focused, false);
  scope.window.View3D.update([vehicle('1')]);
  assert.deepEqual(Array.from(lastFixes, fix => fix.id), ['1']);
  scope.window.View3D.update([]);
  assert.equal(lastFixes.length, 0);
  console.log('PASS: controller forwards all selected positioned buses and clears empty selection');
})().catch(error => { console.error(error); process.exitCode = 1; });
