//  Owns the current selection state and nothing else.

const statusLine = document.getElementById('status');

function setStatus(message) {
  statusLine.textContent = message ?? '';
  statusLine.hidden = !message;
}

let timelineControl = null;

// Turns a raw API error message into wording that matches the picker's own
// Start/End labels, rather than the API's internal from/to param names.
function humanizeError(message) {
  if (message.includes("must not be after")) {
    return "'Start time' must be before 'End time'.";
  }
  return message;
}

async function load(range) {
  setStatus('Loading positions...');

  try {
    const data = await getPositions({
      from: range?.from,
      to: range?.to,
    });
    const drawn = drawTracks(data.vehicles);

    if (drawn === 0) {
      timelineControl?.showNoData();
      setStatus('No positions to show.');
    } else {
      setStatus(null);
    }
  } catch (error) {
    // A failed request means there's no valid current selection -- the map
    // shouldn't keep showing whatever trail was drawn before this attempt.
    drawTracks([]);
    setStatus(humanizeError(error.message));
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initMap();

  timelineControl = Timeline.createTimelineControl(
    document.getElementById('timeline-container'),
    { onChange: (range) => { if (range) load(range); } }
  );
});