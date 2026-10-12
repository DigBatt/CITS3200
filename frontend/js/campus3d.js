// 3D view of the selected buses on campus: the nUWAy CAD model, in its real livery, at its
// position on a 3D map of UWA, with the camera slowly circling it.
//
// The map is MapLibre GL over OpenFreeMap's vector tiles (no key needed),
// whose building footprints carry heights, so the campus around the bus is
// extruded in 3D at its real coordinates. The bus is a three.js custom layer
// in the same WebGL context, drawn true to scale and turned to its heading.
//
// The bus model, its livery and its X-ray are js/bus-model.js, shared with the
// Earth view. The EZ10 is bidirectional, so which end leads does not matter;
// the length is laid along the heading.
//
// An ES module, imported by js/view3d.js the first time someone switches to
// 3D, so nobody else downloads MapLibre, three.js or the model. three.js
// comes from the import map in index.html; MapLibre is loaded here.

import * as THREE from 'three';
import { buildBus, buildRing, loadModel } from './bus-model.js';

const MAPLIBRE_VERSION = '4.7.1';
const MAPLIBRE_JS = `https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE_VERSION}/dist/maplibre-gl.js`;
const MAPLIBRE_CSS = `https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE_VERSION}/dist/maplibre-gl.css`;
const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty';

const CAMPUS_CENTRE = [115.81597, -31.98133]; // [lng, lat], as js/map.js
const ZOOM = 20.6;
const PITCH = 62;
// One full circle of the camera about every 50 seconds.
const ORBIT_DEGREES_PER_SECOND = 7.2;
// After someone drags or zooms, the camera waits this long before circling.
const ORBIT_RESUME_MS = 4000;
// A new position is glided to over this long rather than jumped to.
const GLIDE_MS = 1200;
const MODEL_LAYER_ID = 'nuway-bus';

// ---- Loading ----

function loadMapLibre() {
  if (window.maplibregl) return Promise.resolve(window.maplibregl);
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = MAPLIBRE_CSS;
  document.head.appendChild(css);
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = MAPLIBRE_JS;
    script.onload = () => resolve(window.maplibregl);
    script.onerror = () => reject(new Error('the 3D map library did not load'));
    document.head.appendChild(script);
  });
}

// ---- The view ----

/**
 * Mount the 3D view into `host`.
 *
 * @param {HTMLElement} host - Sized by CSS; the map fills it.
 * @param {Object} [options]
 * @param {(message: string) => void} [options.onStatus] - Loading and error
 *   messages to show over the view; '' clears it.
 * @param {boolean} [options.spin] - Whether the camera circles the bus to
 *   start with; `setSpin` changes it. Defaults to true.
 * @returns {Promise<{showAll: Function, setSpin: (on: boolean) => void, destroy: () => void}>}
 *   `showAll(buses, focusId, focusRequested)` draws every bus given, each
 *   `{ id, name, colour, lng, lat, heading, trail }` where `trail` is its
 *   recent track as [lng, lat] pairs. A new selection follows its one bus or
 *   frames them all. With `focusRequested`, the camera goes to the bus
 *   `focusId`, or back to framing them all when it is null.
 */
export async function mount(host, { onStatus = () => {}, spin: spinAtStart = true, paused: pausedAtStart = false } = {}) {
  onStatus('Loading the 3D campus…');
  let maplibregl;
  let modelData;
  try {
    [maplibregl, modelData] = await Promise.all([loadMapLibre(), loadModel()]);
  } catch (error) {
    onStatus(`Could not load the 3D view: ${error.message}.`);
    throw error;
  }

  let map;
  try {
    map = new maplibregl.Map({
      container: host,
      style: STYLE_URL,
      center: CAMPUS_CENTRE,
      zoom: ZOOM,
      pitch: PITCH,
      bearing: 0,
      maxPitch: 75,
      attributionControl: { compact: true },
      // The arrow keys step between buses (js/view3d.js), not pan the map.
      keyboard: false,
    });
  } catch (error) {
    onStatus('The 3D view needs WebGL, which this browser has turned off.');
    throw error;
  }
  map.on('error', (event) => console.warn('3D map:', event.error?.message ?? event));
  // The style names some point-of-interest icons its sprite sheet does not
  // have. A blank stand-in keeps each from warning in the console.
  map.on('styleimagemissing', ({ id }) => {
    if (!map.hasImage(id)) map.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) });
  });

  // ---- The bus, as a custom layer ----

  // Each selected vehicle owns its model, animation and label.
  const vehicles = new Map();
  const camera = new THREE.Camera();
  let renderer = null;
  let focusedId = null; // null keeps the camera on the fleet
  let selectionKey = '';
  let shown = []; // the targets last handed to showAll
  // Set when the camera should be framed again. Framing waits until the map
  // has a size, since a hidden map (after warming up, or behind Earth)
  // cannot fit anything.
  let framePending = false;
  // Whether the zoom is the fleet's fit rather than one someone chose.
  let fleetFramed = false;

  function createVehicle(target) {
    const bus = buildBus(modelData);
    const ring = buildRing();
    const scene = new THREE.Scene();
    scene.add(bus.solid, ring);
    const ghostScene = new THREE.Scene();
    ghostScene.add(bus.ghost);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7378, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 2.4);
    sun.position.set(-40, 80, 30);
    scene.add(sun);
    const label = document.createElement('span');
    label.textContent = target.name ?? `nUWAy ${target.id}`;
    Object.assign(label.style, {
      background: '#fff', color: '#1c1917', padding: '2px 6px',
      borderRadius: '4px', fontWeight: '700', border: '2px solid',
    });
    const marker = new maplibregl.Marker({ element: label, offset: [0, -22] })
      .setLngLat([target.lng, target.lat]).addTo(map);
    return { bus, ring, scene, ghostScene, marker, label,
      at: { lng: target.lng, lat: target.lat, heading: target.heading ?? 0 }, glide: null };
  }

  function disposeVehicle(vehicle) {
    vehicle.marker.remove();
    const geometries = new Set();
    const materials = new Set();
    for (const scene of [vehicle.scene, vehicle.ghostScene]) {
      scene.traverse((object) => {
        if (object.geometry) geometries.add(object.geometry);
        for (const material of [].concat(object.material ?? [])) materials.add(material);
      });
    }
    geometries.forEach((geometry) => geometry.dispose());
    materials.forEach((material) => material.dispose());
  }

  const layer = {
    id: MODEL_LAYER_ID,
    type: 'custom',
    renderingMode: '3d',
    onAdd(_map, gl) {
      renderer = new THREE.WebGLRenderer({ canvas: map.getCanvas(), context: gl, antialias: true });
      renderer.autoClear = false;
    },
    render(_gl, matrix) {
      const placed = [...vehicles.values()].map(({ at, scene, ghostScene }) => {
        const origin = maplibregl.MercatorCoordinate.fromLngLat([at.lng, at.lat], 0);
        const scale = origin.meterInMercatorCoordinateUnits();
        // Model space is metres, Y up, length along X. Map space is Mercator,
        // Z up, Y pointing south: stand the model up, then turn it about the
        // vertical so its length runs along the heading.
        const transform = new THREE.Matrix4()
          .makeTranslation(origin.x, origin.y, origin.z)
          .scale(new THREE.Vector3(scale, -scale, scale))
          .multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2))
          .multiply(new THREE.Matrix4().makeRotationY(THREE.MathUtils.degToRad(90 - at.heading)));
        return { scene, ghostScene, projection: new THREE.Matrix4().fromArray(matrix).multiply(transform) };
      });
      // Every bus's X-ray before any bus's solid: an X-ray ignores depth, so
      // one drawn after another bus's solid would show through it.
      for (const pass of ['ghostScene', 'scene']) {
        for (const vehicle of placed) {
          camera.projectionMatrix = vehicle.projection;
          renderer.resetState();
          renderer.render(vehicle[pass], camera);
        }
      }
    },
  };

  // ---- The trail ----

  const TRAIL_SOURCE = 'nuway-trail';
  const emptyTrail = { type: 'FeatureCollection', features: [] };

  await new Promise((resolve) => (map.loaded() ? resolve() : map.once('load', resolve)));

  // Softer buildings than the style's default, so the white bus stands out.
  if (map.getLayer('building-3d')) {
    map.setPaintProperty('building-3d', 'fill-extrusion-color', '#d9d6cf');
    map.setPaintProperty('building-3d', 'fill-extrusion-opacity', 0.88);
  }
  map.addSource(TRAIL_SOURCE, { type: 'geojson', data: emptyTrail });
  map.addLayer({
    id: 'nuway-trail',
    type: 'line',
    source: TRAIL_SOURCE,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ['get', 'colour'], 'line-width': 6, 'line-opacity': 0.75 },
  });
  map.addLayer(layer);
  onStatus('');

  // ---- Motion: the orbit and the glide ----

  // Reduced motion decides the page's default for spinning (js/view3d.js);
  // here it only makes a moving bus jump rather than glide.
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let spin = spinAtStart;
  // Paused, nothing moves: set while the view is built out of sight ahead of
  // being shown (js/view3d.js, warming up), so the camera keeps still and the
  // map can finish loading, rather than orbiting for nobody.
  let paused = pausedAtStart;
  let onScreen = true;
  let frame = null;
  let lastTime = null;
  let pausedUntil = 0;


  // Someone moving the view takes over from the orbit for a while.
  for (const event of ['dragstart', 'zoomstart', 'rotatestart', 'pitchstart']) {
    map.on(event, (e) => {
      if (e.originalEvent) pausedUntil = performance.now() + ORBIT_RESUME_MS;
    });
  }

  const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
  const turnTowards = (from, to, t) => {
    const delta = ((to - from + 540) % 360) - 180; // the short way round
    return from + delta * t;
  };

  function step(time) {
    frame = null;
    const dt = lastTime === null ? 0 : Math.min(time - lastTime, 100) / 1000;
    lastTime = time;
    let moving = false;

    for (const vehicle of vehicles.values()) {
      const { at, glide } = vehicle;
      if (!glide) continue;
      const t = Math.min((time - glide.start) / GLIDE_MS, 1);
      const k = easeInOut(t);
      at.lng = glide.from.lng + (glide.to.lng - glide.from.lng) * k;
      at.lat = glide.from.lat + (glide.to.lat - glide.from.lat) * k;
      at.heading = turnTowards(glide.from.heading, glide.to.heading, k);
      vehicle.marker.setLngLat([at.lng, at.lat]);
      if (t >= 1) vehicle.glide = null;
      moving = true;
    }

    const orbiting = spin && time >= pausedUntil;
    const followed = vehicles.get(focusedId);
    const view = followed ? { center: [followed.at.lng, followed.at.lat] } : {};
    if (orbiting) view.bearing = map.getBearing() + ORBIT_DEGREES_PER_SECOND * dt;
    // While someone is looking around, only follow the bus if it moves.
    if (orbiting || moving) map.jumpTo(view);
    else map.triggerRepaint();

    schedule();
  }

  function schedule() {
    if (frame !== null || paused || !onScreen || document.hidden) {
      if (paused || !onScreen || document.hidden) lastTime = null;
      return;
    }
    // Not spinning, there is nothing to animate once a glide is done.
    if (!spin && ![...vehicles.values()].some((vehicle) => vehicle.glide)) {
      lastTime = null;
      return;
    }
    frame = requestAnimationFrame(step);
  }

  const visibility = new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    if (onScreen) {
      map.resize();
      frameCamera();
    }
    schedule();
  });
  visibility.observe(host);
  document.addEventListener('visibilitychange', schedule);
  reducedMotion.addEventListener('change', schedule);

  function showAll(targets, focusId = null, focusRequested = false) {
    const ids = new Set(targets.map((target) => target.id));
    for (const [id, vehicle] of vehicles) {
      if (!ids.has(id)) {
        disposeVehicle(vehicle);
        vehicles.delete(id);
      }
    }
    let jumped = false;
    for (const target of targets) {
      const fresh = !vehicles.has(target.id);
      if (fresh) vehicles.set(target.id, createVehicle(target));
      const vehicle = vehicles.get(target.id);
      const { at, bus, ring } = vehicle;
      const colour = target.colour ?? '#2f7d8f';
      ring.material.color.set(colour);
      bus.ghostEdges.color.set(colour);
      vehicle.label.style.borderColor = colour;
      vehicle.label.textContent = target.name ?? `nUWAy ${target.id}`;
      const to = { lng: target.lng, lat: target.lat, heading: target.heading ?? 0 };
      const far = Math.hypot(to.lng - at.lng, to.lat - at.lat) > 0.002;
      jumped ||= far;
      if (fresh || far || reducedMotion.matches) {
        Object.assign(at, to);
        vehicle.glide = null;
        vehicle.marker.setLngLat([at.lng, at.lat]);
      } else {
        vehicle.glide = { from: { ...at }, to, start: performance.now() };
      }
    }
    map.getSource(TRAIL_SOURCE).setData({
      type: 'FeatureCollection',
      features: targets.filter((target) => target.trail?.length > 1).map((target) => ({
        type: 'Feature', properties: { colour: target.colour ?? '#2f7d8f' },
        geometry: { type: 'LineString', coordinates: target.trail },
      })),
    });
    shown = targets;
    const nextKey = JSON.stringify([...ids].sort());
    if (nextKey !== selectionKey) {
      // A new selection: one bus is followed, several are framed together.
      selectionKey = nextKey;
      focusedId = targets.length === 1 ? targets[0].id : null;
      framePending = true;
    } else if (jumped) {
      // A bus moved a long way, e.g. the period changed: reframe, staying
      // on the bus someone stepped to if there is one.
      framePending = true;
    }
    if (focusRequested) {
      // A step with the arrows: to a bus, or back to the whole fleet (null).
      // A lone bus is followed whichever is asked for.
      focusedId = vehicles.has(focusId) ? focusId : targets.length === 1 ? targets[0].id : null;
      framePending = true;
    }
    frameCamera();
    map.triggerRepaint();
    schedule();
  }

  // Put the camera on the followed bus, or fit the fleet, once the map has a
  // size to do it in. A bus keeps the zoom someone chose, except when coming
  // from the fleet's fit, which may be zoomed well out.
  function frameCamera() {
    if (!framePending || !host.clientWidth || !host.clientHeight) return;
    // The map may not have noticed it was just shown yet.
    map.resize();
    framePending = false;
    const followed = vehicles.get(focusedId);
    if (followed) {
      map.jumpTo({ center: [followed.at.lng, followed.at.lat], ...(fleetFramed ? { zoom: ZOOM } : {}) });
      fleetFramed = false;
    } else if (shown.length > 1) {
      const bounds = new maplibregl.LngLatBounds();
      for (const target of shown) {
        bounds.extend([target.lng, target.lat]);
        for (const point of target.trail ?? []) bounds.extend(point);
      }
      map.fitBounds(bounds, { padding: 70, maxZoom: ZOOM, duration: 0 });
      fleetFramed = true;
    }
  }

  schedule();

  return {
    showAll,
    setPaused(next) {
      paused = next;
      schedule();
    },
    // Resolves once everything in view has loaded and been drawn: the tiles,
    // and the fonts for their labels. MapLibre says so with `idle`, which only
    // comes while the camera is still, so call it paused. Gives up after
    // `timeoutMs` rather than wait on a slow tile server for ever.
    whenReady(timeoutMs = 20000) {
      return new Promise((resolve) => {
        if (map.loaded() && map.areTilesLoaded()) {
          resolve();
          return;
        }
        const timer = setTimeout(resolve, timeoutMs);
        map.once('idle', () => {
          clearTimeout(timer);
          resolve();
        });
      });
    },
    setSpin(on) {
      spin = on;
      schedule();
    },
    // The container changed size, e.g. the view was just revealed.
    resize() {
      map.resize();
      frameCamera();
    },
    destroy() {
      if (frame !== null) cancelAnimationFrame(frame);
      visibility.disconnect();
      document.removeEventListener('visibilitychange', schedule);
      reducedMotion.removeEventListener('change', schedule);
      vehicles.forEach(disposeVehicle);
      vehicles.clear();
      map.remove();
    },
  };
}
