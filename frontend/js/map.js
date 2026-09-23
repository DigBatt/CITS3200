// Leaflet setup: map init, tile layer, and one layer group per overlay.
//
// Layer groups map one-to-one onto the overlays.
//
// Owns: vehicle markers, position trails, event markers, stop markers.

let map = null;
const layers = { trails: null, stops: null };

let pendingFit = null;

// Every stop label drawn at once is unreadable when zoomed out past the
// campus, so below this the names are hidden and the markers stay.
const STOP_LABEL_MIN_ZOOM = 15;

// Stops are drawn in their own pane, under the trails and vehicle markers.
let stopRenderer = null;

function initMap() {
  map = L.map('map').setView([-31.98133, 115.81597], 16); // sets the initial to UWA campus
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  map.createPane('stops').style.zIndex = 350; // below overlayPane (400)
  stopRenderer = L.svg({ pane: 'stops' });

  layers.stops = L.layerGroup().addTo(map);
  layers.trails = L.layerGroup().addTo(map);

  map.on('zoomend', applyStopLabelZoom);
  applyStopLabelZoom();
}

// Draw the configured stops. They come from config and change only on a
// restart, so this is called once rather than on every live poll.
function drawStops(stops) {
  layers.stops.clearLayers();

  for (const stop of stops) {
    L.circleMarker([stop.latitude, stop.longitude], {
      renderer: stopRenderer,
      pane: 'stops',
      radius: 5,
      weight: 2,
      color: 'rgba(28, 25, 23, 0.55)',
      fillColor: '#ffffff',
      fillOpacity: 1,
    })
      .bindTooltip(stop.name, {
        permanent: true,
        direction: 'top',
        offset: [0, -7],
        className: 'stop-label',
      })
      .addTo(layers.stops);
  }

  return stops.length;
}

function applyStopLabelZoom() {
  map.getContainer().classList.toggle('hide-stop-labels', map.getZoom() < STOP_LABEL_MIN_ZOOM);
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
    L.polyline(points, { weight: 3, ...style }).addTo(layers.trails);
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
