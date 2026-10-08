// Leaflet setup: map init, tile layer, and one layer group per overlay.
//
// Layer groups map one-to-one onto the overlays.
//
// Owns: vehicle markers, position trails, event markers, stop markers.

let map = null;
const layers = { trails: null, stops: null, routes: null };

let pendingFit = null;

// Pin the map to one area, overriding the normal "fit to every visible
// vehicle" framing (fitTo() below, via drawTracks()) -- used by the Rider
// tab, which always frames the campus (js/panels.js), and the Area chips
// (js/area.js), e.g. for Eglinton, where nUWAy 2 runs far from the rest of
// the fleet. A function, not a snapshot of bounds, so a pin made before its
// extent is known or before it changes (the campus's, see setCampusBounds()
// below) still resolves to the right thing later.
let pinnedBoundsFn = null;

// The fleet's actual extent, kept up to date by every drawTracks() call
// regardless of fit/pin state (below). What unpinMap() snaps straight back
// to, rather than leaving the map wherever the pin last left it until some
// unrelated later poll happens to trigger a fit.
let lastVehicleBounds = null;

function pinMapTo(boundsFn) {
  pinnedBoundsFn = boundsFn;
  const bounds = boundsFn();
  if (bounds) fitTo(bounds);
}

function unpinMap() {
  pinnedBoundsFn = null;
  if (lastVehicleBounds) fitTo(lastVehicleBounds);
}

// The configured stops' extent (js/stops.js:init()), what the Rider tab and
// the Area chips' "UWA Campus" option both pin to.
let campusBounds = null;

function getCampusBounds() {
  return campusBounds;
}

// Bus markers: a numbered circle, in px. Kept in step with .bus-marker in
// css/dashboard.css.
const BUS_MARKER_SIZE = 28;
const BUS_MARKER_FALLBACK_COLOUR = 'rgba(28, 25, 23, 0.8)';

// Stops are drawn in their own pane, over the trails and under the
// vehicle markers.
let stopRenderer = null;

// Kept so selecting a route restyles the markers in place. Redrawing the
// layer instead would rebuild every tooltip on each click.
const stopMarkers = new Map(); // stop id -> circleMarker

// No route selected: every stop reads the same.
const STOP_NEUTRAL = {
  radius: 5,
  weight: 2,
  color: 'rgba(28, 25, 23, 0.55)',
  fillColor: '#ffffff',
  fillOpacity: 1,
};

// On the selected route: the route's own colour, filled and larger, with a
// white outline. Any rings around it (applyStopStyle) are the buses.
const STOP_ON_ROUTE = { radius: 7, weight: 2, color: '#ffffff', fillOpacity: 1 };
const STOP_ON_ROUTE_FALLBACK_COLOUR = 'rgba(28, 25, 23, 0.8)';

// Off it: present, but plainly secondary.
const STOP_OFF_ROUTE = {
  radius: 4,
  weight: 1.5,
  color: 'rgba(28, 25, 23, 0.3)',
  fillColor: '#ffffff',
  fillOpacity: 0.65,
};

// The Leaflet style for one stop under the current selection. Kept free of
// Leaflet and of the DOM so it can be tested on its own.
function styleForStop(stop, selectedRouteId, routeColour) {
  if (!selectedRouteId) return { ...STOP_NEUTRAL };
  if (!stop.routes.includes(selectedRouteId)) return { ...STOP_OFF_ROUTE };
  return { ...STOP_ON_ROUTE, fillColor: routeColour ?? STOP_ON_ROUTE_FALLBACK_COLOUR };
}

// A stop a bus passed within this many metres of, in the period shown, gets
// a ring in that bus's colour around its own outline: the trail runs on
// through the stop, and the stop reads as part of it. Each bus that came by
// adds its own ring, further out, in the order the vehicle list has them.
const STOP_VISIT_RADIUS_M = 25;
const STOP_VISIT_RING_PX = 2.5;

// What the stops are drawn with now, so a new set of trails and a new route
// selection can each restyle them without losing the other.
const stopsById = new Map(); // stop id -> stop
const stopRings = new Map(); // stop id -> its rings' circleMarkers
let ringRenderer = null;
let routeSelection = { id: null, colour: null };
let stopVisitColours = new Map(); // stop id -> the colours of the buses that came by

function applyStopStyle(stop) {
  const marker = stopMarkers.get(stop.id);
  if (!marker) return;
  const style = styleForStop(stop, routeSelection.id, routeSelection.colour);
  marker.setStyle(style);

  // Each ring is a filled disc under the stop; the outermost is added first,
  // so each one inside it paints over all but its edge.
  stopRings.get(stop.id)?.forEach((ring) => ring.remove());
  stopRings.delete(stop.id);
  // Shown with or without a route selected: on a route they say which of its
  // stops a bus actually reached. A stop faded off the route has faded rings.
  // They are part of the trails, so they fade with them (setRouteFocus).
  const colours = stopVisitColours.get(stop.id) ?? [];
  if (colours.length === 0) return;
  const fillOpacity = style.fillOpacity < 1 ? 0.5 : 1;

  const base = style.radius + style.weight / 2;
  const rings = colours.map((colour, i) => L.circleMarker([stop.latitude, stop.longitude], {
    renderer: ringRenderer,
    pane: 'stopRings',
    stroke: false,
    interactive: false,
    radius: base + (i + 1) * STOP_VISIT_RING_PX,
    fillColor: colour,
    fillOpacity,
  }));
  // Added to the stop layer so the Stops toggle hides them with the stop.
  [...rings].reverse().forEach((ring) => ring.addTo(layers.stops));
  stopRings.set(stop.id, rings);
}

// For each stop, the colours of the buses that came within
// STOP_VISIT_RADIUS_M of it, one each, in the vehicle list's order.
function stopVisits(vehicles) {
  const visits = new Map(); // stop id -> [colour]
  for (const vehicle of vehicles) {
    if (!vehicle.colour) continue;
    const fixes = vehicle.positions.filter((p) => p.latitude !== null && p.longitude !== null);
    for (const stop of stopsById.values()) {
      const near = fixes.some((p) => L.latLng(p.latitude, p.longitude).distanceTo([stop.latitude, stop.longitude]) <= STOP_VISIT_RADIUS_M);
      if (!near) continue;
      if (!visits.has(stop.id)) visits.set(stop.id, []);
      visits.get(stop.id).push(vehicle.colour);
    }
  }
  return visits;
}

function initMap() {
  map = L.map('map').setView([-31.98133, 115.81597], 16); // sets the initial to UWA campus
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  // Bottom to top: the GPS trails, the selected route's line, the stops'
  // rings, the stops. The Focus on routes and stops switch (setRouteFocus) fades the
  // trails and rings and fades the route line in, pane by pane, so whatever
  // is drawn later follows the switch.
  map.createPane('trails').style.zIndex = 335;
  map.createPane('routes').style.zIndex = 340;
  map.createPane('stops').style.zIndex = 350; // below overlayPane (400)
  stopRenderer = L.svg({ pane: 'stops' });
  map.createPane('stopRings').style.zIndex = 345; // just under the stops
  ringRenderer = L.svg({ pane: 'stopRings' });
  for (const name of FADING_PANES) map.getPane(name).style.transition = 'opacity 200ms';
  setRouteFocus(false);

  // The bus markers sit above the stop labels (tooltipPane, 650), so a bus
  // waiting at a stop is not hidden under its name. Popups (700) stay on top.
  map.createPane('buses').style.zIndex = 660;

  layers.routes = L.layerGroup().addTo(map);
  layers.stops = L.layerGroup().addTo(map);
  layers.trails = L.layerGroup().addTo(map);

}

// Draw the configured stops. They come from config and change only on a
// restart, so this is called once rather than on every live poll.
function drawStops(stops, { popupHtml = null } = {}) {
  layers.stops.clearLayers();
  stopMarkers.clear();
  stopsById.clear();
  stopRings.clear(); // their layers went with clearLayers() above

  for (const stop of stops) {
    stopsById.set(stop.id, stop);
    // Text content keeps configured names safe and shows them only on hover.
    const label = document.createElement('span');
    label.textContent = stop.name || stop.id;
    const marker = L.circleMarker([stop.latitude, stop.longitude], {
      renderer: stopRenderer,
      pane: 'stops',
      ...STOP_NEUTRAL,
    })
      .bindTooltip(label, {
        permanent: false,
        direction: 'top',
        offset: [0, -7],
        className: 'stop-label',
      })
      .addTo(layers.stops);

    if (popupHtml) marker.bindPopup(popupHtml(stop), { className: 'stop-popup', closeButton: false });

    stopMarkers.set(stop.id, marker);
    applyStopStyle(stop); // trails drawn before the stops arrived still ring them
  }

  return stops.length;
}

// Restyle the drawn stops for the selected route, or for none. The stops a
// route serves stay full strength; the rest fade, labels included.
function highlightRoute(stops, selectedRouteId, routeColour) {
  routeSelection = { id: selectedRouteId, colour: routeColour };
  for (const stop of stops) {
    const marker = stopMarkers.get(stop.id);
    if (!marker) continue;

    applyStopStyle(stop);

    // Null while the layer is hidden by the Stops toggle, since a tooltip has
    // no element until it is on the map.
    const label = marker.getTooltip()?.getElement();
    label?.classList.toggle('is-dimmed', Boolean(selectedRouteId) && !stop.routes.includes(selectedRouteId));
  }
}

// A route's path as runs drawn once each. A route that goes out along a spur
// and back passes the same stretch twice; drawn twice, the casing of the
// second pass would cut across the line of the first.
function uniqueRuns(path) {
  const seen = new Set();
  const key = (a, b) => [a, b].map(p => p.join(',')).sort().join('|');
  const runs = [];
  let run = null;
  for (let i = 1; i < path.length; i++) {
    const k = key(path[i - 1], path[i]);
    if (seen.has(k)) { run = null; continue; }
    seen.add(k);
    if (!run) { run = [path[i - 1]]; runs.push(run); }
    run.push(path[i]);
  }
  return runs;
}

// Draw only the selected planned route, over the GPS trails and below the
// stop markers. Its path comes from /api/routes, set in config/stops.json by
// the admin page's route editor. It is seen only with the Focus on routes and stops
// switch on (setRouteFocus); with the trails at full strength, the
// route's filled stops (highlightRoute above) show it on their own.
//
// A solid line in the route's colour over a wider white one, the casing,
// which lifts it off the basemap and the faded trails. All the casing goes
// down first, so one run's casing never cuts across another's line.
const ROUTE_CASING = { color: '#ffffff', weight: 8, opacity: 1 };
const ROUTE_LINE = { weight: 5, opacity: 1 };

let routeDrawnBefore = false;

function drawRoutePath(route) {
  layers.routes.clearLayers();
  const runs = uniqueRuns(route?.path ?? []);
  const common = { pane: 'routes', lineCap: 'round', lineJoin: 'round', smoothFactor: 0, interactive: false };
  for (const points of runs) {
    L.polyline(points, { ...common, ...ROUTE_CASING, className: 'planned-route-casing' }).addTo(layers.routes);
  }
  for (const points of runs) {
    L.polyline(points, {
      ...common,
      ...ROUTE_LINE,
      color: route.colour ?? '#D4741F',
      className: 'planned-route-path',
    }).addTo(layers.routes);
  }
  fitToRoute(route);
}

// Picking a route frames the whole of it; going back to all routes frames
// the fleet again. Not on the first draw, at page load, where the fleet's own
// fit is already under way. A pinned map (the Rider tab, an Area chip) stays
// on its pin: fitTo() frames the pin whatever it is passed.
function fitToRoute(route) {
  const first = !routeDrawnBefore;
  routeDrawnBefore = true;
  if (first || !map) return;
  const path = route?.path ?? [];
  if (path.length > 1) fitTo(L.latLngBounds(path));
  else if (!route && lastVehicleBounds) fitTo(lastVehicleBounds);
}

// Rider stop picker (S15): fully hide every stop marker and label but one, to
// cut clutter while choosing. Pass null to show them all again — done
// whenever the rider leaves the picker (map.js is shared with Fleet, so this
// must not leak into its view of the map; js/rider.js and js/panels.js are
// what keep it scoped to the Rider tab).
function isolateStop(stopId) {
  for (const [id, marker] of stopMarkers) {
    const hide = stopId !== null && id !== stopId;
    marker.getElement()?.classList.toggle('is-hidden-stop', hide);
    marker.getTooltip()?.getElement()?.classList.toggle('is-hidden-stop', hide);
    stopRings.get(id)?.forEach((ring) => ring.getElement()?.classList.toggle('is-hidden-stop', hide));
  }
}

// Open a stop's existing popup (bound in Stops.init(), stops.js) so the rider
// picker confirms which stop was chosen (S15) — the same popup every other
// view already gets by clicking the marker directly. Leaflet auto-pans it
// into view, and closes whatever popup was open before.
function openStopPopup(stopId) {
  stopMarkers.get(stopId)?.openPopup();
}

// The Focus on routes and stops switch. Off: the trails and the stops' rings at full
// strength, and no route line. On: the trails and rings faded, still there
// for context, and the selected route's line shown over them. The buses and
// stops stay at full strength either way.
//
// Only the panes' opacity changes, never a line's own style, so turning the
// switch off restores exactly what was drawn, and trails, rings and routes
// drawn later (a new filter, a live poll) follow the switch as it is.
const FADING_PANES = ['trails', 'stopRings', 'routes'];
const TRAIL_FADED_OPACITY = 0.65; // faded, but still easy to follow

function setRouteFocus(focused) {
  if (!map) return;
  map.getPane('trails').style.opacity = focused ? String(TRAIL_FADED_OPACITY) : '';
  map.getPane('stopRings').style.opacity = focused ? String(TRAIL_FADED_OPACITY) : '';
  map.getPane('routes').style.opacity = focused ? '' : '0';
}

// The bus's latest position in the period: its number in a circle of its
// colour, so each bus on the map can be told apart without the legend.
// PREVIEW (not committed): a small bus, drawn here rather than REV's own
// artwork, filled with the vehicle's colour, its number in a badge. The badge
// is still the span in the bus's colour that tests/test_bus_markers.py reads.
const BUS_ICON_SIZE = 34;

function busIcon(vehicle) {
  const colour = escapeHtml(vehicle.colour ?? BUS_MARKER_FALLBACK_COLOUR);
  return L.divIcon({
    className: 'bus-marker',
    // No whitespace around the parts: the marker's text must be just its number.
    html: [
      `<svg viewBox="0 0 34 34" width="${BUS_ICON_SIZE}" height="${BUS_ICON_SIZE}" aria-hidden="true"`,
      ` style="display: block; filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.35))">`,
      `<rect x="6" y="3" width="22" height="25" rx="5" fill="${colour}" stroke="#fff" stroke-width="2"/>`,
      '<rect x="9" y="6.5" width="16" height="8" rx="1.5" fill="#fff" opacity="0.92"/>',
      '<rect x="9" y="17" width="4" height="2.5" rx="1" fill="#fff" opacity="0.85"/>',
      '<rect x="21" y="17" width="4" height="2.5" rx="1" fill="#fff" opacity="0.85"/>',
      '<rect x="8" y="27" width="5" height="4" rx="1.5" fill="#333"/>',
      '<rect x="21" y="27" width="5" height="4" rx="1.5" fill="#333"/>',
      '</svg>',
      `<span style="background: ${colour}; position: absolute; right: -6px; top: -6px; width: 17px; height: 17px;`,
      ` font: 700 10px/1 Sora, sans-serif">${escapeHtml(vehicle.vehicle_id)}</span>`,
    ].join(''),
    iconSize: [BUS_ICON_SIZE, BUS_ICON_SIZE],
    iconAnchor: [BUS_ICON_SIZE / 2, BUS_ICON_SIZE / 2], // centred on the position
  });
}


// A bus that went quiet and came back was not on a straight line between the
// two fixes, so its trail is broken there rather than joined: `fixes`
// (ascending by timestamp) cut wherever two neighbours are more than
// `gapSeconds` apart. With no threshold it is one unbroken run.
function splitAtGaps(fixes, gapSeconds) {
  const runs = [];
  let previous = null;
  for (const fix of fixes) {
    const time = Date.parse(fix.timestamp);
    if (previous === null || (gapSeconds != null && time - previous > gapSeconds * 1000)) runs.push([]);
    runs[runs.length - 1].push(fix);
    previous = time;
  }
  return runs;
}

// `gapSeconds` is the server's inactivity threshold: a silence longer than
// that breaks the trail (splitAtGaps above).
function drawTracks(vehicles, { fit = true, gapSeconds = null } = {}) {
  layers.trails.clearLayers();
  if (fit) pendingFit = null;
  const bounds = L.latLngBounds([]);
  let drawn = 0;

  for (const vehicle of vehicles) {
    // A row with no fix carries no coordinates, so it cannot be plotted.
    const fixes = vehicle.positions.filter((p) => p.latitude !== null && p.longitude !== null);
    if (fixes.length === 0) continue;

    // One line per unbroken run of reporting.
    const runs = splitAtGaps(fixes, gapSeconds).map((run) => run.map((p) => [p.latitude, p.longitude]));
    const points = runs.flat();
    drawn += 1;

    const style = vehicle.colour ? { color: vehicle.colour } : {};
    // Not interactive: the trail carries no popup of its own, so it must not
    // catch clicks meant for the map or a stop near it.
    L.polyline(runs, { pane: 'trails', weight: 3, interactive: false, ...style }).addTo(layers.trails);
    L.marker(points[points.length - 1], { icon: busIcon(vehicle), pane: 'buses', keyboard: false })
      .bindPopup(`${vehicle.name ?? vehicle.vehicle_id} — ${vehicle.count} positions`)
      .addTo(layers.trails);

    bounds.extend(points);
  }

  // Ring each stop once for every bus that came by it.
  stopVisitColours = stopVisits(vehicles);
  stopsById.forEach(applyStopStyle);

  // Only while nothing is pinned: a pinned view (Rider, or an Area chip) can
  // be showing an entirely different vehicle/date selection underneath (the
  // Rider tab forces "today", unrelated to whatever Fleet had), and that
  // must not overwrite what unpinMap() below snaps back to once the pin
  // comes off.
  if (bounds.isValid() && !pinnedBoundsFn) lastVehicleBounds = bounds;

  if (drawn > 0 && fit) fitTo(bounds);
  return drawn;
}

// A hidden map measures 0x0, and fitting to that zooms all the way in, so a
// fit made while the map is hidden waits for showMap().
//
// While something is pinned, this ignores whatever bounds the caller passed
// (the fleet's actual positions) and frames the pin instead -- the single
// choke point every fit (live poll, selection change, tab switch) goes
// through, so the override can't be missed from some other call site.
function fitTo(bounds) {
  const target = pinnedBoundsFn?.() ?? bounds;
  if (map.getContainer().clientWidth === 0) {
    pendingFit = target;
    return;
  }
  pendingFit = null;
  map.fitBounds(target, { padding: [24, 24] });
}

// Recomputed whenever the stop list loads (js/stops.js:init()). If the map
// is currently pinned to the campus -- the Rider tab, or the Area chips'
// "UWA Campus" (both pin the same getCampusBounds function, by reference) --
// frames it immediately rather than waiting for the next unrelated fit.
function setCampusBounds(stops) {
  campusBounds = stops.length ? L.latLngBounds(stops.map((stop) => [stop.latitude, stop.longitude])) : null;
  if (pinnedBoundsFn === getCampusBounds && campusBounds) fitTo(campusBounds);
}

// Call when the map becomes visible again: it re-measures the container,
// which may have been resized while hidden, then applies any waiting fit.
function showMap() {
  map.invalidateSize();
  if (pendingFit) fitTo(pendingFit);
}
