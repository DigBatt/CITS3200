//  Owns the current selection state and nothing else.
//
//  The selection is the timeline's range plus the vehicle filter. A change to
//  either, and every live poll, refetches positions, metrics and liveness.

const statusLine = document.getElementById('status');

// The banner at the top of the map. `isError` styles it as a problem to fix
// rather than a passing note like "Loading positions...".
function setStatus(message, { isError = false } = {}) {
  statusLine.textContent = message ?? '';
  statusLine.hidden = !message;
  statusLine.classList.toggle('is-error', Boolean(message) && isError);
}

let timelineControl = null;
let currentRange = null;
let latestLoad = 0;
// The selection the map view was last fitted to. Live polls repeat it (their
// `to` is always null), so they redraw without moving the map.
let lastFitted = null;

// Turns a failed request into wording for people rather than the raw error.
// fetch rejects with a TypeError ("Failed to fetch" in Chrome) only when the
// server could not be reached at all; the API's own errors are plain Errors.
// Range errors are reworded to match the picker's Start/End labels, rather
// than the API's internal from/to param names.
function humanizeError(error) {
  if (error instanceof TypeError) {
    // While live, the next poll tries again on its own.
    return currentRange?.live
      ? "Couldn't reach the server — retrying"
      : "Couldn't reach the server. Check it's running, then try again.";
  }
  const message = error?.message ?? String(error);
  if (message.includes("must not be after")) {
    return "'Start time' must be before 'End time'.";
  }
  return message;
}

async function load() {
  const request = ++latestLoad;
  const query = {
    vehicles: Vehicles.getSelection(),
    from: currentRange?.from,
    to: currentRange?.to,
  };

  setStatus('Loading positions...');
  Vehicles.refresh();

  const [positions, metrics] = await Promise.allSettled([getPositions(query), getMetrics(query)]);

  // A newer selection was made while these were in flight; its load owns the
  // screen, so drawing this one would show the wrong vehicle or period.
  if (request !== latestLoad) return;

  if (positions.status === 'fulfilled') {
    const selection = JSON.stringify(query);
    const drawn = drawTracks(positions.value.vehicles, { fit: selection !== lastFitted });
    if (drawn > 0) lastFitted = selection;

    if (drawn === 0) {
      timelineControl?.showNoData();
      setStatus('No positions to show.');
    } else {
      timelineControl?.clearStatus();
      setStatus(null);
    }
  } else {
    // A failed request means there's no valid current selection -- the map
    // shouldn't keep showing whatever trail was drawn before this attempt.
    drawTracks([]);
    setStatus(humanizeError(positions.reason), { isError: true });
  }

  if (metrics.status === 'fulfilled') {
    Utilisation.render(metrics.value);
  } else {
    Utilisation.showError(humanizeError(metrics.reason));
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  Stops.init();
  Vehicles.init({ onChange: () => load() });

  timelineControl = Timeline.createTimelineControl(
    document.getElementById('timeline-container'),
    { onChange: (range) => { if (range) { currentRange = range; load(); } } }
  );
});
