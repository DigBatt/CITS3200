/** "12 s ago", "3 min ago", "2 h ago". */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds == null) return 'never';
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86_400)} d ago`;
}

export function ageSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  return Number.isNaN(then) ? null : Math.max(0, (now - then) / 1000);
}

export function formatSpeed(mps: number | null | undefined): string {
  if (mps == null) return '–';
  return `${(mps * 3.6).toFixed(0)} km/h`;
}

export function formatDistance(metres: number): string {
  return metres < 1000 ? `${Math.round(metres)} m` : `${(metres / 1000).toFixed(1)} km`;
}

export function formatClock(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
