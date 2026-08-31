async function getPositions({ vehicles, from, to } = {}) {
  const params = new URLSearchParams();
  if (vehicles) params.set('vehicles', vehicles);
  if (from) params.set('from', from);
  if (to) params.set('to', to);

  const query = params.toString();
  const response = await fetch(`/api/positions${query ? `?${query}` : ''}`);
  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}
