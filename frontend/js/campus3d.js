// 3D view of a bus on campus: the nUWAy CAD model, in its real livery, at its
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
 * @returns {Promise<{show: (bus: Object|null) => void, setSpin: (on: boolean) => void, destroy: () => void}>}
 *   `show` puts the camera on a bus: `{ colour, lng, lat, heading, trail }`,
 *   where `trail` is its recent track as [lng, lat] pairs, or null for a bus
 *   with no position, which leaves the camera on campus with no bus drawn.
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

  const bus = buildBus(modelData);
  const ring = buildRing();
  const scene = new THREE.Scene();
  scene.add(bus.solid, ring);
  // The X-ray, drawn first in a pass of its own (see buildBus).
  const ghostScene = new THREE.Scene();
  ghostScene.add(bus.ghost);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7378, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.position.set(-40, 80, 30);
  scene.add(sun);
  const camera = new THREE.Camera();
  let renderer = null;

  // Where the bus is drawn: its position, as a MercatorCoordinate, and its
  // heading in degrees clockwise from north. Moved by the glide below.
  const at = { lng: CAMPUS_CENTRE[0], lat: CAMPUS_CENTRE[1], heading: 0 };
  let visible = false;

  const layer = {
    id: MODEL_LAYER_ID,
    type: 'custom',
    renderingMode: '3d',
    onAdd(_map, gl) {
      renderer = new THREE.WebGLRenderer({ canvas: map.getCanvas(), context: gl, antialias: true });
      renderer.autoClear = false;
    },
    render(_gl, matrix) {
      if (!visible) return;
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
      camera.projectionMatrix = new THREE.Matrix4().fromArray(matrix).multiply(transform);
      renderer.resetState();
      renderer.render(ghostScene, camera);
      renderer.render(scene, camera);
    },
  };

  // ---- The trail ----

  const TRAIL_SOURCE = 'nuway-trail';
  const emptyTrail = { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} };

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
    paint: { 'line-color': '#2f7d8f', 'line-width': 6, 'line-opacity': 0.75 },
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
  let glide = null; // { from, to, start }

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

    if (glide) {
      const t = Math.min((time - glide.start) / GLIDE_MS, 1);
      const k = easeInOut(t);
      at.lng = glide.from.lng + (glide.to.lng - glide.from.lng) * k;
      at.lat = glide.from.lat + (glide.to.lat - glide.from.lat) * k;
      at.heading = turnTowards(glide.from.heading, glide.to.heading, k);
      if (t >= 1) glide = null;
      moving = true;
    }

    const orbiting = spin && time >= pausedUntil;
    const view = { center: [at.lng, at.lat] };
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
    if (!spin && !glide) {
      lastTime = null;
      return;
    }
    frame = requestAnimationFrame(step);
  }

  const visibility = new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    if (onScreen) map.resize();
    schedule();
  });
  visibility.observe(host);
  document.addEventListener('visibilitychange', schedule);
  reducedMotion.addEventListener('change', schedule);

  let shownKey = null;

  function show(target) {
    if (!target) {
      visible = false;
      map.getSource(TRAIL_SOURCE).setData(emptyTrail);
      map.triggerRepaint();
      shownKey = null;
      return;
    }

    ring.material.color.set(target.colour ?? '#2f7d8f');
    bus.ghostEdges.color.set(target.colour ?? '#2f7d8f');
    map.setPaintProperty('nuway-trail', 'line-color', target.colour ?? '#2f7d8f');
    map.getSource(TRAIL_SOURCE).setData({
      ...emptyTrail,
      geometry: { type: 'LineString', coordinates: target.trail ?? [] },
    });

    const to = { lng: target.lng, lat: target.lat, heading: target.heading ?? 0 };
    // A different bus is cut to; the same bus moving is glided along, unless
    // it has jumped further than a short drive, as when the period changes.
    const key = target.id;
    const far = Math.hypot(to.lng - at.lng, to.lat - at.lat) > 0.002; // ~200 m
    if (key !== shownKey || !visible || far || reducedMotion.matches) {
      Object.assign(at, to);
      glide = null;
      map.jumpTo({ center: [to.lng, to.lat] });
    } else {
      glide = { from: { ...at }, to, start: performance.now() };
    }
    shownKey = key;
    visible = true;
    map.triggerRepaint();
    schedule();
  }

  schedule();

  return {
    show,
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
    resize: () => map.resize(),
    destroy() {
      if (frame !== null) cancelAnimationFrame(frame);
      visibility.disconnect();
      document.removeEventListener('visibilitychange', schedule);
      reducedMotion.removeEventListener('change', schedule);
      map.remove();
    },
  };
}
