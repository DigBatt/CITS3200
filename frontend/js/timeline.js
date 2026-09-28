// Timeline period control, on one line in the filter bar.
//
// A Range menu of suggested timeframes (Last hour, Today, ...), a start/end
// date+time picker, and a "Live" toggle that pins the end of the range to
// now and keeps refetching, producing the from/to parameters in docs/api.md.
//
// While Live is on, the End inputs are hidden rather than just disabled,
// with "Now" in their place -- testing feedback was that a greyed-out End
// field still showing a stale date looked broken even when it was
// correctly being ignored.
//
// Defaults to today from midnight, live, when the page loads, per S06's
// third criterion.
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
  const [year, month, day] = dateStr.split('-').map(Number);
  const [hour, minute] = timeStr.split(':').map(Number);
  const period = hour < 12 ? 'am' : 'pm';
  const hour12 = ((hour + 11) % 12) + 1;
  return `${day} ${MONTH_ABBR[month - 1]} ${year}, ${hour12}:${String(minute).padStart(2, '0')} ${period}`;
}

// Suggested timeframes in the Range menu. Each resolves to a Perth-local
// range at the moment it is chosen, so "Today" always means the day it was
// picked. Editing a date or time by hand switches the menu to Custom.
const PRESETS = [
  { id: 'last-hour', label: 'Last hour' },
  { id: 'today', label: 'Today' },
  { id: 'yesterday', label: 'Yesterday' },
  { id: 'last-7-days', label: 'Last 7 days' },
  { id: 'last-30-days', label: 'Last 30 days' },
  { id: 'custom', label: 'Custom' },
];

/** "YYYY-MM-DD" moved by a whole number of days. */
function addDays(dateStr, days) {
  const [year, month, day] = dateStr.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

/**
 * The range a preset stands for, as the five values the control keeps:
 * start date/time, end date/time (Perth), and whether the end is "now".
 */
function presetRange(id, now = new Date()) {
  const today = getPerthDateString(now);
  const time = getPerthTimeString(now);
  switch (id) {
    case 'last-hour': {
      const hourAgo = new Date(now.getTime() - 60 * 60 * 1000);
      return { startDate: getPerthDateString(hourAgo), startTime: getPerthTimeString(hourAgo), endDate: today, endTime: time, live: true };
    }
    case 'yesterday':
      return { startDate: addDays(today, -1), startTime: '00:00', endDate: today, endTime: '00:00', live: false };
    case 'last-7-days':
      return { startDate: addDays(today, -6), startTime: '00:00', endDate: today, endTime: time, live: true };
    case 'last-30-days':
      return { startDate: addDays(today, -29), startTime: '00:00', endDate: today, endTime: time, live: true };
    default: // 'today'
      return { startDate: today, startTime: '00:00', endDate: today, endTime: time, live: true };
  }
}

/**
 * Mount the time range controls into `container`, on one line: a Range menu
 * of suggested timeframes, Start and End date+time inputs, and a Live switch
 * that pins the end to now.
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
 *   showNoData: () => void,
 *   clearStatus: () => void
 * }}
 */
function createTimelineControl(container, { onChange, livePollMs = DEFAULT_LIVE_POLL_MS } = {}) {
  const todayStr = getPerthDateString();
  // Default: today from midnight to now, live (DESIGN-FINAL.md s2).
  const initial = presetRange('today');

  const presetOptions = PRESETS.map((preset) =>
    `<option value="${preset.id}"${preset.id === 'today' ? ' selected' : ''}>${preset.label}</option>`).join('');

  container.innerHTML = `
    <div class="timeline-control">
      <label class="timeline-group">
        <span class="timeline-group-label">RANGE</span>
        <select class="timeline-preset" id="timeline-preset">${presetOptions}</select>
      </label>
      <div class="timeline-group">
        <span class="timeline-group-label" id="timeline-start-label">START</span>
        <div class="timeline-row">
          <input type="date" id="timeline-start-date" value="${initial.startDate}" max="${todayStr}" autocomplete="off" aria-labelledby="timeline-start-label">
          <input type="time" id="timeline-start-time" value="${initial.startTime}" autocomplete="off" aria-labelledby="timeline-start-label">
        </div>
      </div>
      <div class="timeline-group">
        <span class="timeline-group-label" id="timeline-end-label">END</span>
        <div class="timeline-row" id="timeline-end-row">
          <input type="date" id="timeline-end-date" value="${initial.endDate}" max="${todayStr}" autocomplete="off" aria-labelledby="timeline-end-label">
          <input type="time" id="timeline-end-time" value="${initial.endTime}" autocomplete="off" aria-labelledby="timeline-end-label">
        </div>
        <!-- Stands in for the End inputs while Live is on. -->
        <span class="timeline-now" id="timeline-now"><span class="timeline-live-dot" aria-hidden="true"></span>Now</span>
      </div>
      <label class="timeline-live" for="timeline-live">
        <span class="toggle-switch">
          <input type="checkbox" id="timeline-live" checked aria-labelledby="timeline-live-label">
          <span class="toggle-track"></span>
          <span class="toggle-knob"></span>
        </span>
        <span id="timeline-live-label">Live</span>
      </label>
      <p class="timeline-status" aria-live="polite"></p>
    </div>
  `;

  const preset = container.querySelector('#timeline-preset');
  const startDate = container.querySelector('#timeline-start-date');
  const startTime = container.querySelector('#timeline-start-time');
  const endDate = container.querySelector('#timeline-end-date');
  const endTime = container.querySelector('#timeline-end-time');
  const endRow = container.querySelector('#timeline-end-row');
  const nowLabel = container.querySelector('#timeline-now');
  const liveToggle = container.querySelector('#timeline-live');
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

  function emit() {
    status.textContent = '';
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
    // (see the timeline-picker-redesign discussion). "Now" stands in for it.
    endRow.hidden = isLive;
    endDate.disabled = isLive;
    endTime.disabled = isLive;
    nowLabel.hidden = !isLive;
    stopPolling();
    if (isLive) {
      pollHandle = setInterval(emit, livePollMs);
    }
  }

  function applyPreset(id) {
    const range = presetRange(id);
    startDate.value = range.startDate;
    startTime.value = range.startTime;
    endDate.value = range.endDate;
    endTime.value = range.endTime;
    liveToggle.checked = range.live;
    preset.value = id;
    syncLiveState();
    emit();
  }

  // A hand edit no longer matches a suggested timeframe.
  function edited() {
    preset.value = 'custom';
    emit();
  }

  function guardFutureDate(input) {
    if (input.value > getPerthDateString()) {
      input.value = getPerthDateString();
      status.textContent = 'Future dates are not available yet.';
    }
  }

  // Choosing Custom changes nothing by itself; the inputs are there to edit.
  preset.addEventListener('change', () => { if (preset.value !== 'custom') applyPreset(preset.value); });
  startDate.addEventListener('change', () => { guardFutureDate(startDate); edited(); });
  startTime.addEventListener('change', edited);
  endDate.addEventListener('change', () => { guardFutureDate(endDate); edited(); });
  endTime.addEventListener('change', edited);
  liveToggle.addEventListener('change', () => { syncLiveState(); edited(); });

  syncLiveState();
  // Fire once immediately so the caller is told about the default (today,
  // live) on load, per S06's third criterion -- otherwise onChange only
  // fires after the user manually changes something.
  emit();

  return {
    getRange: currentRange,
    reset: () => applyPreset('today'),
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