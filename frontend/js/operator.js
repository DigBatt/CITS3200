// Operator view (S09): the stops on one route with the riders waiting at each,
// and where the operator's vehicle is.
//
// S09.1: the operator picks their vehicle and the route it is running when the
// page loads. The choice is kept in the URL (?vehicle=1&route=campus-loop), so
// a bookmarked tablet reopens on it, and in localStorage as a fallback. The
// server holds no vehicle-to-route assignment.

const OPERATOR_REFRESH_MS = 10000; // S09.5: well inside the 30 s requirement.
const AT_STOP_METRES = 60;         // closer than this counts as "at" a stop.
const OPERATOR_STORAGE_KEY = 'operator_selection';

const operatorEls = {
  vehicle: document.getElementById('vehicle-selector'),
  route: document.getElementById('route-selector'),
  vehicleInfo: document.getElementById('operator-vehicle'),
  card: document.getElementById('operator-stops-card'),
  title: document.getElementById('operator-route-title'),
  updated: document.getElementById('operator-updated'),
  empty: document.getElementById('operator-empty'),
  error: document.getElementById('operator-error'),
  stops: document.getElementById('operator-stops'),
};

let operatorTimer = null;
let operatorInFlight = false;

async function operatorFetch(path) {
  const response = await fetch(path, { cache: 'no-store' });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}

function operatorEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

// "45 s", "12 min", "1 h 5 min".
function formatWait(seconds) {
  if (seconds == null) return '';
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

// "3 days ago" style age for the last recorded position.
function formatAgo(seconds) {
  if (seconds == null) return '';
  if (seconds < 90) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400 * 2) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

function metresBetween(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.latitude - a.latitude) * rad;
  const dLon = (b.longitude - a.longitude) * rad;
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(a.latitude * rad) * Math.cos(b.latitude * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

// ---- Selection (S09.1) ----

function readSelection() {
  const params = new URLSearchParams(window.location.search);
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(OPERATOR_STORAGE_KEY) ?? '{}') ?? {};
  } catch {
    saved = {};
  }
  return {
    vehicle: params.get('vehicle') ?? saved.vehicle ?? '',
    route: params.get('route') ?? saved.route ?? '',
  };
}

function saveSelection() {
  const selection = { vehicle: operatorEls.vehicle.value, route: operatorEls.route.value };
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(selection)) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  history.replaceState(null, '', url);
  try {
    localStorage.setItem(OPERATOR_STORAGE_KEY, JSON.stringify(selection));
  } catch {
    // Private mode or blocked storage: the URL still carries the choice.
  }
}

function fillSelect(select, placeholder, items, wanted) {
  select.innerHTML = '';
  select.appendChild(new Option(placeholder, ''));
  items.forEach(({ value, label }) => select.appendChild(new Option(label, value)));
  select.value = items.some((item) => item.value === wanted) ? wanted : '';
  select.disabled = false;
}

// ---- Rendering ----

function renderVehicle(vehicle, stops) {
  const box = operatorEls.vehicleInfo;
  if (!vehicle) {
    box.hidden = true;
    return;
  }
  box.hidden = false;

  const position = vehicle.last_position;
  const hasFix = position && position.latitude != null && position.longitude != null;
  const live = vehicle.status === 'active';

  // S09.4: live when the logger (S01/S03) is feeding fresh data, otherwise the
  // latest recorded position, labelled with how old it is.
  let detail;
  let nearest = null;
  if (!hasFix) {
    detail = 'No position recorded yet.';
  } else {
    stops.forEach((stop) => {
      const metres = metresBetween(position, stop);
      if (!nearest || metres < nearest.metres) nearest = { stop, metres };
    });
    const where = !nearest
      ? `${position.latitude.toFixed(5)}, ${position.longitude.toFixed(5)}`
      : nearest.metres <= AT_STOP_METRES
        ? `At ${nearest.stop.name}`
        : `${Math.round(nearest.metres)} m from ${nearest.stop.name}`;
    detail = live ? where : `${where} · recorded ${formatAgo(vehicle.seconds_since_last_seen)}`;
  }

  box.innerHTML = `
    <span class="operator-vehicle-name">${operatorEscape(vehicle.name ?? vehicle.id)}</span>
    <span class="operator-badge ${live ? 'is-live' : ''}">${live ? 'LIVE' : 'LAST RECORDED'}</span>
    <span class="operator-vehicle-detail">${operatorEscape(detail)}</span>
  `;
  return nearest && nearest.metres <= AT_STOP_METRES ? nearest.stop.id : null;
}

function renderStops(data, hereStopId) {
  operatorEls.card.hidden = false;
  operatorEls.error.hidden = true;
  operatorEls.title.textContent = `STOPS · ${data.route.name.toUpperCase()}${data.route.loop ? ' (LOOP)' : ''}`;
  operatorEls.updated.textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString('en-AU')}`;

  // S09.6: say so plainly rather than leave a column of zeros to read.
  operatorEls.empty.hidden = data.total_waiting > 0;

  // S09.3: stops in service order, as configured.
  operatorEls.stops.innerHTML = data.stops.map((stop, index) => `
    <li class="operator-stop ${stop.waiting ? 'has-waiting' : ''}" data-stop-id="${operatorEscape(stop.id)}">
      <span class="operator-stop-index">${index + 1}</span>
      <span class="operator-stop-name">${operatorEscape(stop.name)}${
        stop.id === hereStopId ? '<span class="operator-stop-here">VEHICLE HERE</span>' : ''
      }</span>
      <span class="operator-stop-count">
        <strong class="operator-stop-waiting">${stop.waiting}</strong> waiting
        ${stop.waiting ? `<span class="operator-stop-age">oldest ${formatWait(stop.oldest_wait_seconds)}</span>` : ''}
      </span>
      ${stop.waiting ? `<button type="button" class="operator-collect" data-stop-id="${operatorEscape(stop.id)}">Picked up</button>` : ''}
    </li>
  `).join('');
}

function renderError(message) {
  operatorEls.card.hidden = false;
  operatorEls.error.hidden = false;
  operatorEls.error.textContent = `Could not refresh: ${message}. Retrying.`;
}

// Closes every open request at the stop, then refreshes so it clears at once
// rather than on the next tick.
async function collectAtStop(button) {
  button.disabled = true;
  try {
    const response = await fetch(`/api/stops/${encodeURIComponent(button.dataset.stopId)}/collect`, { method: 'POST' });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
    }
  } catch (err) {
    button.disabled = false;
    renderError(err.message);
    return;
  }
  refreshOperatorView();
}

// ---- Refresh loop (S09.5) ----

async function refreshOperatorView() {
  const routeId = operatorEls.route.value;
  const vehicleId = operatorEls.vehicle.value;
  if (!routeId) {
    operatorEls.card.hidden = true;
    operatorEls.vehicleInfo.hidden = true;
    return;
  }
  if (operatorInFlight) return;
  operatorInFlight = true;
  try {
    const [waiting, fleet] = await Promise.all([
      operatorFetch(`/api/routes/${encodeURIComponent(routeId)}/waiting`),
      vehicleId ? operatorFetch('/api/vehicles') : Promise.resolve(null),
    ]);
    const vehicle = fleet?.vehicles.find((v) => v.id === vehicleId) ?? null;
    const hereStopId = renderVehicle(vehicle, waiting.stops);
    renderStops(waiting, hereStopId);
  } catch (err) {
    renderError(err.message);
  } finally {
    operatorInFlight = false;
  }
}

function restartOperatorRefresh() {
  clearInterval(operatorTimer);
  refreshOperatorView();
  operatorTimer = setInterval(refreshOperatorView, OPERATOR_REFRESH_MS);
}

async function initOperatorView() {
  const wanted = readSelection();
  try {
    const [fleet, network] = await Promise.all([
      operatorFetch('/api/vehicles'),
      operatorFetch('/api/routes'),
    ]);
    fillSelect(
      operatorEls.vehicle,
      'Choose a vehicle',
      fleet.vehicles.map((v) => ({ value: v.id, label: v.name ? `${v.name} (${v.id})` : v.id })),
      wanted.vehicle,
    );
    fillSelect(
      operatorEls.route,
      network.routes.length ? 'Choose a route' : 'No routes configured',
      network.routes.map((r) => ({ value: r.id, label: r.name })),
      wanted.route,
    );
  } catch (err) {
    renderError(err.message);
    return;
  }

  [operatorEls.vehicle, operatorEls.route].forEach((select) => {
    select.addEventListener('change', () => {
      saveSelection();
      restartOperatorRefresh();
    });
  });

  // The list is rebuilt on every refresh, so listen once on the list itself.
  operatorEls.stops.addEventListener('click', (event) => {
    const button = event.target.closest('.operator-collect');
    if (button) collectAtStop(button);
  });

  // Catch up straight away when a backgrounded tablet is woken.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshOperatorView();
  });

  restartOperatorRefresh();
}

initOperatorView();
