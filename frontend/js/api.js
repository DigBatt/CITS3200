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
