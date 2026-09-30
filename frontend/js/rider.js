// Rider view: choose a stop, ask to be collected, and track that request
// through to pickup or cancellation (S08, S15).
//
// Stops are read from /api/stops, so one added to config/stops.yaml appears
// here after a restart with no code change. The request itself is anonymous:
// the API sets a rider_token cookie on the first request, which is what lets
// it recognise a repeat request at the same stop, and what GET
// /api/pickup-requests/mine uses to answer only with this rider's own
// request, never the admin-only full list (S13).

document.addEventListener('DOMContentLoaded', () => {
  const els = {
    picker: document.getElementById('rider-picker'),
    select: document.getElementById('rider-stop-select'),
    button: document.getElementById('rider-request-button'),
    buttonSub: document.getElementById('rider-request-sub'),
    waiting: document.getElementById('rider-waiting'),
    waitingStop: document.getElementById('rider-waiting-stop'),
    cancelButton: document.getElementById('rider-cancel-button'),
    collected: document.getElementById('rider-collected'),
    reviewButton: document.getElementById('rider-review-button'),
    status: document.getElementById('rider-status'),
  };

  if (!els.select || !els.button) return; // the rider panel is not on this page

  const POLL_MS = 5000;

  let pollTimer = null;
  let currentRequestId = null;
  let activeStopId = null; // the stop shown alone on the map, or null for every stop

  function showStatus(message, kind) {
    els.status.textContent = message;
    els.status.className = `rider-status is-${kind}`;
    els.status.hidden = false;
  }

  function clearStatus() {
    els.status.hidden = true;
  }

  // ---- View state: picker / waiting / collected ----

  function showView(name) {
    els.picker.hidden = name !== 'picker';
    els.waiting.hidden = name !== 'waiting';
    els.collected.hidden = name !== 'collected';
  }

  function showWaiting(pickupRequest) {
    currentRequestId = pickupRequest.id;
    els.waitingStop.textContent = pickupRequest.stop_id;
    showView('waiting');
    setActiveStop(pickupRequest.stop_id);
  }

  function showCollected(pickupRequest) {
    currentRequestId = pickupRequest.id;
    showView('collected');
    setActiveStop(pickupRequest.stop_id);
  }

  function resetToPicker(message, kind) {
    stopPolling();
    currentRequestId = null;
    setActiveStop(null);
    els.select.value = '';
    els.button.disabled = true;
    els.buttonSub.textContent = 'Choose a stop first';
    showView('picker');
    showStatus(message, kind);
  }

  // ---- Map: isolate to the stop the rider currently cares about (S15) ----

  function setActiveStop(stopId) {
    activeStopId = stopId;
    syncMapIsolation();
  }

  // Re-applied by panels.js whenever the Rider tab becomes active again.
  // Leaving the tab already restores every stop itself (map.js is shared
  // with Fleet and Operator), so this only isolates while Rider is the one
  // actually showing — background polling must not hide stops on another tab.
  function syncMapIsolation() {
    const riderTabIsActive = document.getElementById('panel-rider')?.hidden === false;
    isolateStop(riderTabIsActive ? activeStopId : null);
  }

  // ---- Fill the picker ----

  async function loadStops() {
    try {
      const { stops } = await getStops();

      if (!stops.length) {
        els.select.innerHTML = '<option value="">No stops configured</option>';
        els.buttonSub.textContent = 'No stops configured';
        return;
      }

      // Ids, not names (S15): the map labels and the operator view already
      // read by id, so the picker matches rather than making the rider
      // translate between a name here and an id everywhere else.
      els.select.innerHTML = '<option value="">Choose a stop&hellip;</option>';
      stops.forEach((stop) => {
        const option = document.createElement('option');
        option.value = stop.id;
        option.textContent = stop.id;
        els.select.appendChild(option);
      });
      els.select.disabled = false;
    } catch (error) {
      els.select.innerHTML = '<option value="">Could not load stops</option>';
      els.buttonSub.textContent = 'Could not load stops';
      showStatus(error.message, 'error');
    }
  }

  // ---- Picking a stop (S15): isolate the map to it and open its popup ----

  els.select.addEventListener('change', () => {
    const stopId = els.select.value || null;
    els.button.disabled = !stopId;
    els.buttonSub.textContent = stopId ?? 'Choose a stop first';
    clearStatus();
    setActiveStop(stopId);
    if (stopId) openStopPopup(stopId);
  });

  // ---- Submit ----

  els.button.addEventListener('click', async () => {
    const stopId = els.select.value;
    if (!stopId) return;

    els.button.disabled = true;
    els.buttonSub.textContent = 'Sending…';

    try {
      const { request: pickupRequest, created } = await createPickupRequest(stopId);
      showWaiting(pickupRequest);
      startPolling();
      showStatus(
        created
          ? `The shuttle knows you're waiting at ${stopId}.`
          : `You already have a request open at ${stopId}.`,
        'ok',
      );
    } catch (error) {
      showStatus(error.message, 'error');
      els.button.disabled = false;
      els.buttonSub.textContent = stopId;
    }
  });

  // ---- Cancel (S15) ----

  els.cancelButton?.addEventListener('click', async () => {
    if (!currentRequestId) return;
    const stopId = els.waitingStop.textContent;

    els.cancelButton.disabled = true;
    try {
      await cancelPickupRequest(currentRequestId);
      resetToPicker(`Cancelled your request at ${stopId}.`, 'ok');
    } catch (error) {
      showStatus(error.message, 'error'); // stay in the waiting view: it's still open
    } finally {
      els.cancelButton.disabled = false;
    }
  });

  // ---- Review (S15): a stub. There is no review feature yet, only the
  // trigger to show this button once a request is collected; dismissing it
  // returns the rider to the picker for their next trip. ----

  els.reviewButton?.addEventListener('click', () => {
    resetToPicker("Thanks for riding nuway! (We're not collecting reviews yet.)", 'ok');
  });

  // ---- Poll the rider's own request (S15) ----
  //
  // Admin sign-in gates the full list (S13), so the rider view can only ever
  // ask about its own request, via GET /api/pickup-requests/mine.

  async function checkMyRequest() {
    let pickupRequest = null;
    try {
      ({ request: pickupRequest } = await getMyPickupRequest());
    } catch (error) {
      // A blip here should not interrupt whatever is currently shown; the
      // next poll tries again.
      console.warn(`Could not check pickup request status: ${error.message}`);
      return;
    }

    if (!pickupRequest) return; // nothing of the rider's on record

    if (pickupRequest.status === 'open') {
      showWaiting(pickupRequest);
      startPolling();
      return;
    }

    stopPolling();
    if (pickupRequest.status === 'collected') {
      showCollected(pickupRequest);
    } else {
      // expired, or cancelled from another tab or device mid-wait.
      resetToPicker(`Your request at ${pickupRequest.stop_id} ${pickupRequest.status}.`, 'error');
    }
  }

  function startPolling() {
    if (pollTimer) return; // already running
    pollTimer = setInterval(checkMyRequest, POLL_MS);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  // Catch up straight away when a backgrounded tab/phone is woken.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && pollTimer) checkMyRequest();
  });

  window.Rider = { syncMapIsolation };

  loadStops().then(checkMyRequest);
});
