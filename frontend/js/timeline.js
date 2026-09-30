// Timeline period control.
//
// Owns the selected period and turns it into the from/to parameters in
// docs/api.md. The days are chosen on the docked mini calendar, by dragging
// across them (js/calendar.js); this control sits underneath it with a Live
// button, which pins the end of the range to now and keeps refetching, and
// a Start and End time slider for the first and last day. The End slider is
// disabled while Live is on.
//
// A plain-language summary line states the resolved range -- that came out
// of testing feedback that an ignored End field looked broken.
//
// Defaults to live when the page loads, per S06's third criterion.
// Dates and times are chosen and displayed in Perth time; the API wants
// UTC instants, so everything is converted here before onChange fires.
// Perth is UTC+8 year round (docs/data-schema.md s4) -- WA has no DST --
// so the conversion below is fixed-offset arithmetic, not a real timezone
// library.

const PERTH_TZ = 'Australia/Perth';
const PERTH_UTC_OFFSET_HOURS = 8; // WA does not observe DST.
const DEFAULT_LIVE_POLL_MS = 15000; // matches config/app.yaml refresh_interval_seconds
const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// TEMPORARY dev convenience: defaults Start to the sample
// data's actual window instead of today, so tracks render immediately on
// load without needing to touch the picker first. Only the sample CSVs
// exist right now (no live telemetry yet) -- remove this once real
// position data is flowing in, reverting Start's default to today.
const DEV_DEFAULT_START_DATE = '2025-09-04';
const DEV_DEFAULT_START_TIME = '08:00';

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
  const [year, month, day] = dateStr.split('-').map(Number);
  const [hour, minute] = timeStr.split(':').map(Number);
  const period = hour < 12 ? 'am' : 'pm';
  const hour12 = ((hour + 11) % 12) + 1;
  return `${day} ${MONTH_ABBR[month - 1]} ${year}, ${hour12}:${String(minute).padStart(2, '0')} ${period}`;
}

const DAY_LAST_MINUTE = 1439;
// How often the map is refetched while a slider is being dragged. Often
// enough that the trail follows the thumb, not so often that it fires a
// request per pixel. main.js draws each response unless a newer one has
// already been drawn.
const SCRUB_THROTTLE_MS = 120;

const pad2 = (n) => String(n).padStart(2, '0');

/** "HH:MM" to minutes past midnight. */
function toMinutes(timeStr) {
  const [hour, minute] = timeStr.split(':').map(Number);
  return hour * 60 + minute;
}

/** Minutes past midnight to "HH:MM". */
function toTimeString(minutes) {
  return `${pad2(Math.floor(minutes / 60))}:${pad2(minutes % 60)}`;
}

/** "YYYY-MM-DD" to "4 Sep", for the slider labels. */
function formatShortDate(dateStr) {
  const [, month, day] = dateStr.split('-').map(Number);
  return `${day} ${MONTH_ABBR[month - 1]}`;
}

/**
 * Mount the period control into `container`: a Live button, and a Start and
 * an End time slider over the dates chosen on the mini calendar.
 *
 * The dates themselves are not picked here. The mini calendar calls
 * `setDates` when the operator drags across days, and reads `getDates` back
 * to paint the selection. The sliders then set the time of day on the first
 * and last of those days, and refetch as they move, so the trail and each
 * vehicle's end marker follow the thumb -- the End slider effectively scrubs
 * where the fleet was at that moment.
 *
 * Live pins the end of the range to now and keeps refetching. The End slider
 * is disabled while it is on, since there is no end time to choose.
 *
 * @param {HTMLElement} container
 * @param {Object} [options]
 * @param {(range: {from: string|null, to: string|null, live: boolean, scrub: boolean}) => void} [options.onChange]
 *   Called with the UTC `from`/`to` instants whenever the selection changes
 *   -- including once on mount with the default -- and on every live poll
 *   tick. `scrub` is true when a slider moved or a poll ticked, so the
 *   caller can redraw without refitting the map under the operator's hand.
 *   `dragging` is true for the updates fired while a slider thumb is still
 *   held, so the caller can keep them light.
 * @param {number} [options.livePollMs] - How often to re-fire onChange
 *   while live, so the caller can refetch. Defaults to 15s, matching
 *   config/app.yaml's refresh_interval_seconds.
 */
function createTimelineControl(container, { onChange, livePollMs = DEFAULT_LIVE_POLL_MS } = {}) {
  const state = {
    startDate: DEV_DEFAULT_START_DATE,
    startMin: toMinutes(DEV_DEFAULT_START_TIME),
    endDate: getPerthDateString(),
    endMin: toMinutes(getPerthTimeString()),
    live: true,
  };

  container.innerHTML = `
    <div class="timeline-control">
      <div class="timeline-head">
        <p class="timeline-summary" id="timeline-summary-text"></p>
        <button type="button" class="timeline-live-btn" id="timeline-live" title="Set the end of the range to now, and keep it there">
          <span class="timeline-live-dot" aria-hidden="true"></span>Live
        </button>
      </div>
      <label class="timeline-slider">
        <span class="timeline-slider-label">Start <small id="timeline-start-date"></small></span>
        <input type="range" id="timeline-start" min="0" max="${DAY_LAST_MINUTE}" step="1">
        <output class="timeline-slider-value" id="timeline-start-value" for="timeline-start"></output>
      </label>
      <label class="timeline-slider">
        <span class="timeline-slider-label">End <small id="timeline-end-date"></small></span>
        <input type="range" id="timeline-end" min="0" max="${DAY_LAST_MINUTE}" step="1">
        <output class="timeline-slider-value" id="timeline-end-value" for="timeline-end"></output>
      </label>
      <p class="timeline-status" aria-live="polite"></p>
    </div>
  `;

  const summaryText = container.querySelector('#timeline-summary-text');
  const liveButton = container.querySelector('#timeline-live');
  const liveDot = container.querySelector('.timeline-live-dot');
  const startSlider = container.querySelector('#timeline-start');
  const endSlider = container.querySelector('#timeline-end');
  const startDateLabel = container.querySelector('#timeline-start-date');
  const endDateLabel = container.querySelector('#timeline-end-date');
  const startValue = container.querySelector('#timeline-start-value');
  const endValue = container.querySelector('#timeline-end-value');
  const status = container.querySelector('.timeline-status');

  let pollHandle = null;
  let scrubHandle = null;
  let lastScrubAt = 0;

  const today = () => getPerthDateString();
  const nowMinutes = () => toMinutes(getPerthTimeString());
  // Where the range actually ends: now while live, the End slider otherwise.
  const effectiveEnd = () =>
    state.live ? { date: today(), min: nowMinutes() } : { date: state.endDate, min: state.endMin };

  function currentRange() {
    const from = perthToUtcIso(state.startDate, toTimeString(state.startMin));
    // Live sends no `to` at all and lets the server default apply
    // (docs/api.md), so every poll genuinely reaches the latest data rather
    // than replaying a stale "now". Otherwise the End minute is inclusive.
    const to = state.live ? null : perthToUtcIso(state.endDate, `${toTimeString(state.endMin)}:59`);
    return { from, to, live: state.live };
  }

  function render() {
    const end = effectiveEnd();
    summaryText.textContent =
      `${formatDisplay(state.startDate, toTimeString(state.startMin))} → ${formatDisplay(end.date, toTimeString(end.min))}`;

    startSlider.value = state.startMin;
    startValue.textContent = toTimeString(state.startMin);
    startDateLabel.textContent = formatShortDate(state.startDate);

    endSlider.value = end.min;
    endSlider.disabled = state.live;
    endValue.textContent = state.live ? 'now' : toTimeString(end.min);
    endDateLabel.textContent = formatShortDate(end.date);

    liveButton.classList.toggle('is-on', state.live);
    liveButton.setAttribute('aria-pressed', String(state.live));
    liveDot.hidden = !state.live;
  }

  function emit(scrub = false, dragging = false) {
    clearTimeout(scrubHandle);
    scrubHandle = null;
    status.textContent = '';
    render();
    onChange?.({ ...currentRange(), scrub, dragging });
  }

  function syncPolling() {
    if (pollHandle !== null) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
    if (state.live) pollHandle = setInterval(() => emit(true), livePollMs);
  }

  // The start may not pass the end, and neither may run past now: nothing
  // after now exists yet. Only matters when they share a day, or it is today.
  function clampStart(minutes) {
    const end = effectiveEnd();
    let max = state.startDate === today() ? nowMinutes() : DAY_LAST_MINUTE;
    if (state.startDate === end.date) max = Math.min(max, end.min - 1);
    return Math.max(0, Math.min(minutes, max));
  }

  function clampEnd(minutes) {
    const min = state.startDate === state.endDate ? state.startMin + 1 : 0;
    const max = state.endDate === today() ? nowMinutes() : DAY_LAST_MINUTE;
    return Math.max(min, Math.min(minutes, max));
  }

  function onSlide(slider, key, clamp) {
    // Moving the thumb redraws the labels at once and refetches as it goes,
    // at most once per SCRUB_THROTTLE_MS. A trailing update catches the last
    // position, and letting go refetches straight away.
    slider.addEventListener('input', () => {
      state[key] = clamp(Number(slider.value));
      render();
      clearTimeout(scrubHandle);
      const wait = SCRUB_THROTTLE_MS - (Date.now() - lastScrubAt);
      const fire = () => {
        lastScrubAt = Date.now();
        emit(true, true);
      };
      if (wait <= 0) fire();
      else scrubHandle = setTimeout(fire, wait);
    });
    slider.addEventListener('change', () => emit(true));
  }

  onSlide(startSlider, 'startMin', clampStart);
  onSlide(endSlider, 'endMin', clampEnd);

  function setLive(on) {
    state.live = on;
    // Either way the range now ends today: switching Live off leaves the
    // End slider at the moment it was switched off, ready to be dragged back.
    state.endDate = today();
    state.endMin = nowMinutes();
    state.startMin = clampStart(state.startMin);
    syncPolling();
    emit();
  }

  liveButton.addEventListener('click', () => setLive(!state.live));

  /**
   * Take a new pair of Perth dates, as the mini calendar hands them over.
   * The times open out to the whole of both days so nothing chosen is
   * hidden at first; the sliders narrow it from there. Live survives only a
   * range that still ends today.
   */
  function setDates(startDate, endDate) {
    const todayStr = today();
    if (startDate > endDate) [startDate, endDate] = [endDate, startDate];
    let clamped = false;
    if (endDate > todayStr) { endDate = todayStr; clamped = true; }
    if (startDate > todayStr) { startDate = todayStr; clamped = true; }

    state.startDate = startDate;
    state.endDate = endDate;
    state.live = state.live && endDate === todayStr;
    state.endMin = endDate === todayStr ? nowMinutes() : DAY_LAST_MINUTE;
    state.startMin = clampStart(0);
    syncPolling();
    emit();
    if (clamped) status.textContent = 'Future dates are not available yet.';
  }

  syncPolling();
  // Fire once immediately so the caller is told about the default on load,
  // per S06's third criterion -- otherwise onChange only fires after the
  // user manually changes something.
  emit();

  return {
    getRange: currentRange,
    // The chosen days as Perth "YYYY-MM-DD", for the mini calendar to paint.
    getDates: () => ({ start: state.startDate, end: effectiveEnd().date, live: state.live }),
    setDates,
    setLive,
    reset: () => {
      state.startDate = DEV_DEFAULT_START_DATE;
      state.startMin = toMinutes(DEV_DEFAULT_START_TIME);
      setLive(true);
    },
    // Called by main.js when a fetch for the selected range comes back
    // empty, so "no data" is stated rather than an unexplained blank map
    // (S06 AC2, docs/api.md).
    showNoData: () => {
      status.textContent = 'No data for this period.';
    },
    // Called by main.js once a fetch comes back with data, e.g. after the
    // vehicle filter changes, so an earlier "no data" does not linger.
    clearStatus: () => {
      status.textContent = '';
    },
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createTimelineControl, getPerthDateString, getPerthTimeString, perthToUtcIso, formatDisplay };
}
if (typeof window !== 'undefined') {
  window.Timeline = { createTimelineControl, getPerthDateString, getPerthTimeString, perthToUtcIso, formatDisplay };
}