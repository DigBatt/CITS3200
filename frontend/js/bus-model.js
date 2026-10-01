// The nUWAy bus as three.js objects, shared by the two 3D views: the campus
// view (js/campus3d.js) and the Earth view (js/earth3d.js).
//
// The model is frontend/models/nuway.json, from the nuway-blueprint project:
// a photo-based visual approximation on the nominal Ligier EZ10 envelope, not
// measured CAD. Coordinates are metres, Y up, with the length along X and the
// wheels on Y = 0.

import * as THREE from 'three';

const MODEL_URL = new URL('../models/nuway.json', import.meta.url);

// The nUWAy livery, from the REV Project's photographs
// (therevproject.com/vehicles/nuway.php): a glossy white body over a black
// skirt, bumpers and wheel arches, black door frames, smoked glazing, silver
// hubcaps on black tyres, and black LiDAR housings. Decals are left off.
const LIVERY = [
  // [part name prefix, colour, roughness, metalness]
  ['cabin_shell', 0xf3f4f1, 0.32, 0.08],
  ['roof_sensor_base', 0xe9ebe8, 0.4, 0.05],
  ['sliding_door_frame', 0x16181a, 0.5, 0.2],
  ['door_upper_rail', 0x16181a, 0.5, 0.2],
  ['wheel_arch', 0x16181a, 0.6, 0.05],
  ['end_bumper', 0x16181a, 0.6, 0.05],
  ['floor', 0x1d2023, 0.7, 0.05],
  ['entry_step', 0x2a2d30, 0.7, 0.05],
  ['wheel_cap', 0xc5cacd, 0.3, 0.7],
  ['wheel_rim', 0xc5cacd, 0.3, 0.7],
  ['tyre', 0x151515, 0.9, 0.0],
  ['light', 0xf2ecd8, 0.2, 0.1],
  ['roof_lidar_pedestal', 0x1a1c1e, 0.6, 0.1],
  ['roof_equipment', 0x1f2224, 0.6, 0.1],
  ['door_request_button', 0x1f9c8c, 0.4, 0.1],
  ['roof_lidar', 0x101214, 0.4, 0.3],
  ['end_lidar', 0x101214, 0.4, 0.3],
  ['corner_lidar', 0x101214, 0.4, 0.3],
];
const GLAZING = { color: 0x1a2328, roughness: 0.12, metalness: 0.4 };
const FALLBACK = { color: 0x9aa3a8, roughness: 0.6, metalness: 0.1 };

function finishFor(part) {
  if (part.group === 'glazing') return GLAZING;
  const match = LIVERY.find(([prefix]) => part.name.startsWith(prefix));
  if (!match) return FALLBACK;
  const [, color, roughness, metalness] = match;
  return { color, roughness, metalness };
}

export async function loadModel() {
  const response = await fetch(MODEL_URL);
  if (!response.ok) throw new Error(`the bus model request returned ${response.status}`);
  return response.json();
}

// The bus as two three.js groups, in metres with Y up, sitting on Y = 0:
//   solid  the bus in its livery, hidden by whatever stands in front of it;
//   ghost  an X-ray of it in the vehicle's colour, drawn with no depth test,
//          so it shows through buildings.
// Drawn ghost first, then solid over it (see render below): where the bus is
// in plain view the solid covers the ghost, and where a building is in front
// only the ghost is left. The two share geometry.
export function buildBus(data) {
  const solid = new THREE.Group();
  const ghost = new THREE.Group();
  const ghostFill = new THREE.MeshBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.22, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
  });
  const ghostEdges = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthTest: false, depthWrite: false });

  for (const part of data.parts) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(part.positions, 3));
    geometry.setIndex(part.indices);
    geometry.computeVertexNormals();
    const finish = finishFor(part);
    solid.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      ...finish,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    })));

    // The CAD edges, faint, for crisp panel lines at a distance.
    const edges = new THREE.BufferGeometry();
    edges.setAttribute('position', new THREE.Float32BufferAttribute(part.edges, 3));
    solid.add(new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x0d1114, transparent: true, opacity: 0.35 })));

    // Glazing and small fittings add clutter to the X-ray without helping
    // anyone find the bus, so it is the shell, doors, wheels and roof kit.
    if (part.group !== 'glazing' && part.group !== 'details') {
      ghost.add(new THREE.Mesh(geometry, ghostFill));
      ghost.add(new THREE.LineSegments(edges, ghostEdges));
    }
  }
  return { solid, ghost, ghostFill, ghostEdges };
}

// A flat ring on the ground in the vehicle's dashboard colour, so it is clear
// which bus is which: the real ones all look alike.
export function buildRing() {
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(2.7, 3.15, 64),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, side: THREE.DoubleSide }),
  );
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.03;
  return ring;
}
