// knows endpoint URLs.
//
//   getPositions()                     GET /api/positions
//
//

async function getPositions() {
  const response = await fetch('/api/positions');
  const body = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}
