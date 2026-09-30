// Leaflet setup: map init, tile layer, and one layer group per overlay.
//
// Layer groups map one-to-one onto the overlays.
//
// Owns: vehicle markers, position trails, event markers, stop markers.

let map = null;
const layers = { trails: null, stops: null, route: null };

let pendingFit = null;


// Stops are drawn in their own pane, under the trails and vehicle markers.
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

// On the selected route: the route's own colour, filled and larger.
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

const ROUTE_FALLBACK_COLOUR = '#7c3aed';

// Set true while fine-tuning demo paths. Clicking the map then prints a YAML
// path point ready to paste into config/stops.yaml.
const ROUTE_POINT_DEBUG = false;

// The Leaflet style for one stop under the current selection. Kept free of
// Leaflet and of the DOM so it can be tested on its own.
function styleForStop(stop, selectedRouteId, routeColour) {
  if (!selectedRouteId) return { ...STOP_NEUTRAL };
  if (!stop.routes.includes(selectedRouteId)) return { ...STOP_OFF_ROUTE };
  return { ...STOP_ON_ROUTE, fillColor: routeColour ?? STOP_ON_ROUTE_FALLBACK_COLOUR };
}

function initMap() {
  map = L.map('map').setView([-31.98133, 115.81597], 16); // sets the initial to UWA campus
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  map.createPane('stops').style.zIndex = 350; // below overlayPane (400)
  map.createPane('routes').style.zIndex = 340; // route line sits behind stop markers
  stopRenderer = L.svg({ pane: 'stops' });

  layers.route = L.layerGroup().addTo(map);
  layers.stops = L.layerGroup().addTo(map);
  layers.trails = L.layerGroup().addTo(map);


  if (ROUTE_POINT_DEBUG) {
    map.on('click', (event) => {
      console.log(
        `  - { latitude: ${event.latlng.lat.toFixed(7)}, longitude: ${event.latlng.lng.toFixed(7)} }`
      );
    });
  }
}

// Draw the configured stops. They come from config and change only on a
// restart, so this is called once rather than on every live poll.
function drawStops(stops, { popupHtml = null } = {}) {
  layers.stops.clearLayers();
  stopMarkers.clear();

  for (const stop of stops) {
    const marker = L.circleMarker([stop.latitude, stop.longitude], {
      renderer: stopRenderer,
      pane: 'stops',
      ...STOP_NEUTRAL,
    })
      .bindTooltip(stop.name, {
        permanent: false,
        direction: 'top',
        offset: [0, -7],
        className: 'stop-label',
      })
      .addTo(layers.stops);

    if (popupHtml) marker.bindPopup(popupHtml(stop), { className: 'stop-popup', closeButton: false });

    stopMarkers.set(stop.id, marker);
  }

  return stops.length;
}

// Restyle the drawn stops for the selected route, or for none. Normal routes
// fade unrelated stops; demo routes can hide them completely. Labels appear
// only while the pointer is over a marker.
function setStopMarkerVisible(marker, visible) {
  marker.options.routeVisible = visible;
  const element = marker.getElement();
  if (!element) return;
  element.style.display = visible ? '' : 'none';
  element.style.pointerEvents = visible ? '' : 'none';
}

function highlightRoute(stops, selectedRouteId, routeColour, hideOtherStops = false) {
  for (const stop of stops) {
    const marker = stopMarkers.get(stop.id);
    if (!marker) continue;

    const onSelectedRoute = Boolean(selectedRouteId) && stop.routes.includes(selectedRouteId);
    const visible = !hideOtherStops || !selectedRouteId || onSelectedRoute;

    marker.setStyle(styleForStop(stop, selectedRouteId, routeColour));

    // Demo routes can request a clean map containing only their named
    // landmarks. Geometry-only path points never become markers at all.
    setStopMarkerVisible(marker, visible);
    if (!visible) marker.closeTooltip();
  }
}

// Show or hide the whole stop layer. The markers are kept, so turning it back
// on needs no refetch.
function setStopsVisible(visible) {
  if (visible) {
    layers.stops.addTo(map);
    for (const marker of stopMarkers.values()) {
      setStopMarkerVisible(marker, marker.options.routeVisible !== false);
    }
  } else {
    map.removeLayer(layers.stops);
  }
}

// Draw the selected configured route if it has map geometry. Routes without a
// path keep the existing stop-highlighting behaviour and simply draw no line.
function drawRoutePath(route, { fit = true } = {}) {
  layers.route.clearLayers();

  if (!route?.path || route.path.length < 2) return 0;

  const points = route.path.map((point) => [point.latitude, point.longitude]);
  const line = L.polyline(points, {
    pane: 'routes',
    color: route.colour ?? ROUTE_FALLBACK_COLOUR,
    weight: 5,
    opacity: 0.85,
    dashArray: '10 8',
    interactive: false,
  }).addTo(layers.route);

  if (fit) fitTo(line.getBounds());
  return points.length;
}

function drawTracks(vehicles, { fit = true } = {}) {
  layers.trails.clearLayers();
  if (fit) pendingFit = null;
  const bounds = L.latLngBounds([]);
  let drawn = 0;

  for (const vehicle of vehicles) {
    // A row with no fix carries no coordinates, so it cannot be plotted.
    const points = vehicle.positions
      .filter((p) => p.latitude !== null && p.longitude !== null)
      .map((p) => [p.latitude, p.longitude]);

    if (points.length === 0) continue;
    drawn += 1;

    const style = vehicle.colour ? { color: vehicle.colour } : {};
    // Not interactive: the trail carries no popup of its own, and it is drawn
    // over the stops, so a clickable trail would swallow clicks on a stop
    // underneath it.
    L.polyline(points, { weight: 3, interactive: false, ...style }).addTo(layers.trails);
    L.circleMarker(points[points.length - 1], { radius: 6, weight: 2, fillOpacity: 1, ...style })
      .bindPopup(`${vehicle.name ?? vehicle.vehicle_id} — ${vehicle.count} positions`)
      .addTo(layers.trails);

    bounds.extend(points);
  }

  if (drawn > 0 && fit) fitTo(bounds);
  return drawn;
}

// A hidden map measures 0x0, and fitting to that zooms all the way in, so a
// fit made while the map is hidden waits for showMap().
function fitTo(bounds) {
  if (map.getContainer().clientWidth === 0) {
    pendingFit = bounds;
    return;
  }
  pendingFit = null;
  map.fitBounds(bounds, { padding: [24, 24] });
}

// Call when the map becomes visible again: it re-measures the container,
// which may have been resized while hidden, then applies any waiting fit.
function showMap() {
  map.invalidateSize();
  if (pendingFit) fitTo(pendingFit);
}
