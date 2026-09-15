// Display formatting shared by the panels. Times are shown in Perth
// (docs/data-schema.md s4), reusing the timeline's conversions.

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

// "4 Sep 2025, 4:58 pm" for an ISO 8601 instant.
function formatInstant(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  return Timeline.formatDisplay(Timeline.getPerthDateString(date), Timeline.getPerthTimeString(date));
}

// Minutes under an hour, otherwise hours to one decimal.
function formatDuration(seconds) {
  if (seconds == null) return '—';
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function formatPercent(fraction) {
  return fraction == null ? '—' : `${(fraction * 100).toFixed(1)}%`;
}
