// Timeline period control.
//
// Owns the selected period and turns it into the from/to parameters in
// docs/api.md. The days are chosen on a calendar, by dragging across them
// (js/calendar.js, both the docked mini month and the full calendar's
// dropdown); this control sits under the mini month with a Live button,
// which pins the end of the range to now and keeps refetching, and a Start
// and End time slider. The full calendar has its own slider over the same
// state. End sliders are disabled while Live is on.
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
const MINUTE_MS = 60000;
const HOUR_MS = 60 * MINUTE_MS;
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

/** The UTC instant, in ms, of midnight starting a Perth date. */
function perthDayStartMs(dateStr) {
  const [year, month, day] = dateStr.split('-').map(Number);
  return Date.UTC(year, month - 1, day, -PERTH_UTC_OFFSET_HOURS);
}

/** A UTC instant in ms as a Perth date and minute of the day. */
function toPerth(ms) {
  const shifted = new Date(ms + PERTH_UTC_OFFSET_HOURS * HOUR_MS);
  return {
    date: shifted.toISOString().slice(0, 10),
    min: shifted.getUTCHours() * 60 + shifted.getUTCMinutes(),
  };
}

/** A UTC instant in ms for the summary line, e.g. "4 Sep 2025, 4:21 pm". */
function formatInstant(ms) {
  const { date, min } = toPerth(ms);
  return formatDisplay(date, toTimeString(min));
}

/**
 * Mount the period control into `container`: a Live button, and a Start and
 * an End time slider under the mini calendar.
 *
 * The selection has two parts. The *span* is the run of days picked on a
 * calendar, by dragging across them (js/calendar.js calls `setDates`, and
 * reads `getDates` back to paint them). The *window* is the start and end
 * instant inside that span, which is what the map and metrics are fetched
 * for. Picking days opens the window out to the whole span; the sliders
 * then narrow it.
 *
 * The dock's two sliders set the time of day at each end of the window, on
 * whichever day that end sits. The full calendar's slider covers the whole
 * span with one thumb per end, through `scrub`. Either way the map refetches
 * as a thumb moves, so the trail and each vehicle's end marker follow it --
 * the end effectively scrubs where the fleet was at that moment.
 *
 * Live pins the end of the window to now and keeps refetching. End sliders
 * are disabled while it is on, since there is no end to choose.
 *
 * @param {HTMLElement} container
 * @param {Object} [options]
 * @param {(range: {from: string|null, to: string|null, live: boolean, scrub: boolean, dragging: boolean}) => void} [options.onChange]
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
  const todayOnLoad = getPerthDateString();
  // Instants are UTC ms on whole minutes. `endMs` is the start of the last
  // minute included, and is ignored while live.
  const state = {
    spanStart: DEV_DEFAULT_START_DATE,
    spanEnd: todayOnLoad,
    startMs: perthDayStartMs(DEV_DEFAULT_START_DATE) + toMinutes(DEV_DEFAULT_START_TIME) * MINUTE_MS,
    endMs: 0,
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
  // Now, down to the minute, since that is the resolution everything moves in.
  const nowMs = () => Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
  // Where the window actually ends: now while live, `endMs` otherwise.
  const effectiveEndMs = () => (state.live ? nowMs() : state.endMs);
  // The span as instants: midnight starting the first day, to the last
  // minute of the last day or now, whichever comes first.
  const spanStartMs = () => perthDayStartMs(state.spanStart);
  const spanEndMs = () => Math.min(perthDayStartMs(state.spanEnd) + DAY_LAST_MINUTE * MINUTE_MS, nowMs());

  // The start stays inside the span and at least a minute before the end;
  // the end stays inside the span, after the start, and not past now.
  const clampStart = (ms) => Math.max(spanStartMs(), Math.min(ms, effectiveEndMs() - MINUTE_MS));
  const clampEnd = (ms) => Math.max(state.startMs + MINUTE_MS, Math.min(ms, spanEndMs()));

  function currentRange() {
    const from = new Date(state.startMs).toISOString();
    // Live sends no `to` at all and lets the server default apply
    // (docs/api.md), so every poll genuinely reaches the latest data rather
    // than replaying a stale "now". Otherwise the end minute is inclusive.
    const to = state.live ? null : new Date(state.endMs + 59000).toISOString();
    return { from, to, live: state.live };
  }

  function render() {
    const start = toPerth(state.startMs);
    const end = toPerth(effectiveEndMs());
    summaryText.textContent = `${formatInstant(state.startMs)} → ${formatInstant(effectiveEndMs())}`;

    startSlider.value = start.min;
    startValue.textContent = toTimeString(start.min);
    startDateLabel.textContent = formatShortDate(start.date);

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

  /**
   * Move either end of the window while a thumb is held. Labels follow at
   * once; the refetch goes out at most once per SCRUB_THROTTLE_MS, with a
   * trailing one to catch where the thumb stopped. Call `release` on letting
   * go, which refetches straight away.
   */
  function scrub({ startMs, endMs } = {}) {
    if (startMs !== undefined) state.startMs = clampStart(startMs);
    if (endMs !== undefined && !state.live) state.endMs = clampEnd(endMs);
    render();
    clearTimeout(scrubHandle);
    const wait = SCRUB_THROTTLE_MS - (Date.now() - lastScrubAt);
    const fire = () => {
      lastScrubAt = Date.now();
      emit(true, true);
    };
    if (wait <= 0) fire();
    else scrubHandle = setTimeout(fire, wait);
  }

  const release = () => emit(true);

  // The dock sliders are a time of day, on whichever day that end sits.
  startSlider.addEventListener('input', () => {
    scrub({ startMs: perthDayStartMs(toPerth(state.startMs).date) + Number(startSlider.value) * MINUTE_MS });
  });
  endSlider.addEventListener('input', () => {
    scrub({ endMs: perthDayStartMs(toPerth(state.endMs).date) + Number(endSlider.value) * MINUTE_MS });
  });
  startSlider.addEventListener('change', release);
  endSlider.addEventListener('change', release);

  function setLive(on) {
    state.live = on;
    // Either way the span now runs to today. Switching Live off leaves the
    // end at the moment it was switched off, ready to be dragged back.
    state.spanEnd = today();
    state.endMs = nowMs();
    state.startMs = clampStart(state.startMs);
    syncPolling();
    emit();
  }

  liveButton.addEventListener('click', () => setLive(!state.live));

  /**
   * Take a new span of Perth dates, as a calendar hands them over. The window
   * opens out to the whole span so nothing chosen is hidden at first; the
   * sliders narrow it from there. Live survives only a span that still ends
   * today.
   */
  function setDates(startDate, endDate) {
    const todayStr = today();
    if (startDate > endDate) [startDate, endDate] = [endDate, startDate];
    let clamped = false;
    if (endDate > todayStr) { endDate = todayStr; clamped = true; }
    if (startDate > todayStr) { startDate = todayStr; clamped = true; }

    state.spanStart = startDate;
    state.spanEnd = endDate;
    state.live = state.live && endDate === todayStr;
    state.endMs = spanEndMs();
    state.startMs = clampStart(spanStartMs());
    syncPolling();
    emit();
    if (clamped) status.textContent = 'Future dates are not available yet.';
  }

  state.endMs = nowMs();
  syncPolling();
  // Fire once immediately so the caller is told about the default on load,
  // per S06's third criterion -- otherwise onChange only fires after the
  // user manually changes something.
  emit();

  return {
    getRange: currentRange,
    // The span as Perth "YYYY-MM-DD", for the mini calendar to paint.
    getDates: () => ({ start: state.spanStart, end: state.live ? today() : state.spanEnd, live: state.live }),
    // The span and window as UTC ms, for the full calendar's slider and the
    // selection it paints. `endMs` is the start of the last minute included.
    getWindow: () => ({
      spanStartMs: spanStartMs(),
      spanEndMs: state.live ? nowMs() : spanEndMs(),
      startMs: state.startMs,
      endMs: effectiveEndMs(),
      live: state.live,
    }),
    setDates,
    setLive,
    scrub,
    release,
    reset: () => {
      state.spanStart = DEV_DEFAULT_START_DATE;
      state.startMs = perthDayStartMs(DEV_DEFAULT_START_DATE) + toMinutes(DEV_DEFAULT_START_TIME) * MINUTE_MS;
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
  module.exports = { createTimelineControl, getPerthDateString, getPerthTimeString, perthToUtcIso, formatDisplay, formatInstant };
}
if (typeof window !== 'undefined') {
  window.Timeline = { createTimelineControl, getPerthDateString, getPerthTimeString, perthToUtcIso, formatDisplay, formatInstant };
}