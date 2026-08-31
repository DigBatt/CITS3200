//  Owns the current selection state and nothing else.


const statusLine = document.getElementById('status');

function setStatus(message) {
  statusLine.textContent = message ?? '';
  statusLine.hidden = !message;
}

async function load() {
  initMap();
  setStatus('Loading positions...');

  try {
    const data = await getPositions();
    const drawn = drawTracks(data.vehicles);
    setStatus(drawn === 0 ? 'No positions to show.' : null);
  } catch (error) {
    setStatus(error.message);
  }
}

document.addEventListener('DOMContentLoaded', load);
