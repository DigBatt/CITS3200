// Timeline period control.
//
// Independent start and end date+time pickers, producing the from/to
// parameters in docs/api.md. Unlike a single-day picker, start and end can
// be on different days -- this is a full range, not "a day with times
// narrowed inside it".
//
// Defaults to today (00:00 start, live end) when the page loads.
// Perth does not observe daylight saving, so its UTC offset is always
// +08:00 -- no need to compute it per-date the way a DST-observing zone
// would require.
const PERTH_TZ = 'Australia/Perth';
const PERTH_OFFSET = '+08:00';

/**
 * The current calendar date in Perth local time, as "YYYY-MM-DD".
 *
 * Uses Intl rather than a hardcoded UTC+8 offset so this stays correct
 * even if WA's DST policy ever changes, and so it matches whatever the
 * backend's Australia/Perth zoneinfo handling does.
 */
function getPerthDateString(date = new Date()) {
  // en-CA locale formats as YYYY-MM-DD, which is what the API expects.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: PERTH_TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

/**
 * Combine a "YYYY-MM-DD" date and an "HH:mm" time into a full ISO instant
 * with the Perth offset attached, as params.py requires for any value that
 * isn't a bare date.
 */
function toApiValue(dateStr, timeStr) {
  const time = timeStr || '00:00';
  return `${dateStr}T${time}:00${PERTH_OFFSET}`;
}

/**
 * Mount a start/end date+time range control into `container`.
 *
 * Start and end are independent date+time pairs -- they are not assumed to
 * fall on the same day. An optional "live" checkbox lets the end be left
 * open, meaning "now"; when checked, the end date/time inputs are disabled
 * and `to` is reported as `null` so the caller omits it from the request
 * (the API then defaults `to` to now).
 *
 * @param {HTMLElement} container
 * @param {Object} [options]
 * @param {(range: { from: string, to: string|null, live: boolean }) => void} [options.onChange]
 *   Called whenever the selection changes, with from/to values ready to
 *   send to the API.
 * @returns {{ getRange: () => object, reset: () => void, showNoData: () => void }}
 */
function createTimelineControl(container, { onChange } = {}) {
  const todayStr = getPerthDateString();

  container.innerHTML = `
    <div class="timeline-control">
      <fieldset>
        <legend>Start</legend>
        <label for="timeline-start-date">Date</label>
        <input type="date" id="timeline-start-date" value="${todayStr}" max="${todayStr}">
        <label for="timeline-start-time">Time</label>
        <input type="time" id="timeline-start-time" value="00:00">
      </fieldset>

      <fieldset>
        <legend>End</legend>
        <label for="timeline-end-date">Date</label>
        <input type="date" id="timeline-end-date" value="${todayStr}" max="${todayStr}">
        <label for="timeline-end-time">Time</label>
        <input type="time" id="timeline-end-time" value="23:59">
        <label>
          <input type="checkbox" id="timeline-live">
          Live (end = now)
        </label>
      </fieldset>

      <p class="timeline-status" aria-live="polite"></p>
    </div>
  `;

  const startDateInput = container.querySelector('#timeline-start-date');
  const startTimeInput = container.querySelector('#timeline-start-time');
  const endDateInput = container.querySelector('#timeline-end-date');
  const endTimeInput = container.querySelector('#timeline-end-time');
  const liveCheckbox = container.querySelector('#timeline-live');
  const status = container.querySelector('.timeline-status');

  function clampFutureDate(input) {
    if (input.value > todayStr) {
      input.value = todayStr;
      status.textContent = 'Future dates are not available yet.';
      return true;
    }
    return false;
  }

  function currentRange() {
    const from = toApiValue(startDateInput.value, startTimeInput.value);
    const live = liveCheckbox.checked;
    const to = live ? null : toApiValue(endDateInput.value, endTimeInput.value);
    return { from, to, live };
  }

  function emitChange() {
    // Keep status limited to explaining the range itself; clear it here
    // unless a bad_range check below sets it.
    if (!liveCheckbox.checked) {
      const { from, to } = currentRange();
      if (from > to) {
        status.textContent = 'Start must be before end.';
        onChange?.(null);
        return;
      }
    }
    status.textContent = '';
    onChange?.(currentRange());
  }

  startDateInput.addEventListener('change', () => {
    clampFutureDate(startDateInput);
    emitChange();
  });
  startTimeInput.addEventListener('change', emitChange);

  endDateInput.addEventListener('change', () => {
    clampFutureDate(endDateInput);
    emitChange();
  });
  endTimeInput.addEventListener('change', emitChange);

  liveCheckbox.addEventListener('change', () => {
    endDateInput.disabled = liveCheckbox.checked;
    endTimeInput.disabled = liveCheckbox.checked;
    emitChange();
  });

  // Fire once immediately so the caller is told about the default range on
  // load, rather than only after the user changes something.
  emitChange();

  return {
    getRange: currentRange,
    reset: () => {
      startDateInput.value = todayStr;
      startTimeInput.value = '00:00';
      endDateInput.value = todayStr;
      endTimeInput.value = '23:59';
      endDateInput.disabled = false;
      endTimeInput.disabled = false;
      liveCheckbox.checked = false;
      status.textContent = '';
    },
    // Called by main.js when a fetch for the selected range comes back
    // empty, so "no data" is stated rather than an unexplained blank map.
    showNoData: () => {
      status.textContent = 'No data for this period.';
    },
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createTimelineControl, getPerthDateString };
}
if (typeof window !== 'undefined') {
  window.Timeline = { createTimelineControl, getPerthDateString };
}