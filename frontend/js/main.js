//  Owns the current selection state and nothing else.
//
//  The selection is the timeline's range plus the vehicle filter. A change to
//  either, and every live poll, refetches positions, metrics and liveness.
//
//  The range is picked on the docked mini calendar (days, by dragging) and
//  the timeline control under it (Live, and the start/end time sliders), so
//  the two are mounted together here.

const statusLine = document.getElementById('status');

function setStatus(message) {
  statusLine.textContent = message ?? '';
  statusLine.hidden = !message;
}

let timelineControl = null;
let currentRange = null;
let latestLoad = 0;
// The newest load whose result is on screen. Mid drag, a response is drawn
// as long as nothing newer already has been, so the map keeps up with the
// thumb instead of waiting for the requests to stop overtaking each other.
let latestDrawn = 0;
// The selection the map view was last fitted to. Live polls repeat it (their
// `to` is always null), so they redraw without moving the map.
let lastFitted = null;

// Turns a raw API error message into wording that matches the picker's own
// Start/End labels, rather than the API's internal from/to param names.
function humanizeError(message) {
  if (message.includes("must not be after")) {
    return "'Start time' must be before 'End time'.";
  }
  return message;
}

async function load() {
  const request = ++latestLoad;
  const { scrub = false, dragging = false } = currentRange ?? {};
  const query = {
    vehicles: Vehicles.getSelection(),
    from: currentRange?.from,
    to: currentRange?.to,
  };

  // Mid drag these fire several times a second: a flashing status line and
  // a liveness refetch (which does not depend on the period) would be noise.
  if (!dragging) {
    setStatus('Loading positions...');
    Vehicles.refresh();
  }

  const [positions, metrics] = await Promise.allSettled([getPositions(query), getMetrics(query)]);

  // A newer selection was made while these were in flight; its load owns the
  // screen, so drawing this one would show the wrong vehicle or period. A
  // drag is the exception: each step is only a moment along the same
  // selection, so any step newer than what is drawn is worth showing.
  if (dragging ? request < latestDrawn : request !== latestLoad) return;
  latestDrawn = request;

  if (positions.status === 'fulfilled') {
    View3D.update(positions.value.vehicles);
    const selection = JSON.stringify(query);
    // A slider being dragged, or a live poll, redraws in place: refitting
    // would move the map out from under the operator mid scrub.
    const fit = selection !== lastFitted && !scrub;
    const drawn = drawTracks(positions.value.vehicles, { fit });
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
    View3D.update([]);
    setStatus(humanizeError(positions.reason.message));
  }

  if (metrics.status === 'fulfilled') {
    Utilisation.render(metrics.value);
  } else {
    Utilisation.showError(humanizeError(metrics.reason.message));
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  Stops.init();
  Vehicles.init({
    onChange: () => {
      // A new vehicle is a new selection to frame, even straight after a scrub.
      if (currentRange) currentRange = { ...currentRange, scrub: false };
      load();
    },
  });

  // The docked mini month, on screen for every view. Same wiring as the
  // admin page, plus the range: dragging across days sets the timeline's
  // dates, and the timeline's changes are painted back onto the days.
  const calendar = ServiceCalendar.mount({
    mini: document.getElementById('dashboard-mini'),
    head: document.getElementById('dashboard-mini-head'),
    panel: document.getElementById('period-panel'),
    overlay: document.getElementById('cal-overlay'),
    body: document.getElementById('cal-overlay-body'),
    close: document.getElementById('cal-overlay-close'),
  }, {
    // The month bar sits in the header and opens the month and the sliders
    // as an overlay, so it starts closed: nothing covers the map until asked.
    collapsed: true,
    // A scheduled or downtime block opens that vehicle's figures for its
    // time, on the admin page (signing in first if need be).
    onBlock: ({ vehicle, from, to }) => {
      window.location.href = `/admin?${new URLSearchParams({ tab: 'figures', vehicles: vehicle, from, to })}`;
    },
    range: {
      get: () => timelineControl?.getDates(),
      select: (start, end) => timelineControl?.setDates(start, end),
      max: () => Timeline.getPerthDateString(),
      // For the full calendar's slider, over the same state as the dock's.
      window: () => timelineControl?.getWindow(),
      scrub: (ends) => timelineControl?.scrub(ends),
      release: () => timelineControl?.release(),
      setLive: (on) => timelineControl?.setLive(on),
    },
  });

  timelineControl = Timeline.createTimelineControl(
    document.getElementById('timeline-container'),
    {
      onChange: (range) => {
        if (!range) return;
        currentRange = range;
        calendar.paintRange();
        load();
      },
    }
  );
});
