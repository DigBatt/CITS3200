async function requestJson(url) {
  const response = await fetch(url);
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  return body;
}

function getVehicles() { return requestJson('/api/vehicles'); }

function getPositions({ vehicle = 'all', mode = 'live', date = null } = {}) {
  const params = new URLSearchParams();
  if (vehicle !== 'all') params.set('vehicles', vehicle);
  if ((mode === 'today' || mode === 'calendar') && date) {
    params.set('from', date);
    params.set('to', date);
  }
  const suffix = params.toString() ? `?${params}` : '';
  return requestJson(`/api/positions${suffix}`);
}
