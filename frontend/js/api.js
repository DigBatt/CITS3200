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

function getMetrics(query) {
  return request('/api/metrics', query);
}

function getVehicles() {
  return request('/api/vehicles');
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
