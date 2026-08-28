// Timeline period control.
//
// A date picker with optional start/end times within that day 
// producing the from/to parameters in docs/api.md.<<< NOT IMPLEMENTED YET IN FILE, COMING LATER
//
// Defaults to today when the page loads, per S06 s third criterion.
// Dates are chosen and displayed in Perth time; the API accepts a bare date
// and expands it to a Perth day, so send the date.

const PERTH_TZ = 'Australia/Perth';
 
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
 * Mount a single-day calendar picker into `container`.
 *
 * @param {HTMLElement} container
 * @param {Object} [options]
 * @param {(date: string) => void} [options.onChange] - called with the
 *   newly selected "YYYY-MM-DD" (Perth) whenever the user picks a date.
 * @returns {{ getSelectedDate: () => string, reset: () => void }}
 */
function createTimelineControl(container, { onChange } = {}) {
  const todayStr = getPerthDateString();
 
  container.innerHTML = `
    <div class="timeline-control">
      <label for="timeline-date">Date</label>
      <input type="date" id="timeline-date" value="${todayStr}" max="${todayStr}">
      <p class="timeline-status" aria-live="polite"></p>
    </div>
  `;
 
  const input = container.querySelector('#timeline-date');
  const status = container.querySelector('.timeline-status');
 
  input.addEventListener('change', () => {
    const selected = input.value;
    if (!selected) return;
 
    // Belt and braces: the `max` attribute stops most browsers, but not all
    // input methods respect it (e.g. typing a date directly).
    if (selected > todayStr) {
      input.value = todayStr;
      status.textContent = 'Future dates are not available yet.';
      onChange?.(todayStr);
      return;
    }
 
    status.textContent = '';
    onChange?.(selected);
  });
 
  // Fire once immediately so the caller is told about the default (today)
  // date on load, per S06's third criterion -- otherwise onChange only
  // fires after the user manually changes the date.
  onChange?.(todayStr);
 
  return {
    getSelectedDate: () => input.value,
    reset: () => {
      input.value = todayStr;
      status.textContent = '';
    },
    // Called by main.js when a fetch for the selected day comes back empty,
    // so "no data" is stated rather than an unexplained blank map (S06 AC2,
    // docs/api.md).
    showNoData: () => {
      status.textContent = 'No data for this day.';
    },
  };
}
 
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createTimelineControl, getPerthDateString };
}
if (typeof window !== 'undefined') {
  window.Timeline = { createTimelineControl, getPerthDateString };
}
 