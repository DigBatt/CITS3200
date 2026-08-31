//  Owns the current selection state and nothing else.

const statusLine = document.getElementById('status');

function setStatus(message) {
  statusLine.textContent = message ?? '';
  statusLine.hidden = !message;
}

let timelineControl = null;

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
    setStatus(error.message);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initMap();

  timelineControl = Timeline.createTimelineControl(
    document.getElementById('timeline-container'),
    { onChange: (range) => { if (range) load(range); } }
  );
});