// Earth view: the bus on Google's photorealistic 3D tiles, so every building
// around it looks as it does in real life, with the camera slowly circling.
//
// The tiles are streamed by the 3d-tiles-renderer library into a three.js
// scene, re-centred on campus with +Y up (ReorientationPlugin), so the bus can
// be placed in metres like any other object. Its height starts at the fix's
// GPS altitude (height above the ellipsoid) and is then refined by probing
// the tiles straight down.
//
// Needs a Google Maps Platform API key with the Map Tiles API enabled, from
// /api/earth (backend/api/earth.py). Google's attribution must stay on screen
// while its tiles are shown; this view draws it.
//
// Shares the bus, its livery and its X-ray with the campus view
// (js/bus-model.js). An ES module, imported by js/view3d.js the first time
// someone turns Earth on; three.js, its add-ons and 3d-tiles-renderer come
// from the import map in index.html.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { TilesRenderer } from '3d-tiles-renderer/three';
import { GoogleCloudAuthPlugin } from '3d-tiles-renderer/core/plugins';
import { GLTFExtensionsPlugin } from '3d-tiles-renderer/src/three/plugins/GLTFExtensionsPlugin.js';
import { ReorientationPlugin } from '3d-tiles-renderer/src/three/plugins/ReorientationPlugin.js';
import { buildBus, buildRing, loadModel } from './bus-model.js';

const CAMPUS = { lat: -31.98133, lng: 115.81597 }; // as js/map.js
const DRACO_DECODERS = 'https://www.gstatic.com/draco/versioned/decoders/1.5.7/';
// One full circle about every 50 seconds, as the campus view.
const ORBIT_SECONDS = 50;
const ORBIT_RESUME_MS = 4000;
const GLIDE_MS = 1200;
// Where the camera starts relative to the bus: back and up. High enough, at
// about 54 m, to circle over the campus rooftops and trees rather than
// through them.
const START_DISTANCE = 70;
const START_ELEVATION = THREE.MathUtils.degToRad(50);
// How often to probe the tiles for the ground under the bus, while the tiles
// there are still sharpening.
const GROUND_PROBE_MS = 400;
// A probe further than this from the GPS altitude is not the ground. The
// first tiles in are a coarse globe whose flat faces cut far below the real
// surface, 150 m and more at UWA; taking one of those as the ground once put
// the camera underground, where it saw nothing and nothing more loaded.
const GROUND_TOLERANCE_M = 40;
// The camera keeps at least this far above the bus it is looking at.
const MIN_CAMERA_HEIGHT_M = 6;

const rad = THREE.MathUtils.degToRad;

/**
 * Mount the Earth view into `host`.
 *
 * @param {HTMLElement} host - Sized by CSS; the canvas fills it.
 * @param {Object} options
 * @param {string} options.apiKey - Google Maps Platform key (Map Tiles API).
 * @param {(message: string) => void} [options.onStatus]
 * @param {boolean} [options.spin=true]
 * @returns {Promise<{show: Function, setSpin: Function, resize: Function, destroy: Function}>}
 *   The same interface as js/campus3d.js.
 */
export async function mount(host, { apiKey, onStatus = () => {}, spin: spinAtStart = true } = {}) {
  onStatus('Loading the Earth view…');
  const modelData = await loadModel().catch((error) => {
    onStatus(`Could not load the bus model: ${error.message}.`);
    throw error;
  });

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (error) {
    onStatus('The Earth view needs WebGL, which this browser has turned off.');
    throw error;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.autoClear = false;
  renderer.setClearColor(0xcfe2ef); // sky, until anything is drawn over it
  host.appendChild(renderer.domElement);

  const attribution = document.createElement('p');
  attribution.className = 'earth3d-attribution';
  host.appendChild(attribution);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 30000);

  // ---- The tiles ----

  const tilesScene = new THREE.Scene();
  const dracoLoader = new DRACOLoader().setDecoderPath(DRACO_DECODERS);
  const tiles = new TilesRenderer();
  tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: apiKey, autoRefreshToken: true }));
  tiles.registerPlugin(new GLTFExtensionsPlugin({ dracoLoader }));
  // Campus at the origin, the local up along +Y, so metres work as metres.
  tiles.registerPlugin(new ReorientationPlugin({ lat: rad(CAMPUS.lat), lon: rad(CAMPUS.lng), height: 0, recenter: true }));
  tiles.setCamera(camera);
  tilesScene.add(tiles.group);

  let loadFailed = false;
  tiles.addEventListener('load-error', ({ error }) => {
    if (loadFailed) return;
    loadFailed = true;
    console.error('Earth view:', error);
    onStatus('Google’s 3D tiles did not load. Check the API key has the Map Tiles API enabled, and is allowed for this site.');
  });

  // A lat/lng as a point in the scene. Valid once the root tileset is in and
  // the re-centring has been applied to the tiles' group.
  const scratch = new THREE.Vector3();
  function toLocal(lat, lng, height = 0, target = new THREE.Vector3()) {
    tiles.ellipsoid.getCartographicToPosition(rad(lat), rad(lng), height, scratch);
    tiles.group.updateMatrixWorld();
    return target.copy(scratch).applyMatrix4(tiles.group.matrixWorld);
  }

  // ---- The bus ----

  const bus = buildBus(modelData);
  const ring = buildRing();
  const busScene = new THREE.Scene();
  const ghostScene = new THREE.Scene();
  const busGroup = new THREE.Group();
  busGroup.add(bus.solid, ring);
  const ghostGroup = new THREE.Group();
  ghostGroup.add(bus.ghost);
  busScene.add(busGroup, new THREE.HemisphereLight(0xffffff, 0x6b7378, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.position.set(-40, 80, 30);
  busScene.add(sun);
  ghostScene.add(ghostGroup);

  // Where the bus is, and where it is heading (degrees clockwise from north).
  const at = { lat: CAMPUS.lat, lng: CAMPUS.lng, heading: 0, altitude: null };
  let ground = null; // metres, the ground's height at the bus, once probed
  let lastProbe = 0;
  let visible = false;
  let glide = null;
  let shownKey = null;
  const raycaster = new THREE.Raycaster();
  raycaster.firstHitOnly = true;

  // Put the bus at its position, on the ground, turned along its heading.
  // Returns where that is, for the camera to follow.
  const busAt = new THREE.Vector3();
  function placeBus(time) {
    toLocal(at.lat, at.lng, 0, busAt);
    // Where GPS puts the ground, as a first answer and a sanity check.
    const gps = at.altitude != null ? toLocal(at.lat, at.lng, at.altitude).y : null;

    // The ground: probe straight down through the tiles, again every so
    // often, since the first tiles in are coarse and sharpen as they load.
    if (time - lastProbe > GROUND_PROBE_MS) {
      lastProbe = time;
      raycaster.set(new THREE.Vector3(busAt.x, busAt.y + 1000, busAt.z), new THREE.Vector3(0, -1, 0));
      const [hit] = raycaster.intersectObject(tiles.group, true);
      if (hit && (gps === null || Math.abs(hit.point.y - gps) < GROUND_TOLERANCE_M)) ground = hit.point.y;
    }
    busAt.y = ground ?? gps ?? busAt.y;

    // Heading: north and east here, in scene terms, then the model's length
    // (+X) laid along heading's direction between them.
    const north = toLocal(at.lat + 1e-5, at.lng).sub(toLocal(at.lat, at.lng)).setY(0).normalize();
    const east = toLocal(at.lat, at.lng + 1e-5).sub(toLocal(at.lat, at.lng)).setY(0).normalize();
    const h = rad(at.heading);
    const direction = north.multiplyScalar(Math.cos(h)).add(east.multiplyScalar(Math.sin(h)));
    const turn = Math.atan2(-direction.z, direction.x);

    for (const group of [busGroup, ghostGroup]) {
      group.position.copy(busAt);
      group.rotation.set(0, turn, 0);
      group.visible = visible && (ground !== null || gps !== null);
    }
    return busAt;
  }

  // ---- The camera ----

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 8;
  controls.maxDistance = 600;
  controls.maxPolarAngle = rad(86);
  controls.autoRotateSpeed = 60 / ORBIT_SECONDS; // OrbitControls: 1 = a turn a minute
  let spin = spinAtStart;
  let resumeTimer = null;
  controls.autoRotate = spin;
  // Someone moving the view takes over from the orbit for a while.
  controls.addEventListener('start', () => {
    clearTimeout(resumeTimer);
    controls.autoRotate = false;
  });
  controls.addEventListener('end', () => {
    clearTimeout(resumeTimer);
    resumeTimer = setTimeout(() => { controls.autoRotate = spin; }, ORBIT_RESUME_MS);
  });

  function aimAt(point) {
    controls.target.copy(point);
    camera.position.copy(point).add(new THREE.Vector3(
      0,
      START_DISTANCE * Math.sin(START_ELEVATION),
      START_DISTANCE * Math.cos(START_ELEVATION),
    ));
    controls.update();
  }

  // ---- Sizing and drawing ----

  function resize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) return;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
    tiles.setResolutionFromRenderer(camera, renderer);
  }
  const sizing = new ResizeObserver(resize);
  sizing.observe(host);
  resize();

  let lastAttribution = '';
  function drawAttribution() {
    const lines = (tiles.getAttributions?.() ?? [])
      .filter((entry) => entry.type === 'string')
      .map((entry) => entry.value);
    // Google's own name first, whether or not the tiles also list it.
    const text = [...new Set(['Google', ...lines])].join(' · ');
    if (text !== lastAttribution) {
      attribution.textContent = text;
      lastAttribution = text;
    }
  }

  const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
  const turnTowards = (from, to, t) => from + (((to - from + 540) % 360) - 180) * t;

  const clock = new THREE.Clock();
  let aimed = false;
  const followFrom = new THREE.Vector3();

  function frame(time) {
    const delta = Math.min(clock.getDelta(), 0.1);

    if (glide) {
      const t = Math.min((time - glide.start) / GLIDE_MS, 1);
      const k = easeInOut(t);
      at.lat = glide.from.lat + (glide.to.lat - glide.from.lat) * k;
      at.lng = glide.from.lng + (glide.to.lng - glide.from.lng) * k;
      at.heading = turnTowards(glide.from.heading, glide.to.heading, k);
      at.altitude = glide.to.altitude;
      if (t >= 1) glide = null;
    }

    // Until the root tileset is in, there is no frame to place anything in.
    if (tiles.root) {
      followFrom.copy(busAt);
      const point = placeBus(time);
      if (!aimed) {
        aimAt(point);
        aimed = true;
      } else {
        // Carry the camera along with the bus, so a moving bus stays framed
        // at the same distance and angle. Up and down, only a small step is
        // the bus driving over a slope; a big one is the ground estimate
        // being corrected, which moves where the camera looks, not the camera.
        const shift = point.clone().sub(followFrom);
        if (Math.abs(shift.y) > 2) {
          controls.target.y += shift.y;
          shift.y = 0;
        }
        controls.target.add(shift);
        camera.position.add(shift);
      }
      // Never below the bus it is looking at, let alone under the ground.
      camera.position.y = Math.max(camera.position.y, controls.target.y + MIN_CAMERA_HEIGHT_M);
    }

    controls.update(delta);
    camera.updateMatrixWorld();
    tiles.update();

    renderer.clear();
    renderer.render(tilesScene, camera);
    // The X-ray, then the solid bus over it (see js/bus-model.js).
    renderer.render(ghostScene, camera);
    renderer.render(busScene, camera);
    drawAttribution();

    // Loaded once there is something of the world on screen.
    if (tiles.visibleTiles.size > 0 && !loadFailed) onStatus('');
  }

  // Draw only while there is someone to see it. Unlike the campus view this
  // must keep drawing while still, since the tiles stream in over time.
  let onScreen = true;
  function sync() {
    renderer.setAnimationLoop(onScreen && !document.hidden ? frame : null);
    if (onScreen) clock.getDelta();
  }
  const visibility = new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    if (onScreen) resize();
    sync();
  });
  visibility.observe(host);
  document.addEventListener('visibilitychange', sync);
  sync();

  // ---- The interface js/view3d.js drives, as js/campus3d.js ----

  function show(target) {
    if (!target) {
      visible = false;
      shownKey = null;
      return;
    }
    ring.material.color.set(target.colour ?? '#2f7d8f');
    bus.ghostEdges.color.set(target.colour ?? '#2f7d8f');

    const to = { lat: target.lat, lng: target.lng, heading: target.heading ?? 0, altitude: target.altitude ?? null };
    const far = Math.hypot(to.lng - at.lng, to.lat - at.lat) > 0.002; // ~200 m
    if (target.id !== shownKey || !visible || far) {
      // A different bus, or a long jump: cut to it, and find its ground anew.
      Object.assign(at, to);
      glide = null;
      ground = null;
      lastProbe = 0;
      aimed = false;
    } else {
      glide = { from: { ...at }, to, start: performance.now() };
    }
    shownKey = target.id;
    visible = true;
  }

  return {
    show,
    setSpin(on) {
      spin = on;
      clearTimeout(resumeTimer);
      controls.autoRotate = on;
    },
    resize,
    destroy() {
      renderer.setAnimationLoop(null);
      visibility.disconnect();
      sizing.disconnect();
      document.removeEventListener('visibilitychange', sync);
      clearTimeout(resumeTimer);
      controls.dispose();
      tiles.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      attribution.remove();
    },
  };
}
