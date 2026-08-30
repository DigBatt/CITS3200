// Leaflet setup: map init, tile layer, and one layer group per overlay.
//
// Layer groups map one-to-one onto the overlays.
//
// Owns: vehicle markers, position trails, event markers.

let map = null;
const layers = { trails: null };

function initMap() {
  map = L.map('map');
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);
  layers.trails = L.layerGroup().addTo(map);
}

// Draws one trail per vehicle and a marker at its last known position, then
// fits the view to everything drawn. Returns the number of vehicles with
// something to draw, so the caller can say when there is nothing.
function drawTracks(vehicles) {
  layers.trails.clearLayers();
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

  if (drawn > 0) map.fitBounds(bounds, { padding: [24, 24] });
  return drawn;
}
