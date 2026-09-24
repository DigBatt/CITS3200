// Rider view: choose a stop and ask to be collected (S08).
//
// Stops are read from /api/stops, so one added to config/stops.yaml appears
// here after a restart with no code change. The request itself is anonymous:
// the API sets a rider_token cookie on the first request, which is what lets
// it recognise a repeat request at the same stop.

document.addEventListener('DOMContentLoaded', () => {
  const select = document.getElementById('rider-stop-select');
  const button = document.getElementById('rider-request-button');
  const buttonSub = document.getElementById('rider-request-sub');
  const status = document.getElementById('rider-status');

  if (!select || !button || !buttonSub || !status) return;

  function showStatus(message, kind) {
    status.textContent = message;
    status.className = `rider-status is-${kind}`;
    status.hidden = false;
  }

  function clearStatus() {
    status.hidden = true;
  }

  // ---- Fill the picker ----

  async function loadStops() {
    try {
      const { stops } = await getStops();

      if (!stops.length) {
        select.innerHTML = '<option value="">No stops configured</option>';
        buttonSub.textContent = 'No stops configured';
        return;
      }

      select.innerHTML = '<option value="">Choose a stop&hellip;</option>';
      stops.forEach((stop) => {
        const option = document.createElement('option');
        option.value = stop.id;
        option.textContent = stop.name;
        select.appendChild(option);
      });
      select.disabled = false;
    } catch (error) {
      select.innerHTML = '<option value="">Could not load stops</option>';
      buttonSub.textContent = 'Could not load stops';
      showStatus(error.message, 'error');
    }
  }

  // ---- Submit ----

  select.addEventListener('change', () => {
    const chosen = Boolean(select.value);
    button.disabled = !chosen;
    buttonSub.textContent = chosen
      ? select.options[select.selectedIndex].textContent
      : 'Choose a stop first';
    clearStatus();
  });

  button.addEventListener('click', async () => {
    const stopId = select.value;
    if (!stopId) return;

    const stopName = select.options[select.selectedIndex].textContent;

    button.disabled = true;
    buttonSub.textContent = 'Sending\u2026';

    try {
      const { created } = await createPickupRequest(stopId);
      showStatus(
        created
          ? `The shuttle knows you're waiting at ${stopName}.`
          : `You already have a request open at ${stopName}.`,
        'ok',
      );
    } catch (error) {
      showStatus(error.message, 'error');
    } finally {
      button.disabled = false;
      buttonSub.textContent = stopName;
    }
  });

  loadStops();
});