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

function getStops() {
  return request('/api/stops');
}

function getRoutes() {
  return request('/api/routes');
}
