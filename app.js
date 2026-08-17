const OFFLINE_THRESHOLD_MINUTES = 15;
const VEHICLE_COLORS = {
  'nuway-1': '#f5b642',
  'nuway-2': '#54a7ff',
  'nuway-3': '#2bc48a',
  'nuway-4': '#bb83ff'
};
const EMPTY_HISTORY = { paths: {}, events: [] };
const state = { vehicle: 'all', mode: 'live', date: NUWAY_DATA.today };

const vehicleFilter = document.getElementById('vehicleFilter');
const dateFilter = document.getElementById('dateFilter');
const filterSummary = document.getElementById('filterSummary');
const modeButtons = [...document.querySelectorAll('.mode-btn')];
const toggleRoutes = document.getElementById('toggleRoutes');
const toggleDisengagements = document.getElementById('toggleDisengagements');
const toggleReengagements = document.getElementById('toggleReengagements');

// The prototype's "today" is defined by the sample dataset. The real system should
// populate this with the server's local date. Setting max prevents future selection.
dateFilter.max = NUWAY_DATA.today;
dateFilter.value = NUWAY_DATA.today;

const map = L.map('map', { zoomControl: true }).setView([-31.9814, 115.8198], 16);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const layers = {
  routes: L.layerGroup().addTo(map),
  vehicles: L.layerGroup().addTo(map),
  disengagements: L.layerGroup().addTo(map),
  reengagements: L.layerGroup().addTo(map)
};

let chart;

function isOffline(v) {
  return v.lastSeenMinutes >= OFFLINE_THRESHOLD_MINUTES;
}

function selectedHistory() {
  // Important: never fall back to today's data for an unknown date.
  return NUWAY_DATA.history[state.date] || EMPTY_HISTORY;
}

function vehicleIdsForSelectionDate() {
  if (state.mode === 'live' || state.mode === 'today') {
    return new Set(Object.keys((NUWAY_DATA.history[NUWAY_DATA.today] || EMPTY_HISTORY).paths));
  }
  return new Set(Object.keys(selectedHistory().paths));
}

function vehiclesForSelectionDate() {
  const ids = vehicleIdsForSelectionDate();
  return NUWAY_DATA.vehicles.filter(v => ids.has(v.id));
}

function selectedVehicles() {
  const dayVehicles = vehiclesForSelectionDate();
  return state.vehicle === 'all' ? dayVehicles : dayVehicles.filter(v => v.id === state.vehicle);
}

function syncVehicleFilter() {
  const available = vehiclesForSelectionDate();
  const availableIds = new Set(available.map(v => v.id));

  if (state.vehicle !== 'all' && !availableIds.has(state.vehicle)) {
    state.vehicle = 'all';
  }

  vehicleFilter.innerHTML = '<option value="all">All vehicles</option>';
  available.forEach(v => {
    const option = document.createElement('option');
    option.value = v.id;
    option.textContent = v.name;
    vehicleFilter.appendChild(option);
  });
  vehicleFilter.value = state.vehicle;
  vehicleFilter.disabled = available.length === 0;
}

function markerIcon(v) {
  const color = VEHICLE_COLORS[v.id] || '#f5b642';
  return L.divIcon({
    className: '',
    html: `<div class="vehicle-marker ${isOffline(v) ? 'offline' : ''}" style="--vehicle-color:${color}"></div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12]
  });
}

function eventIcon(type) {
  return L.divIcon({
    className: '',
    html: type === 'disengagement'
      ? '<div class="event-marker-disengage"></div>'
      : '<div class="event-marker-reengage"></div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9]
  });
}

function renderMap() {
  Object.values(layers).forEach(layer => layer.clearLayers());
  const history = selectedHistory();
  const visibleIds = new Set(selectedVehicles().map(v => v.id));
  const bounds = [];

  Object.entries(history.paths).forEach(([vehicleId, path]) => {
    if (!visibleIds.has(vehicleId)) return;
    const v = NUWAY_DATA.vehicles.find(x => x.id === vehicleId);
    if (!v || !path.length) return;

    const offline = state.mode === 'live' && isOffline(v);
    const routeColor = VEHICLE_COLORS[vehicleId] || '#f5b642';
    const polyline = L.polyline(path, {
      color: offline ? '#707b88' : routeColor,
      weight: 4,
      opacity: offline ? .45 : .82,
      dashArray: offline ? '7,7' : null
    });
    if (toggleRoutes.checked) polyline.addTo(layers.routes);

    path.forEach(point => bounds.push(point));
    const final = path[path.length - 1];
    const marker = L.marker(final, { icon: markerIcon({ ...v, lastSeenMinutes: offline ? v.lastSeenMinutes : 0 }) }).bindPopup(`
      <div class="popup-title">${v.name}</div>
      <div class="popup-meta">${offline ? `OFFLINE · Last update ${v.lastSeenMinutes} min ago` : `${v.autonomyMode} · ${v.battery}% battery`}<br>Operator: ${v.operator}<br>Passengers: ${v.passengers}</div>
    `, { className: 'custom-popup' });
    marker.addTo(layers.vehicles);
  });

  history.events.forEach(event => {
    if (!visibleIds.has(event.vehicle)) return;
    const v = NUWAY_DATA.vehicles.find(x => x.id === event.vehicle);
    const marker = L.marker([event.lat, event.lng], { icon: eventIcon(event.type) }).bindPopup(`
      <div class="popup-title">${event.type === 'disengagement' ? 'DISENGAGEMENT' : 'RE-ENGAGEMENT'} · ${v.name}</div>
      <div class="popup-meta">${state.date} · ${event.time}<br>${event.reason}</div>
    `, { className: 'custom-popup' });

    if (event.type === 'disengagement' && toggleDisengagements.checked) marker.addTo(layers.disengagements);
    if (event.type === 'reengagement' && toggleReengagements.checked) marker.addTo(layers.reengagements);
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [36, 36], maxZoom: 17 });
  } else {
    map.setView([-31.9814, 115.8198], 16);
  }
}

function renderFleetStatus() {
  const vehicleList = document.getElementById('vehicleList');
  vehicleList.innerHTML = '';
  const dayVehicles = vehiclesForSelectionDate();
  const shownVehicles = selectedVehicles();

  document.getElementById('fleetCount').textContent = dayVehicles.length;

  if (state.mode === 'live') {
    document.getElementById('activeCount').textContent = dayVehicles.filter(v => !isOffline(v)).length;
    document.getElementById('offlineCount').textContent = dayVehicles.filter(isOffline).length;
  } else {
    // Historical data tells us which vehicles ran, not whether they are currently online.
    document.getElementById('activeCount').textContent = dayVehicles.length;
    document.getElementById('offlineCount').textContent = 0;
  }

  if (!shownVehicles.length) {
    vehicleList.innerHTML = '<div class="empty-state">No vehicle runs recorded for this selection.</div>';
    return;
  }

  shownVehicles.forEach(v => {
    const offline = state.mode === 'live' && isOffline(v);
    const row = document.createElement('div');
    row.className = `vehicle-row ${offline ? 'offline' : ''} ${state.vehicle === v.id ? 'selected' : ''}`;
    row.innerHTML = `<div class="vehicle-state-dot" style="background:${offline ? '#7d8794' : VEHICLE_COLORS[v.id]}"></div><div><div class="vehicle-name">${v.name}</div><div class="vehicle-detail">${offline ? `Offline · ${v.lastSeenMinutes} min since update` : `${v.autonomyMode} · ${v.operator}`}</div></div><div class="vehicle-battery">${v.battery}%</div>`;
    row.addEventListener('click', () => {
      state.vehicle = v.id;
      vehicleFilter.value = v.id;
      renderAll();
    });
    vehicleList.appendChild(row);
  });
}

function aggregateTech() {
  const vs = selectedVehicles();
  const names = ['Network', 'GPS', 'LiDAR', 'Cameras', 'Autonomous Software'];
  if (!vs.length) return [];

  return names.map(name => {
    const values = vs.map(v => v.tech[name]);
    if (values.every(value => ['Online', 'Healthy', 'Running'].includes(value))) {
      return [name, name === 'Network' ? 'Online' : name === 'Autonomous Software' ? 'Running' : 'Healthy', 'ok'];
    }
    if (values.every(value => value === 'Offline')) return [name, 'Offline', 'offline'];
    return [name, 'Attention', 'warning'];
  });
}

function renderTech() {
  const el = document.getElementById('techStatus');
  const rows = aggregateTech();
  el.innerHTML = rows.length
    ? rows.map(([name, label, status]) => `<div class="tech-row"><span class="tech-name">${name}</span><span class="status-label ${status}">${label}</span></div>`).join('')
    : '<div class="empty-state">No technology data for this selection.</div>';
}

function renderMetrics() {
  const vs = selectedVehicles();
  const service = document.getElementById('serviceMetrics');
  const eventMetrics = document.getElementById('eventMetrics');
  const recentEvents = document.getElementById('recentEvents');

  if (!vs.length) {
    service.innerHTML = '<div class="empty-state">No service metrics for this selection.</div>';
    eventMetrics.innerHTML = '<div class="empty-state">No event data for this selection.</div>';
    recentEvents.innerHTML = '';
    return;
  }

  const sum = key => vs.reduce((total, v) => total + (v[key] || 0), 0);
  const trips = sum('trips');
  const completed = sum('completed');
  const passengers = sum('passengers');
  const autonomy = sum('autonomousHours');
  const completion = trips ? Math.round(completed / trips * 100) : 0;

  service.innerHTML = [
    ['Trips', trips, ''], ['Completed', completed, ''], ['Completion', completion, '%'],
    ['Autonomous time', autonomy.toFixed(1), 'h'], ['Passengers', passengers, ''],
    ['Vehicles shown', vs.length, '']
  ].map(([label, value, suffix]) => `<div class="metric-tile"><div class="metric-label">${label}</div><div class="metric-value">${value}<span class="metric-suffix">${suffix}</span></div></div>`).join('');

  const history = selectedHistory();
  const ids = new Set(vs.map(v => v.id));
  const events = history.events.filter(e => ids.has(e.vehicle));
  const disengagements = events.filter(e => e.type === 'disengagement').length;
  const reengagements = events.filter(e => e.type === 'reengagement').length;
  const mtbd = disengagements ? Math.round((autonomy * 60) / disengagements) : 0;

  eventMetrics.innerHTML = [
    ['Disengagements', disengagements], ['Re-engagements', reengagements],
    ['MTBD', disengagements ? `${mtbd} min` : '—'], ['Events / trip', trips ? (disengagements / trips).toFixed(2) : '0.00']
  ].map(([label, value]) => `<div class="event-kpi"><span>${label}</span><strong>${value}</strong></div>`).join('');

  recentEvents.innerHTML = events.slice(-3).reverse().map(e => {
    const v = NUWAY_DATA.vehicles.find(x => x.id === e.vehicle);
    return `<div class="mini-event"><span class="type">${e.type === 'disengagement' ? 'Disengagement' : 'Re-engagement'}</span><span class="meta">${v.name} · ${e.time}</span></div>`;
  }).join('') || '<div class="mini-event"><span class="meta">No events for this selection</span></div>';
}

function renderUtilisation() {
  const vs = selectedVehicles();
  const utilKpis = document.getElementById('utilKpis');

  if (chart) {
    chart.destroy();
    chart = null;
  }

  if (!vs.length) {
    utilKpis.innerHTML = '<div class="empty-state">No utilisation data for this selection.</div>';
    return;
  }

  const key = state.vehicle === 'all' ? 'all' : state.vehicle;
  const usage = NUWAY_DATA.timeUsage[key] || NUWAY_DATA.timeUsage.all;
  const avg = metric => Math.round(vs.reduce((total, v) => total + v[metric], 0) / vs.length);

  utilKpis.innerHTML = [
    ['Availability', `${avg('availability')}%`],
    ['Utilisation', `${avg('utilisation')}%`],
    ['Autonomous utilisation', `${avg('autonomousUtilisation')}%`]
  ].map(([label, value]) => `<div class="util-kpi"><span>${label}</span><strong>${value}</strong></div>`).join('');

  chart = new Chart(document.getElementById('utilisationChart'), {
    type: 'doughnut',
    data: {
      labels: Object.keys(usage),
      datasets: [{
        data: Object.values(usage),
        backgroundColor: ['#f5b642', '#54a7ff', '#5c6f87', '#f28c28', '#ee5c5c', '#8a7c69'],
        borderColor: '#0d1a2d',
        borderWidth: 3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '67%',
      plugins: {
        legend: { position: 'bottom', labels: { color: '#9eabb9', boxWidth: 9, boxHeight: 9, padding: 10, font: { size: 9 } } },
        tooltip: { callbacks: { label: context => `${context.label}: ${context.raw}%` } }
      }
    }
  });
}

function renderFilterSummary() {
  const selectedVehicle = state.vehicle === 'all'
    ? 'All vehicles'
    : (NUWAY_DATA.vehicles.find(x => x.id === state.vehicle)?.name || 'All vehicles');
  const timeLabel = state.mode === 'live' ? 'Live' : state.mode === 'today' ? 'Today' : state.date;
  const noRuns = vehiclesForSelectionDate().length === 0 ? ' · No recorded runs' : '';
  filterSummary.textContent = `Showing: ${selectedVehicle} · ${timeLabel}${noRuns}`;
  dateFilter.disabled = state.mode !== 'calendar';
}

function renderAll() {
  syncVehicleFilter();
  renderFilterSummary();
  renderFleetStatus();
  renderTech();
  renderMetrics();
  renderUtilisation();
  renderMap();
}

vehicleFilter.addEventListener('change', event => {
  state.vehicle = event.target.value;
  renderAll();
});

modeButtons.forEach(button => button.addEventListener('click', () => {
  modeButtons.forEach(b => b.classList.remove('active'));
  button.classList.add('active');
  state.mode = button.dataset.mode;

  if (state.mode === 'live' || state.mode === 'today') {
    state.date = NUWAY_DATA.today;
    dateFilter.value = NUWAY_DATA.today;
  }
  renderAll();
}));

dateFilter.addEventListener('change', event => {
  if (!event.target.value) return;

  // HTML's max attribute blocks this in normal use, but this guard also protects
  // the state if a future value is injected programmatically.
  if (event.target.value > NUWAY_DATA.today) {
    event.target.value = state.date;
    return;
  }

  state.date = event.target.value;
  renderAll();
});

[toggleRoutes, toggleDisengagements, toggleReengagements].forEach(toggle => toggle.addEventListener('change', renderMap));

renderAll();
setTimeout(() => map.invalidateSize(), 100);
