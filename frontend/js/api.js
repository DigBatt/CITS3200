// Fetch wrappers for the JSON API in docs/api.md. Each resolves to the parsed
// body, or throws with the API's error message.

async function request(path, { vehicles, from, to } = {}) {
  const params = new URLSearchParams();
  if (vehicles) params.set('vehicles', vehicles);
  if (from) params.set('from', from);
  if (to) params.set('to', to);

  const query = params.toString();
  const response = await fetch(`${path}${query ? `?${query}` : ''}`);
  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}

function getPositions(query) {
  return request('/api/positions', query);
}

// Just the first and last position in a period, for the calendar's slider.
function getPositionsExtent(query) {
  return request('/api/positions/extent', query);
}

function getMetrics(query) {
  return request('/api/metrics', query);
}

function getVehicles() {
  return request('/api/vehicles');
}

// The service schedule (S21). Public: the dashboard shows scheduled time to
// anyone, so anyone may read the roster behind it. Editing it is the admin
// page's PUT, which S13 will guard.
function getSchedule() {
  return request('/api/schedule');
}

// Operator reported downtime, for the service calendar. Reading is public;
// the admin page's writes are what S13 will guard.
function getDowntime(query) {
  return request('/api/downtime', query);
}

function getRoutes() {
  return request('/api/routes');
}

function getStops() {
  return request('/api/stops');
}

// POST /api/pickup-requests. Resolves to { request, created }: `created` is
// false when the rider already had an open request at that stop, which the
// API answers with 200 rather than 201 (docs/api.md, S08).
async function createPickupRequest(stopId) {
  const response = await fetch('/api/pickup-requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stop_id: stopId }),
  });
  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return { request: body.request, created: response.status === 201 };
}

// GET /api/pickup-requests/mine. No auth: identified by the rider_token
// cookie (S08.2, S15). Resolves to { request: null } if this rider has no
// cookie yet, or has never made a request — the normal state, not an error.
function getMyPickupRequest() {
  return request('/api/pickup-requests/mine');
}

// POST /api/pickup-requests/<id>/cancel (S15). Resolves to the cancelled
// request, or throws with the API's message (e.g. it was already collected).
async function cancelPickupRequest(requestId) {
  const response = await fetch(`/api/pickup-requests/${encodeURIComponent(requestId)}/cancel`, { method: 'POST' });
  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body.request;
}
