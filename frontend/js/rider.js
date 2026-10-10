// Rider view: choose a stop, ask to be collected, and track that request
// through to pickup, review or cancellation (S08, S15).
//
// Stops are read from /api/stops, so one added to config/stops.json appears
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
    closed: document.getElementById('rider-closed'),
    closedNote: document.getElementById('rider-closed-note'),
    waiting: document.getElementById('rider-waiting'),
    waitingStop: document.getElementById('rider-waiting-stop'),
    cancelButton: document.getElementById('rider-cancel-button'),
    collected: document.getElementById('rider-collected'),
    reviewButton: document.getElementById('rider-review-button'),
    reviewDecline: document.getElementById('rider-review-decline'),
    reviewForm: document.getElementById('rider-review-form'),
    reviewSkip: document.getElementById('rider-review-skip'),
    status: document.getElementById('rider-status'),
  };

  if (!els.select || !els.button) return; // the rider panel is not on this page

  const POLL_MS = 5000;

  let pollTimer = null;
  let currentRequestId = null;
  let activeStopId = null; // the stop shown alone on the map, or null for every stop

  // ---- Shuttle hours (S15 follow-up): a "closed" message in place of the
  // picker outside pickup_requests.operating_hours. Checked far less often
  // than the request poll above, since hours change at most a couple of
  // times a day, not every few seconds.
  const HOURS_POLL_MS = 60000;
  let hoursInfo = null;

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
    els.closed.hidden = name !== 'closed';
    els.waiting.hidden = name !== 'waiting';
    els.collected.hidden = name !== 'collected';
  }

  // ---- Shuttle hours (S15 follow-up) ----
  //
  // Only the idle state (no active request) is ever replaced by "closed":
  // a request already waiting or collected plays out regardless of hours
  // that close mid-ride.

  function describeHours(info) {
    if (info.today_hours) {
      const [open, close] = info.today_hours;
      return `Pickup requests open today from ${open} to ${close}.`;
    }
    return 'No shuttle service today. Check back on the next service day.';
  }

  function renderIdleView() {
    if (hoursInfo && !hoursInfo.open_now) {
      els.closedNote.textContent = describeHours(hoursInfo);
      showView('closed');
    } else {
      showView('picker');
    }
  }

  async function checkHours() {
    try {
      hoursInfo = await getPickupRequestHours();
    } catch (error) {
      console.warn(`Could not check shuttle hours: ${error.message}`);
      return;
    }
    if (currentRequestId === null) renderIdleView();
  }

  function showWaiting(pickupRequest) {
    currentRequestId = pickupRequest.id;
    els.waitingStop.textContent = pickupRequest.stop_id;
    showView('waiting');
    setActiveStop(pickupRequest.stop_id);
  }

  function showCollected(pickupRequest) {
    currentRequestId = pickupRequest.id;
    // Fresh every time: the button offers the review again, the form (and
    // whatever was typed into it) is reset and hidden until asked for.
    els.reviewButton.hidden = false;
    els.reviewDecline.hidden = false;
    els.reviewForm.hidden = true;
    els.reviewForm.reset();
    prefillProfile();
    clearStatus(); // "The shuttle knows you're waiting..." no longer applies
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
    renderIdleView();
    showStatus(message, kind);
  }

  // ---- Map: isolate to the stop the rider currently cares about (S15) ----

  function setActiveStop(stopId) {
    activeStopId = stopId;
    syncMapIsolation();
  }

  // Re-applied by panels.js whenever the Rider tab becomes active again.
  // Leaving the tab already restores every stop itself (map.js is shared
  // with Fleet), so this only isolates while Rider is the one actually
  // showing — background polling must not hide stops on another tab.
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
      checkHours(); // hours may have just closed between loading the picker and clicking
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

  // ---- Review (S15 follow-up) ----
  //
  // "Leave a review" reveals the form in place of the buttons; "Not today",
  // the form's "Not now" or a successful submit all return to the picker,
  // ready for the next trip.
  // vehicle_id, route_id and wait_minutes are not asked here -- the server
  // reads them off the pickup request itself (backend/api/reviews.py).

  // Demographics the rider answers once and this remembers for next time
  // (within the cookie's lifetime, same as the rider_token cookie's), rather
  // than asking again on every review.
  const PROFILE_COOKIE = 'rider_profile';
  const PROFILE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // ~1 year
  const PROFILE_FIELDS = ['role', 'usage_frequency'];

  function rememberProfile(form) {
    try {
      const profile = Object.fromEntries(PROFILE_FIELDS.map((field) => [field, form.elements[field].value]));
      const value = encodeURIComponent(JSON.stringify(profile));
      document.cookie = `${PROFILE_COOKIE}=${value}; max-age=${PROFILE_COOKIE_MAX_AGE}; path=/; samesite=lax`;
    } catch (error) {
      /* storage unavailable */
    }
  }

  function recallProfile() {
    try {
      const match = document.cookie.match(new RegExp(`(?:^|; )${PROFILE_COOKIE}=([^;]*)`));
      return match ? JSON.parse(decodeURIComponent(match[1])) : null;
    } catch (error) {
      return null;
    }
  }

  function prefillProfile() {
    const profile = recallProfile();
    if (!profile) return;
    PROFILE_FIELDS.forEach((field) => {
      if (profile[field]) els.reviewForm.elements[field].value = profile[field];
    });
  }

  // A "120 / 1000" counter under each comment box, red once the box is full.
  // The limit is the textarea's own maxlength, which matches the server's
  // MAX_COMMENT_LENGTH (backend/api/reviews.py).
  els.reviewForm?.querySelectorAll('textarea[maxlength]').forEach((textarea, index) => {
    const counter = document.createElement('span');
    counter.className = 'review-count';
    counter.id = `review-count-${index}`;
    textarea.setAttribute('aria-describedby', counter.id);
    textarea.after(counter);

    const update = () => {
      const full = textarea.value.length >= textarea.maxLength;
      counter.textContent = full
        ? `${textarea.maxLength} character limit reached`
        : `${textarea.value.length} / ${textarea.maxLength}`;
      counter.classList.toggle('is-full', full);
    };
    textarea.addEventListener('input', update);
    // reset fires before the fields clear, so count once they have.
    els.reviewForm.addEventListener('reset', () => setTimeout(update));
    update();
  });

  // The required ratings say what is missing in red under each one, rather
  // than the browser's own one-at-a-time bubble (the form is novalidate; the
  // radios keep `required` so assistive tech still announces them as such).
  const ratingGroups = [...(els.reviewForm?.querySelectorAll('.review-rating') ?? [])].map((group, index) => {
    const field = group.closest('.review-field');
    const error = document.createElement('span');
    error.className = 'review-error';
    error.id = `review-error-${index}`;
    error.textContent = 'Please choose a rating from 1 to 5.';
    error.setAttribute('aria-live', 'polite');
    error.hidden = true;
    group.after(error);

    const inputs = [...group.querySelectorAll('input[type="radio"]')];
    inputs.forEach((input) => input.setAttribute('aria-describedby', error.id));

    const setInvalid = (invalid) => {
      field.classList.toggle('is-invalid', invalid);
      error.hidden = !invalid;
      inputs.forEach((input) => input.setAttribute('aria-invalid', String(invalid)));
    };
    group.addEventListener('change', () => setInvalid(false));
    return { inputs, setInvalid };
  });

  // Marks every unanswered rating at once and moves to the first. True when
  // nothing required is missing.
  function checkRatings() {
    const missing = ratingGroups.filter(({ inputs }) => !inputs.some((input) => input.checked));
    ratingGroups.forEach((group) => group.setInvalid(missing.includes(group)));
    if (missing.length) {
      missing[0].inputs[0].focus({ preventScroll: true });
      missing[0].inputs[0].closest('.review-field').scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    return missing.length === 0;
  }

  els.reviewForm?.addEventListener('reset', () => ratingGroups.forEach((group) => group.setInvalid(false)));

  // Pickups this browser is done with -- reviewed, or the review declined --
  // so a reload does not offer the review again. Only the latest few are
  // kept, since only the rider's most recent pickup is ever shown. The
  // server refuses a second review regardless (409 already_reviewed).
  const FINISHED_KEY = 'rider_finished_pickups';
  const FINISHED_KEEP = 20;

  function finishedPickups() {
    try {
      return JSON.parse(localStorage.getItem(FINISHED_KEY) ?? '[]');
    } catch (error) {
      return [];
    }
  }

  function markFinished(requestId) {
    try {
      const ids = [...finishedPickups().filter((id) => id !== requestId), requestId].slice(-FINISHED_KEEP);
      localStorage.setItem(FINISHED_KEY, JSON.stringify(ids));
    } catch (error) {
      /* storage unavailable: the review is just offered again on reload */
    }
  }

  function declineReview(message) {
    if (currentRequestId) markFinished(currentRequestId);
    resetToPicker(message, 'ok');
  }

  els.reviewButton?.addEventListener('click', () => {
    els.reviewButton.hidden = true;
    els.reviewDecline.hidden = true;
    els.reviewForm.hidden = false;
  });

  els.reviewDecline?.addEventListener('click', () => declineReview('Thanks for riding nuway!'));

  els.reviewSkip?.addEventListener('click', () => declineReview('Thanks for riding nuway!'));

  els.reviewForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!checkRatings() || !currentRequestId) return; // the two ratings are required

    const submitButton = document.getElementById('rider-review-submit');
    submitButton.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(els.reviewForm).entries());
      await submitReview({ pickup_request_id: currentRequestId, ...data });
      markFinished(currentRequestId);
      rememberProfile(els.reviewForm);
      resetToPicker('Thanks for the feedback!', 'ok');
    } catch (error) {
      showStatus(error.message, 'error'); // stay on the form: nothing typed is lost
    } finally {
      submitButton.disabled = false;
    }
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
      // Already reviewed or declined here: stay on the picker, quietly.
      if (!finishedPickups().includes(pickupRequest.id)) showCollected(pickupRequest);
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

  checkHours();
  setInterval(checkHours, HOURS_POLL_MS);
  loadStops().then(checkMyRequest);
});
