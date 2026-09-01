// Timeline period control.
//
// A start/end date+time picker, plus a "Live" toggle that pins the end of
// the range to now and keeps refetching, producing the from/to parameters
// in docs/api.md.
//
// While Live is on, the End row is hidden rather than just disabled, and a
// plain-language summary line states the resolved range -- both came out
// of testing feedback that a greyed-out End field still showing a stale
// date looked broken even when it was correctly being ignored.
//
// Defaults to today, live, when the page loads, per S06's third criterion.
// Dates and times are chosen and displayed in Perth time; the API wants
// UTC instants, so everything is converted here before onChange fires.
// Perth is UTC+8 year round (docs/data-schema.md s4) -- WA has no DST --
// so the conversion below is fixed-offset arithmetic, not a real timezone
// library.

const PERTH_TZ = 'Australia/Perth';
const PERTH_UTC_OFFSET_HOURS = 8; // WA does not observe DST.
const DEFAULT_LIVE_POLL_MS = 15000; // matches config/app.yaml refresh_interval_seconds
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

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
 * The current wall clock time in Perth, as "HH:MM".
 */
function getPerthTimeString(date = new Date()) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: PERTH_TZ,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
}

/**
 * Combine a Perth-local date and time into the UTC instant the API wants.
 *
 * Perth's offset is a fixed +8 all year, so this is arithmetic: subtract
 * 8 hours from the wall clock value and read the result back as UTC.
 * `Date.UTC` normalises an hour that goes negative or past 24, rolling
 * the calendar date over as needed, so no manual day-boundary handling
 * is needed here.
 *
 * @param {string} dateStr - "YYYY-MM-DD" in Perth time.
 * @param {string} [timeStr] - "HH:MM" or "HH:MM:SS" in Perth time.
 *   Defaults to midnight.
 * @returns {string|null} An ISO 8601 UTC instant ending in "Z", or `null`
 *   if `dateStr` is blank.
 */
function perthToUtcIso(dateStr, timeStr = '00:00') {
  if (!dateStr) return null;

  const [year, month, day] = dateStr.split('-').map(Number);
  const [hour, minute, second = 0] = timeStr.split(':').map(Number);

  const utcMs = Date.UTC(year, month - 1, day, hour - PERTH_UTC_OFFSET_HOURS, minute, second);
  return new Date(utcMs).toISOString();
}

/**
 * Format a Perth-local date+time for the plain-language summary line, e.g.
 * "4 Sep, 4:21 pm". Purely cosmetic -- perthToUtcIso (not this) is what
 * actually produces the value sent to the API.
 */
function formatDisplay(dateStr, timeStr) {
  if (!dateStr) return '';
  const [, month, day] = dateStr.split('-').map(Number);
  const [hour, minute] = timeStr.split(':').map(Number);
  const period = hour < 12 ? 'am' : 'pm';
  const hour12 = ((hour + 11) % 12) + 1;
  return `${day} ${MONTH_ABBR[month - 1]}, ${hour12}:${String(minute).padStart(2, '0')} ${period}`;
}

/**
 * Mount a start/end date-time range picker into `container`, with a "Live"
 * toggle for the end of the range.
 *
 * @param {HTMLElement} container
 * @param {Object} [options]
 * @param {(range: {from: string|null, to: string|null, live: boolean}) => void} [options.onChange]
 *   Called with the UTC `from`/`to` instants (`null` when a field is blank)
 *   whenever the selection changes -- including once on mount with the
 *   default (today, live) -- and on every live poll tick.
 * @param {number} [options.livePollMs] - How often to re-fire onChange
 *   while live, so the caller can refetch. Defaults to 15s, matching
 *   config/app.yaml's refresh_interval_seconds.
 * @returns {{
 *   getRange: () => {from: string|null, to: string|null, live: boolean},
 *   reset: () => void,
 *   showNoData: () => void
 * }}
 */
function createTimelineControl(container, { onChange, livePollMs = DEFAULT_LIVE_POLL_MS } = {}) {
  const todayStr = getPerthDateString();
  const nowStr = getPerthTimeString();

  container.innerHTML = `
    <div class="timeline-control">
      <div class="timeline-row">
        <span class="timeline-row-label">Start</span>
        <input type="date" id="timeline-start-date" value="${todayStr}" max="${todayStr}" autocomplete="off">
        <input type="time" id="timeline-start-time" value="00:00" autocomplete="off">
      </div>
      <div class="timeline-row" id="timeline-end-row">
        <span class="timeline-row-label">End</span>
        <input type="date" id="timeline-end-date" value="${todayStr}" max="${todayStr}" autocomplete="off">
        <input type="time" id="timeline-end-time" value="${nowStr}" autocomplete="off">
      </div>
      <label class="timeline-live">
        <span class="timeline-switch">
          <input type="checkbox" id="timeline-live" checked>
          <span class="timeline-switch-track"></span>
          <span class="timeline-switch-knob"></span>
        </span>
        <span>Live (end = now)</span>
        <span class="timeline-live-dot" aria-hidden="true"></span>
      </label>
      <p class="timeline-summary">Showing <strong id="timeline-summary-text"></strong></p>
      <p class="timeline-status" aria-live="polite"></p>
    </div>
  `;

  const startDate = container.querySelector('#timeline-start-date');
  const startTime = container.querySelector('#timeline-start-time');
  const endDate = container.querySelector('#timeline-end-date');
  const endTime = container.querySelector('#timeline-end-time');
  const endRow = container.querySelector('#timeline-end-row');
  const liveToggle = container.querySelector('#timeline-live');
  const liveDot = container.querySelector('.timeline-live-dot');
  const summaryText = container.querySelector('#timeline-summary-text');
  const status = container.querySelector('.timeline-status');

  let pollHandle = null;

  function currentRange() {
    const from = perthToUtcIso(startDate.value, startTime.value);
    // Live ignores whatever sits in the (hidden) end inputs and means
    // "now": send no `to` at all and let the server default apply
    // (docs/api.md), so every poll genuinely reaches the latest data
    // rather than replaying a stale "now" captured when the toggle was
    // switched on.
    const to = liveToggle.checked ? null : perthToUtcIso(endDate.value, endTime.value);
    return { from, to, live: liveToggle.checked };
  }

  function updateSummary() {
    const startDisplay = formatDisplay(startDate.value, startTime.value);
    // Real current date/time, not the word "now" -- refreshes on every
    // poll tick while Live is on, so the summary visibly advances rather
    // than sitting static.
    const endDisplay = liveToggle.checked
      ? formatDisplay(getPerthDateString(), getPerthTimeString())
      : formatDisplay(endDate.value, endTime.value);
    summaryText.textContent = `${startDisplay} \u2192 ${endDisplay}`;
  }

  function emit() {
    status.textContent = '';
    updateSummary();
    onChange?.(currentRange());
  }

  function stopPolling() {
    if (pollHandle !== null) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
  }

  function syncLiveState() {
    const isLive = liveToggle.checked;
    // Hidden, not just disabled -- a greyed-out End field still showing a
    // stale date reads as broken even when it's correctly being ignored
    // (see the timeline-picker-redesign discussion).
    endRow.hidden = isLive;
    endDate.disabled = isLive;
    endTime.disabled = isLive;
    liveDot.hidden = !isLive;
    stopPolling();
    if (isLive) {
      pollHandle = setInterval(emit, livePollMs);
    }
  }

  function guardFutureDate(input) {
    if (input.value > todayStr) {
      input.value = todayStr;
      status.textContent = 'Future dates are not available yet.';
    }
  }

  startDate.addEventListener('change', () => { guardFutureDate(startDate); emit(); });
  startTime.addEventListener('change', emit);
  endDate.addEventListener('change', () => { guardFutureDate(endDate); emit(); });
  endTime.addEventListener('change', emit);
  liveToggle.addEventListener('change', () => { syncLiveState(); emit(); });

  syncLiveState();
  // Fire once immediately so the caller is told about the default (today,
  // live) on load, per S06's third criterion -- otherwise onChange only
  // fires after the user manually changes something.
  emit();

  return {
    getRange: currentRange,
    reset: () => {
      startDate.value = todayStr;
      startTime.value = '00:00';
      endDate.value = todayStr;
      endTime.value = getPerthTimeString();
      liveToggle.checked = true;
      syncLiveState();
      emit();
    },
    // Called by main.js when a fetch for the selected range comes back
    // empty, so "no data" is stated rather than an unexplained blank map
    // (S06 AC2, docs/api.md).
    showNoData: () => {
      status.textContent = 'No data for this period.';
    },
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createTimelineControl, getPerthDateString, getPerthTimeString, perthToUtcIso, formatDisplay };
}
if (typeof window !== 'undefined') {
  window.Timeline = { createTimelineControl, getPerthDateString, getPerthTimeString, perthToUtcIso, formatDisplay };
}