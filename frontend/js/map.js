let map = null;
const mapLayers = { trails: null, markers: null, gaps: null };
let lastRendered = [];
let selectedVehicleId = null;

function initMap() {
  map = L.map('map', { zoomControl: true, attributionControl: true });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
  }).addTo(map);
  mapLayers.trails = L.layerGroup().addTo(map);
  mapLayers.markers = L.layerGroup().addTo(map);
  mapLayers.gaps = L.layerGroup();
  map.setView([-31.98133, 115.81597], 16);
}

function validPoints(vehicle) {
  return vehicle.positions.filter(p => p.latitude !== null && p.longitude !== null);
}

function markerIcon(vehicle, position, selected) {
  const speed = position?.speed_mps == null ? '—' : `${Math.round(position.speed_mps * 3.6)} km/h`;
  return L.divIcon({
    className: '',
    iconSize: null,
    html: `<div class="nw-pin ${selected ? 'selected' : ''}"><span class="pin-dot" style="background:${vehicle.colour || '#777'}"></span>${escapeMapHtml(vehicle.name || vehicle.vehicle_id)}<span class="mono" style="font-size:9px;opacity:.62">${speed}</span></div>`
  });
}

function escapeMapHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

function renderMap(vehicles, options = {}) {
  if (!map) initMap();
  lastRendered = vehicles;
  selectedVehicleId = options.selectedVehicle ?? null;
  mapLayers.trails.clearLayers();
  mapLayers.markers.clearLayers();
  mapLayers.gaps.clearLayers();

  const bounds = L.latLngBounds([]);
  let drawn = 0;

  for (const vehicle of vehicles) {
    const points = validPoints(vehicle);
    if (!points.length) continue;
    drawn += 1;
    const latLngs = points.map(p => [p.latitude, p.longitude]);
    const style = { color: vehicle.colour || '#6f6680' };

    if (options.showTrails !== false) {
      L.polyline(latLngs, { weight: 4, opacity: .62, lineJoin: 'round', ...style })
        .bindPopup(`${escapeMapHtml(vehicle.name || vehicle.vehicle_id)} — ${vehicle.count} positions`)
        .addTo(mapLayers.trails);
    }

    if (options.showMarkers !== false) {
      const latest = points[points.length - 1];
      const marker = L.marker([latest.latitude, latest.longitude], {
        icon: markerIcon(vehicle, latest, vehicle.vehicle_id === selectedVehicleId),
        zIndexOffset: vehicle.vehicle_id === selectedVehicleId ? 400 : 200
      });
      marker.on('click', () => window.dispatchEvent(new CustomEvent('nuway:vehicle-select', { detail: vehicle.vehicle_id })));
      marker.bindPopup(`<b>${escapeMapHtml(vehicle.name || vehicle.vehicle_id)}</b><br>${escapeMapHtml(new Date(latest.timestamp).toLocaleString('en-AU', { timeZone: 'Australia/Perth' }))}<br>${latest.speed_mps == null ? 'Speed unavailable' : `${(latest.speed_mps * 3.6).toFixed(1)} km/h`}`);
      marker.addTo(mapLayers.markers);
    }

    if (options.showGaps) {
      vehicle.positions.filter(p => p.gps_status === -1).forEach(p => {
        const before = points.findLast?.(q => q.timestamp < p.timestamp);
        if (!before) return;
        L.circleMarker([before.latitude, before.longitude], { radius: 4, color: '#fff', weight: 2, fillColor: '#b86a22', fillOpacity: 1 })
          .bindTooltip('GPS no-fix sample')
          .addTo(mapLayers.gaps);
      });
    }

    bounds.extend(latLngs);
  }

  if (options.showGaps) mapLayers.gaps.addTo(map); else if (map.hasLayer(mapLayers.gaps)) map.removeLayer(mapLayers.gaps);
  if (drawn > 0 && options.fit !== false) map.fitBounds(bounds, { padding: [42, 42] });
  setTimeout(() => map.invalidateSize(), 50);
  return drawn;
}

function focusVehicle(vehicleId) {
  const vehicle = lastRendered.find(v => v.vehicle_id === vehicleId);
  const points = vehicle ? validPoints(vehicle) : [];
  if (!points.length || !map) return;
  const latest = points[points.length - 1];
  map.setView([latest.latitude, latest.longitude], Math.max(map.getZoom(), 17));
}
