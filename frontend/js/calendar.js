// Service calendar (S21): scheduled service with downtime laid over it,
// shared by the admin page and the dashboard.
//
// Reads what already exists and adds no endpoint of its own:
//   /api/schedule   the weekly roster    -> scheduled bands
//   /api/downtime   operator reports     -> downtime blocks
//   /api/vehicles   names and colours    -> the vehicle toggles
//
// Requires js/api.js to be loaded first, for getSchedule, getVehicles and
// getDowntime. Both pages that mount this load it; admin.html needs it only
// for the calendar, since admin.js has its own fetch helper.
//
// One lane per shown vehicle, because the roster is per vehicle: a lane shows
// that bus's scheduled bands and its downtime. Anything not covered by a band
// is non-scheduled, which is a state in its own right rather than an absence,
// so an empty lane means that bus is rostered off, not that data is missing.
//
// Vehicle selection here is its own thing, and multi select. The dashboard's
// Vehicles filter is one vehicle or the whole fleet, which cannot express
// "these two buses", so the calendar keeps a separate set.
//
// AUTH (S13): every read behind this is public and stays public. The calendar
// is view only in both pages; editing the roster is the admin page's PUT.
//
// Times are drawn in the browser's local zone. The roster is written in the
// fleet's zone (display.timezone), so a viewer in another zone would see the
// bands shifted; the caption names the roster's zone for that reason.

(function () {
  const DAY_MS = 86400000;
  const MINUTE_MS = 60000;
  // Matches the dashboard's live poll (config/app.yaml).
  const EXTENT_LIVE_REFRESH_MS = 15000;
  const DAY_MINUTES = 1440;
  const HOUR_LABELS = [0, 6, 12, 18, 24];
  const DAY_NAMES = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];

  const escape = (value) =>
    String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const pad = (n) => String(n).padStart(2, '0');
  const hhmm = (date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const pct = (value) => `${(value * 100).toFixed(4)}%`;

  function startOfDay(value) {
    const date = new Date(value);
    date.setHours(0, 0, 0, 0);
    return date;
  }

  const minutesInto = (day, moment) => (moment - day) / 60000;

  // A local day as YYYY-MM-DD, to compare with a period's starts_on/ends_on.
  const isoDay = (day) => `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;

  // The roster's periods in force on one day: its weekday, inside any
  // starts_on (first day it counts) and ends_on (first day it no longer does).
  // Both the hand kept roster and the drives synced from calendar.online,
  // which come as one-day periods under `synced`.
  function rosterOn(schedule, day) {
    const iso = isoDay(day);
    const name = DAY_NAMES[day.getDay()];
    return [...((schedule?.schedule ?? {})[name] ?? []), ...((schedule?.synced ?? {})[name] ?? [])].filter(
      (period) => (!period.starts_on || period.starts_on <= iso) && (!period.ends_on || iso < period.ends_on),
    );
  }

  function clockMinutes(text) {
    const [hours, minutes] = String(text).split(':').map(Number);
    return hours * 60 + minutes;
  }

  // Downtime records for a window, or none if they cannot be read. Reading
  // them is admin only (/api/downtime, S13), so on the public dashboard a
  // signed out visitor gets a 401: the calendar then shows the roster without
  // downtime rather than failing to draw at all.
  async function loadDowntimeRecords(from, to) {
    try {
      const data = await getDowntime({ from: from.toISOString(), to: to.toISOString() });
      return data.records ?? [];
    } catch {
      return [];
    }
  }

  // Operating time from /api/operating, flattened to one list:
  // [{ vehicle, start, end, inSchedule }], with Dates. It is drawn over the
  // roster and downtime rather than needed by them, so a failure here leaves
  // the list empty and the rest of the calendar as it was.
  async function loadOperating(from, to) {
    try {
      const data = await getOperating({ from: from.toISOString(), to: to.toISOString() });
      return (data.vehicles ?? []).flatMap((vehicle) =>
        vehicle.intervals.map((interval) => ({
          vehicle: vehicle.vehicle_id,
          start: new Date(interval.start),
          end: new Date(interval.end),
          inSchedule: interval.in_schedule,
        })));
    } catch {
      return [];
    }
  }

  // The words for an interval's state, for titles and the legends.
  const operatingLabel = (inSchedule) =>
    inSchedule === true ? 'operating in schedule' : inSchedule === false ? 'operating outside schedule' : 'operating';
  const operatingClass = (inSchedule) => (inSchedule === true ? 'is-in' : inSchedule === false ? 'is-out' : 'is-unknown');

  function create(container, options = {}) {
    // The dashboard is fixed at a week; the admin page can switch.
    const fixedSpan = options.fixedDays ?? null;
    let span = fixedSpan ?? options.days ?? 3;
    // The day in focus. A 3 day view puts it in the middle, a week shows the
    // week containing it. Held as a date, not an offset, so a caller can open
    // the calendar on a day the user picked elsewhere.
    let anchor = startOfDay(options.anchor ?? new Date());
    // The dashboard's period, when the calendar also picks it (see
    // createRangeTools). The admin page passes none.
    const range = options.range ?? null;
    const tools = range ? createRangeTools(range, { onPicked: showSpan }) : null;
    let extent = null;
    let extentKey = null;
    let extentAt = 0;
    // Picking the period from the day headings: the start once the first
    // heading is clicked, waiting for the end.
    let pickStart = null;

    let schedule = null;
    let vehicles = [];
    let downtime = [];
    let operating = [];
    let shown = null;
    let error = null;
    let loading = false;
    let timer = null;

    function firstDay() {
      // Monday first, matching the roster's own day order.
      if (span >= 7) return new Date(anchor.getTime() - ((anchor.getDay() + 6) % 7) * DAY_MS);
      return new Date(anchor.getTime() - DAY_MS);
    }

    const isOnToday = () => anchor.getTime() === startOfDay(new Date()).getTime();

    const days = () => {
      const first = firstDay();
      return Array.from({ length: span }, (_, i) => new Date(first.getTime() + i * DAY_MS));
    };

    async function refresh() {
      const window = days();
      const from = window[0];
      const to = new Date(window[window.length - 1].getTime() + DAY_MS);

      loading = true;
      try {
        const [scheduleData, vehicleData, downtimeRecords, operatingData] = await Promise.all([
          getSchedule(),
          getVehicles(),
          loadDowntimeRecords(from, to),
          loadOperating(from, to),
        ]);

        schedule = scheduleData;
        vehicles = vehicleData.vehicles ?? [];
        downtime = downtimeRecords;
        operating = operatingData;
        if (shown === null) shown = new Set(vehicles.map((vehicle) => vehicle.id));
        error = null;
      } catch (exc) {
        error = exc.message;
      }
      loading = false;
      render();
    }

    // This vehicle's rostered periods on one day. A period naming no vehicle
    // is fleet wide, so it applies to everyone.
    function periodsFor(day, vehicleId) {
      return rosterOn(schedule, day)
        .filter((period) => !period.vehicles?.length || period.vehicles.includes(vehicleId))
        .map((period) => ({
          from: clockMinutes(period.start),
          to: clockMinutes(period.end),
          label: `${period.start}–${period.end}`,
          operator: period.operator ?? null,
        }));
    }

    // This vehicle's operating time on one day, clipped to it, each piece
    // keeping its whole interval for opening in Figures.
    function operatingFor(day, vehicleId) {
      const next = new Date(day.getTime() + DAY_MS);
      return operating
        .filter((interval) => interval.vehicle === vehicleId && interval.start < next && interval.end > day)
        .map((interval) => ({
          from: Math.max(0, minutesInto(day, interval.start)),
          to: Math.min(DAY_MINUTES, minutesInto(day, interval.end)),
          inSchedule: interval.inSchedule,
          label: `${hhmm(interval.start)}–${hhmm(interval.end)}`,
          startIso: interval.start.toISOString(),
          endIso: interval.end.toISOString(),
        }));
    }

    function downtimeFor(day, vehicleId) {
      const next = new Date(day.getTime() + DAY_MS);
      return downtime
        .filter((record) => record.vehicle_id === vehicleId)
        .map((record) => ({ record, start: new Date(record.start), end: new Date(record.end) }))
        .filter(({ start, end }) => start < next && end > day)
        .map(({ record, start, end }) => ({
          from: Math.max(0, minutesInto(day, start)),
          to: Math.min(DAY_MINUTES, minutesInto(day, end)),
          reason: record.reason,
          label: `${hhmm(start)}–${hhmm(end)}`,
          // The whole record, not the part on this day, for opening it.
          startIso: start.toISOString(),
          endIso: end.toISOString(),
        }));
    }

    // A block on a lane. With `link` and an onBlock handler it is a button
    // that opens that vehicle's figures for the block's time.
    const band = (from, to, className, title, text = '', link = null) => {
      const style = `top:${pct(from / DAY_MINUTES)};height:${pct((to - from) / DAY_MINUTES)}`;
      if (!link || !options.onBlock) {
        return `<div class="${className}" style="${style}" title="${escape(title)}">${escape(text)}</div>`;
      }
      return `<div class="${className} is-linked" style="${style}" role="button" tabindex="0"
                   data-cal-block data-vehicle="${escape(link.vehicle)}" data-from="${escape(link.from)}" data-to="${escape(link.to)}"
                   title="${escape(`${title} · open in Figures`)}">${escape(text)}</div>`;
    };
    // A minute of a day as an instant, for a scheduled block's link.
    const at = (day, minutes) => new Date(day.getTime() + minutes * 60000).toISOString();

    function dayColumn(day, selected) {
      const today = day.toDateString() === new Date().toDateString();
      const now = new Date();
      const width = selected.length ? 100 / selected.length : 100;
      const wide = span < 7 && selected.length < 3;

      const lanes = selected
        .map((vehicle, index) => {
          const scheduled = periodsFor(day, vehicle.id)
            .map((period) =>
              band(period.from, period.to, 'cal-scheduled',
                `${vehicle.name ?? vehicle.id} scheduled ${period.label}${period.operator ? ` · operator ${period.operator}` : ''}`,
                // The operator is who to ask about a block, so it is shown
                // even in a narrow lane, where the times drop out.
                period.operator ? (wide ? `${period.operator} · ${period.label}` : period.operator) : wide ? period.label : '',
                { vehicle: vehicle.id, from: at(day, period.from), to: at(day, period.to) }),
            )
            .join('');
          const down = downtimeFor(day, vehicle.id)
            .map((block) =>
              band(block.from, block.to, 'cal-downtime', `${vehicle.name ?? vehicle.id} down ${block.label} — ${block.reason}`, '',
                { vehicle: vehicle.id, from: block.startIso, to: block.endIso }),
            )
            .join('');
          // Operating time: a bar down the middle of the lane, over the roster,
          // so whether it falls inside a scheduled band is plain to see.
          const ops = operatingFor(day, vehicle.id)
            .map((block) =>
              band(block.from, block.to, `cal-operating ${operatingClass(block.inSchedule)}`,
                `${vehicle.name ?? vehicle.id} ${operatingLabel(block.inSchedule)} ${block.label}`, '',
                { vehicle: vehicle.id, from: block.startIso, to: block.endIso }),
            )
            .join('');
          return `<div class="cal-lane" style="left:${pct((index * width) / 100)};width:${pct(width / 100)};--cal-vehicle:${escape(vehicle.colour ?? 'currentColor')}" title="${escape(vehicle.name ?? vehicle.id)}">${scheduled}${down}${ops}</div>`;
        })
        .join('');

      const nowLine = today
        ? `<div class="cal-now" style="top:${pct(minutesInto(day, now) / DAY_MINUTES)}" title="Now ${escape(hhmm(now))}"><span>${escape(hhmm(now))}</span></div>`
        : '';

      return `
        <div class="cal-day${today ? ' is-today' : ''}">
          ${dayHead(day)}
          <div class="cal-day-body">
            ${HOUR_LABELS.slice(1, -1).map((hour) => `<div class="cal-gridline" style="top:${pct(hour / 24)}"></div>`).join('')}
            ${lanes || '<p class="cal-no-vehicles">No vehicles shown</p>'}
            ${range ? ['before', 'after'].map((side) => `<div class="cal-outside" data-cal-outside="${side}" data-day="${day.getTime()}" title="Outside the selected period" hidden></div>`).join('') : ''}
            ${nowLine}
          </div>
        </div>`;
    }

    // A day's heading. Where this calendar picks the period, it is a button:
    // click one day's heading for the start and another's for the end.
    function dayHead(day) {
      const label = `
            <span class="cal-day-name">${escape(day.toLocaleDateString([], { weekday: 'short' }))}</span>
            <span class="cal-day-date">${escape(day.toLocaleDateString([], { day: '2-digit', month: 'short' }))}</span>`;
      if (!range) return `<div class="cal-day-head">${label}</div>`;
      const date = isoDate(day);
      const future = date > range.max();
      return `<button type="button" class="cal-day-head is-pickable" data-cal-pick="${date}"${future ? ' aria-disabled="true"' : ''}
                title="${future ? 'Not yet available' : 'Pick this day as the start or end of the period'}">${label}</button>`;
    }

    function rangeLabel() {
      const window = days();
      const first = window[0];
      const last = window[window.length - 1];
      const fmt = (date, withYear) =>
        date.toLocaleDateString([], { day: '2-digit', month: 'short', ...(withYear ? { year: 'numeric' } : {}) });
      return `${fmt(first, false)} – ${fmt(last, true)}`;
    }

    function controls() {
      const viewToggle = fixedSpan
        ? ''
        : `<div class="cal-views" role="group" aria-label="Days shown">
             ${[3, 7].map((n) => `<button type="button" class="cal-view${span === n ? ' is-on' : ''}" data-cal-span="${n}" aria-pressed="${span === n}">${n} days</button>`).join('')}
           </div>`;

      const step = span >= 7 ? 'week' : 'day';
      return `
        <div class="cal-controls">
          <div class="cal-nav">
            <button type="button" class="cal-step" data-cal-step="-1" aria-label="Previous ${step}" title="Previous ${step}">&#8249;</button>
            <button type="button" class="cal-today" data-cal-step="0"${isOnToday() ? ' disabled' : ''}>Today</button>
            <button type="button" class="cal-step" data-cal-step="1" aria-label="Next ${step}" title="Next ${step}">&#8250;</button>
          </div>
          ${tools ? '<div data-cal-tools></div>' : `<span class="cal-range">${escape(rangeLabel())}</span>`}
          ${viewToggle}
        </div>`;
    }

    function vehiclePicker() {
      if (!vehicles.length) return '';
      const chips = vehicles
        .map((vehicle) => {
          const on = shown?.has(vehicle.id);
          return `<button type="button" class="cal-chip${on ? ' is-on' : ''}" data-cal-vehicle="${escape(vehicle.id)}"
                    style="--cal-vehicle:${escape(vehicle.colour ?? 'currentColor')}"
                    aria-pressed="${on}">${escape(vehicle.name ?? vehicle.id)}</button>`;
        })
        .join('');
      return `<div class="cal-chips" role="group" aria-label="Vehicles shown on the calendar">${chips}</div>`;
    }

    function caption() {
      if (!schedule) return '';
      if (!schedule.configured) {
        return 'No service schedule is in the system, so all time is non-scheduled. Set one under Schedule.';
      }
      return `One lane per vehicle. Roster in ${schedule.timezone ?? 'local time'}.`;
    }

    function render() {
      if (error) {
        container.innerHTML = `<p class="cal-error">Could not load the calendar: ${escape(error)}</p>`;
        return;
      }
      if (!schedule) {
        container.innerHTML = '<p class="cal-empty">Loading…</p>';
        return;
      }

      const selected = vehicles.filter((vehicle) => shown?.has(vehicle.id));
      container.innerHTML = `
        <div class="cal${loading ? ' is-loading' : ''}" style="--cal-days:${span}">
          ${controls()}
          ${vehiclePicker()}
          <div class="cal-legend">
            <span class="cal-key"><span class="cal-swatch is-scheduled"></span>Scheduled</span>
            <span class="cal-key"><span class="cal-swatch is-unscheduled"></span>Non-scheduled</span>
            <span class="cal-key"><span class="cal-swatch is-downtime"></span>Downtime</span>
            <span class="cal-key"><span class="cal-swatch is-op-in"></span>Operating in schedule</span>
            <span class="cal-key"><span class="cal-swatch is-op-out"></span>Operating outside schedule</span>
            <span class="cal-key"><span class="cal-swatch is-now"></span>Now</span>
            ${range ? `
            <span class="cal-key"><span class="cal-swatch is-outside-period"></span>Outside selected period</span>
            <span class="cal-key"><span class="cal-measure-dot"></span>First / last measurement</span>
            <span class="cal-pick-hint" aria-live="polite"></span>` : ''}
          </div>
          <div class="cal-grid">
            <div class="cal-hours">
              ${HOUR_LABELS.map((hour) => `<span style="top:${pct(hour / 24)}">${pad(hour)}:00</span>`).join('')}
            </div>
            ${days().map((day) => dayColumn(day, selected)).join('')}
          </div>
          <p class="cal-caption">${escape(caption())}</p>
        </div>`;

      if (tools) {
        container.querySelector('[data-cal-tools]').replaceWith(tools.element);
        tools.setLabel(rangeLabel());
        paintRange();
      }
    }

    // ---- The period, when this calendar picks it ----

    // Leave the window clear and shade the rest of each day: a band before
    // it and a band after it, either of which may be empty, or the whole day
    // when the window misses it. Done in place, so a slider drag does not
    // rebuild the board under the pointer.
    function paintSelection(win) {
      container.querySelectorAll('[data-cal-outside]').forEach((band) => {
        const dayStart = Number(band.dataset.day);
        const dayEnd = dayStart + DAY_MS;
        // endMs is the start of the last minute included.
        const selFrom = win.startMs;
        const selTo = win.endMs + MINUTE_MS;
        const misses = selTo <= dayStart || selFrom >= dayEnd;

        let from;
        let to;
        if (band.dataset.calOutside === 'before') {
          from = dayStart;
          to = misses ? dayEnd : Math.min(Math.max(selFrom, dayStart), dayEnd);
        } else {
          from = misses ? dayEnd : Math.max(Math.min(selTo, dayEnd), dayStart);
          to = dayEnd;
        }

        band.hidden = to <= from;
        if (band.hidden) return;
        band.style.top = pct((from - dayStart) / DAY_MS);
        band.style.height = pct((to - from) / DAY_MS);
        // A line only where the band meets the selection, so its edge reads
        // clearly; not at midnight, where the band just runs off the day.
        band.classList.toggle('meets-selection', !misses);
      });
    }

    // The first and last measurement in the span, for the slider's dots and
    // zoom. Fetched again only when the span or the vehicles shown change,
    // or every poll interval while live, since new data keeps arriving then.
    async function loadExtent() {
      const win = range.window();
      if (shown && shown.size === 0) {
        extentKey = 'none';
        extent = null;
        return;
      }
      const ids = shown && shown.size < vehicles.length ? [...shown].join(',') : undefined;
      const key = `${win.spanStartMs}|${win.live ? 'live' : win.spanEndMs}|${ids ?? 'all'}`;
      if (key === extentKey && !(win.live && Date.now() - extentAt > EXTENT_LIVE_REFRESH_MS)) return;
      extentKey = key;
      extentAt = Date.now();

      let next = null;
      try {
        const data = await getPositionsExtent({
          vehicles: ids,
          from: new Date(win.spanStartMs).toISOString(),
          // Live leaves `to` to the server's default of now.
          to: win.live ? undefined : new Date(win.spanEndMs + MINUTE_MS - 1).toISOString(),
        });
        if (data.first && data.last) next = { first: Date.parse(data.first), last: Date.parse(data.last) };
      } catch {
        // No dots, and no zoom, is the honest fallback.
      }
      if (key !== extentKey) return;
      extent = next;
      paintRange();
    }

    function paintRange() {
      if (!range) return;
      const win = range.window();
      tools.update(win, extent);
      paintSelection(win);
      paintHeads();
      loadExtent();
    }

    // The day headings: the chosen days tinted, a half made pick's start
    // marked, and the hint saying what the next click does.
    function paintHeads() {
      const { start, end } = range.get() ?? {};
      container.querySelectorAll('[data-cal-pick]').forEach((head) => {
        const date = head.dataset.calPick;
        head.classList.toggle('is-in-period', !pickStart && Boolean(start) && date >= start && date <= end);
        head.classList.toggle('is-pick-start', date === pickStart);
        head.setAttribute('aria-pressed', String(date === pickStart));
      });
      const hint = container.querySelector('.cal-pick-hint');
      if (hint) {
        hint.textContent = pickStart
          ? `From ${new Date(`${pickStart}T00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' })}: now click an end day's heading. Esc cancels.`
          : "Click a day's heading for the start of the period, then another for the end.";
      }
    }

    // A heading clicked: the first is the start, the second the end, in
    // either order; the same day twice is that one day.
    function pickDay(date) {
      if (pickStart === null) {
        pickStart = date;
        paintHeads();
        return;
      }
      const [start, end] = [pickStart, date].sort();
      pickStart = null;
      range.select(start, end);
      paintHeads();
    }

    function cancelPick() {
      if (pickStart === null) return false;
      pickStart = null;
      paintHeads();
      return true;
    }

    // Bring a newly picked span into view: its first day starts the week, or
    // sits in the middle of the 3 days.
    function showSpan(startDate) {
      const first = startOfDay(new Date(`${startDate}T00:00`));
      anchor = span >= 7 ? first : new Date(first.getTime() + DAY_MS);
      refresh();
    }

    container.addEventListener('click', (event) => {
      const vehicle = event.target.closest('[data-cal-vehicle]');
      const step = event.target.closest('[data-cal-step]');
      const view = event.target.closest('[data-cal-span]');
      const heading = event.target.closest('[data-cal-pick]');
      const block = event.target.closest('[data-cal-block]');

      if (block) {
        options.onBlock?.({ vehicle: block.dataset.vehicle, from: block.dataset.from, to: block.dataset.to });
        return;
      }

      if (heading) {
        if (heading.getAttribute('aria-disabled') !== 'true') pickDay(heading.dataset.calPick);
        return;
      }

      if (vehicle && shown) {
        const id = vehicle.dataset.calVehicle;
        // De-selecting the last vehicle is allowed: the empty board still
        // shows the days, which is a fair thing to want.
        shown.has(id) ? shown.delete(id) : shown.add(id);
        render();
        return;
      }

      if (step) {
        const delta = Number(step.dataset.calStep);
        // A week view steps by weeks, a 3 day view by single days.
        anchor = delta === 0 ? startOfDay(new Date()) : new Date(anchor.getTime() + delta * (span >= 7 ? 7 : 1) * DAY_MS);
        refresh();
        return;
      }

      if (view) {
        const next = Number(view.dataset.calSpan);
        if (next === span) return;
        // The day in focus is kept, so switching view does not jump away.
        span = next;
        refresh();
      }
    });

    // A linked block is a button to the keyboard too.
    container.addEventListener('keydown', (event) => {
      const block = event.target.closest?.('[data-cal-block]');
      if (!block || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      block.click();
    });

    refresh();
    // Redraws for the moving now line, but not under a held slider thumb.
    timer = setInterval(() => {
      if (!tools?.isSliding()) render();
    }, 60000);

    return {
      refresh,
      paintRange,
      cancelPick,
      // Open on a particular day, for the mini calendar handing one over.
      goTo(date) {
        anchor = startOfDay(date);
        refresh();
      },
      destroy() {
        clearInterval(timer);
        timer = null;
      },
    };
  }


  // ---- Range tools, for the full calendar on the dashboard ----
  //
  // There the full calendar also picks the period, between the visible days'
  // label and the 3/7 day toggle:
  //   - the label drops down to a month to drag a span of days across, which
  //     can run well past the 3 or 7 days on screen;
  //   - a slider over that span, with a thumb for each end of the window;
  //   - dots on the track at the first and last measurement in the span, and
  //     a Zoom to data toggle that narrows the track to between them;
  //   - Live, as in the dock, since the dock is behind the overlay.
  //
  // `range` is the dashboard's adapter over js/timeline.js:
  //   get(), select(a, b), max()   as for the mini month
  //   window()                     { spanStartMs, spanEndMs, startMs, endMs, live }
  //   scrub({ startMs?, endMs? })  move an end while a thumb is held
  //   release()                    the thumb was let go
  //   setLive(on)
  //
  // Built once and moved back into each re-render of the calendar, so a held
  // thumb and the open dropdown survive the board redrawing around them.

  function createRangeTools(range, { onPicked }) {
    const element = document.createElement('div');
    element.className = 'cal-tools';
    element.innerHTML = `
      <div class="cal-range-pick">
        <button type="button" class="cal-range-btn" data-cal-range-toggle aria-expanded="false" aria-haspopup="dialog"
                title="Choose the period, across as many days as you like">
          <span class="cal-range"></span>
          <span class="cal-range-chevron" aria-hidden="true">&#9662;</span>
        </button>
        <div class="cal-range-pop" role="dialog" aria-label="Choose the period" hidden>
          <div class="cal-range-mini"></div>
        </div>
      </div>
      <div class="cal-slider">
        <button type="button" class="cal-slider-btn cal-slider-live" data-cal-live
                title="Set the end of the period to now, and keep it there">
          <span class="cal-slider-live-dot" aria-hidden="true"></span>Live
        </button>
        <div class="cal-slider-body">
          <div class="cal-slider-track">
            <div class="cal-slider-rail">
              <div class="cal-slider-fill"></div>
              <span class="cal-measure-dot" data-cal-dot="first" hidden></span>
              <span class="cal-measure-dot" data-cal-dot="last" hidden></span>
            </div>
            <input type="range" class="cal-slider-input" data-cal-thumb="start" min="0" max="1" step="1" aria-label="Start of the period">
            <input type="range" class="cal-slider-input" data-cal-thumb="end" min="0" max="1" step="1" aria-label="End of the period">
          </div>
          <div class="cal-slider-ends">
            <span data-cal-end-label="start"></span>
            <span data-cal-end-label="end"></span>
          </div>
        </div>
        <button type="button" class="cal-slider-btn" data-cal-zoom aria-pressed="false"
                title="Zoom the slider in to between the first and last measurement">Zoom to data</button>
      </div>`;

    const toggle = element.querySelector('[data-cal-range-toggle]');
    const label = element.querySelector('.cal-range');
    const pop = element.querySelector('.cal-range-pop');
    const miniHost = element.querySelector('.cal-range-mini');
    const liveButton = element.querySelector('[data-cal-live]');
    const zoomButton = element.querySelector('[data-cal-zoom]');
    const fill = element.querySelector('.cal-slider-fill');
    const startInput = element.querySelector('[data-cal-thumb="start"]');
    const endInput = element.querySelector('[data-cal-thumb="end"]');
    const dots = {
      first: element.querySelector('[data-cal-dot="first"]'),
      last: element.querySelector('[data-cal-dot="last"]'),
    };
    const endLabels = {
      start: element.querySelector('[data-cal-end-label="start"]'),
      end: element.querySelector('[data-cal-end-label="end"]'),
    };

    let mini = null;
    let zoom = false;
    let sliding = false;
    // The track's scale, in ms, as last drawn; the thumbs' values are whole
    // minutes from `lo`.
    let lo = 0;
    let hi = MINUTE_MS;

    const floorMinute = (ms) => Math.floor(ms / MINUTE_MS) * MINUTE_MS;
    const ceilMinute = (ms) => Math.ceil(ms / MINUTE_MS) * MINUTE_MS;
    const toValue = (ms) => Math.max(0, Math.min(Math.round((ms - lo) / MINUTE_MS), Number(startInput.max)));
    const toMs = (value) => lo + Number(value) * MINUTE_MS;
    const instant = (ms) => Timeline.formatInstant(ms);

    // ---- The dropdown ----

    function setOpen(open) {
      pop.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      if (!open) return;
      // Built on first open, so a closed dropdown costs nothing.
      if (!mini) {
        mini = createMini(miniHost, {
          expand: false,
          range: {
            get: range.get,
            max: range.max,
            select(start, end) {
              range.select(start, end);
              setOpen(false);
              onPicked(start, end);
            },
          },
        });
      }
      // Open on the month the span starts in, not wherever it was left.
      mini.show(new Date(`${range.get().start}T00:00`));
      mini.paint();
    }

    toggle.addEventListener('click', () => setOpen(pop.hidden));
    // Escape closes the dropdown first, and only the dropdown: the overlay's
    // own Escape handler sits on the document, above this.
    element.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !pop.hidden) {
        event.stopPropagation();
        setOpen(false);
        toggle.focus();
      }
    });
    document.addEventListener('pointerdown', (event) => {
      if (!pop.hidden && !element.querySelector('.cal-range-pick').contains(event.target)) setOpen(false);
    });

    // ---- The slider ----

    startInput.addEventListener('input', () => range.scrub({ startMs: toMs(startInput.value) }));
    endInput.addEventListener('input', () => range.scrub({ endMs: toMs(endInput.value) }));
    for (const input of [startInput, endInput]) {
      input.addEventListener('change', () => range.release());
      input.addEventListener('pointerdown', () => { sliding = true; });
    }
    window.addEventListener('pointerup', () => { sliding = false; });

    liveButton.addEventListener('click', () => range.setLive(!range.window().live));
    zoomButton.addEventListener('click', () => {
      zoom = !zoom;
      update(range.window(), lastExtent);
    });

    let lastExtent = null;

    function placeDot(dot, ms, what) {
      dot.hidden = ms === undefined || ms < lo || ms > hi;
      if (dot.hidden) return;
      dot.style.left = pct((ms - lo) / (hi - lo));
      dot.title = `${what} measurement: ${instant(ms)}`;
    }

    function update(win, extent) {
      lastExtent = extent;
      const zoomed = zoom && Boolean(extent);
      zoomButton.disabled = !extent;
      zoomButton.classList.toggle('is-on', zoomed);
      zoomButton.setAttribute('aria-pressed', String(zoomed));
      zoomButton.title = extent
        ? 'Zoom the slider in to between the first and last measurement'
        : 'No measurements in this period to zoom to';

      if (zoomed) {
        lo = floorMinute(extent.first);
        hi = Math.max(ceilMinute(extent.last), lo + MINUTE_MS);
      } else {
        lo = win.spanStartMs;
        hi = Math.max(win.spanEndMs, lo + MINUTE_MS);
      }
      const max = Math.round((hi - lo) / MINUTE_MS);
      startInput.max = max;
      endInput.max = max;

      // A thumb outside a zoomed track sits at its edge; the labels under
      // the track still give the real time.
      const startValue = toValue(win.startMs);
      const endValue = toValue(win.endMs);
      startInput.value = startValue;
      endInput.value = endValue;
      endInput.disabled = win.live;
      // With the thumbs close together, the one that can still move away
      // has to be on top, or it cannot be grabbed.
      startInput.classList.toggle('is-top', startValue > max / 2);

      fill.style.left = pct(startValue / max);
      fill.style.width = pct((endValue - startValue) / max);
      placeDot(dots.first, extent?.first, 'First');
      placeDot(dots.last, extent?.last, 'Last');

      endLabels.start.textContent = instant(win.startMs);
      endLabels.end.textContent = win.live ? 'Now' : instant(win.endMs);

      liveButton.classList.toggle('is-on', win.live);
      liveButton.setAttribute('aria-pressed', String(win.live));
      if (mini && !pop.hidden) mini.paint();
    }

    return {
      element,
      update,
      setLabel(text) {
        label.textContent = text;
      },
      isSliding: () => sliding,
    };
  }


  // ---- Mini month ----
  //
  // A month at a glance, docked on the admin page. Each day carries a mark
  // for what happened on it: service rostered, downtime reported, or both.
  // Clicking a day opens the full calendar on that day, which is why
  // ServiceCalendar.create takes an anchor.
  //
  // It says nothing about which vehicle: at this size a mark per bus would be
  // unreadable, and the full view is one click away for that.
  //
  // Given `options.range`, it is also the dashboard's date picker: click a
  // start date, then an end date (hovering in between previews the range), or
  // drag across the days as a shortcut. The full calendar moves to an expand
  // button in the head, since a day press no longer opens it.
  // The range itself is owned by the caller (js/timeline.js on the dashboard):
  //   range.get()          -> { start, end } as local "YYYY-MM-DD"
  //   range.select(a, b)   <- the days the operator let go on, a <= b
  //   range.max()          -> the last selectable day; later ones are shown
  //                           but cannot be picked
  //
  // Given `options.headHost`, the month bar is drawn there instead, e.g. in
  // the page header, and `container` holds only the month itself. Folding
  // then shows and hides the month as an overlay under the bar: `onFold`
  // is told each time, for the page to show or hide whatever holds it.

  const isoDate = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

  function createMini(container, options = {}) {
    const onOpen = options.onOpen ?? (() => {});
    const range = options.range ?? null;
    const headHost = options.headHost ?? null;
    const onFold = options.onFold ?? (() => {});
    // Collapsed shows the month bar alone, which is the whole dock on a small
    // screen where a full month would bury what is behind it.
    let collapsed = Boolean(options.collapsed);
    let month = startOfDay(new Date());
    month.setDate(1);

    let schedule = null;
    let downtime = [];
    let operating = [];
    let error = null;
    // A press in progress: the day it started on, the day under the pointer,
    // and whether it has moved to another day, which makes it a drag.
    let drag = null;
    // Picking by clicks: the start date once the first click has landed, and
    // the day under the pointer, to preview the range before the second.
    let pending = null;
    let hover = null;

    // Six weeks from the Monday on or before the 1st, so the grid never jumps
    // height between months.
    function cells() {
      const first = new Date(month);
      const lead = (first.getDay() + 6) % 7;
      const start = new Date(first.getTime() - lead * DAY_MS);
      return Array.from({ length: 42 }, (_, i) => new Date(start.getTime() + i * DAY_MS));
    }

    async function refresh() {
      const window = cells();
      try {
        const from = window[0];
        const to = new Date(window[41].getTime() + DAY_MS);
        const [scheduleData, downtimeRecords, operatingData] = await Promise.all([
          getSchedule(),
          loadDowntimeRecords(from, to),
          loadOperating(from, to),
        ]);
        schedule = scheduleData;
        downtime = downtimeRecords;
        operating = operatingData;
        error = null;
      } catch (exc) {
        error = exc.message;
      }
      render();
    }

    const hasService = (day) => rosterOn(schedule, day).length > 0;

    const hasDowntime = (day) => {
      const next = new Date(day.getTime() + DAY_MS);
      return downtime.some((record) => new Date(record.start) < next && new Date(record.end) > day);
    };

    // Whether any vehicle operated that day in schedule (true) or outside it
    // (false); the month is fleet wide, like its other marks.
    const hasOperating = (day, inSchedule) => {
      const next = new Date(day.getTime() + DAY_MS);
      return operating.some((interval) => interval.inSchedule === inSchedule && interval.start < next && interval.end > day);
    };

    // The month bar: an expand button, the month arrows, and the month name,
    // which folds the month away and back. Needs no data, so a bar in the
    // header is drawn at once, before the month has loaded.
    function headHtml() {
      // In the header there is no dock left to click for the full calendar,
      // so the bar always gets the expand button there.
      const expand = (range && options.expand !== false) || headHost
        ? '<button type="button" class="mini-step mini-expand" data-mini-expand aria-label="Open the full calendar" title="Open the full calendar">&#10530;</button>'
        : '';
      return `
        <div class="mini-head">
          ${expand}
          <button type="button" class="mini-step" data-mini-month="-1" aria-label="Previous month">&#8249;</button>
          <button type="button" class="mini-month" data-mini-toggle aria-expanded="${!collapsed}"
                  title="${collapsed ? 'Show the month' : 'Hide the month'}">
            <span>${escape(month.toLocaleDateString([], { month: 'long', year: 'numeric' }))}</span>
            <span class="mini-chevron" aria-hidden="true">${collapsed ? '&#9656;' : '&#9662;'}</span>
          </button>
          <button type="button" class="mini-step" data-mini-month="1" aria-label="Next month">&#8250;</button>
        </div>`;
    }

    function render() {
      const ranged = range ? ' is-ranged' : '';
      if (headHost) {
        headHost.innerHTML = `<div class="mini is-bar${ranged}">${headHtml()}</div>`;
        onFold(collapsed);
      }
      if (error) {
        container.innerHTML = `<p class="cal-error">${escape(error)}</p>`;
        return;
      }
      if (!schedule) {
        container.innerHTML = '<p class="cal-empty">Loading…</p>';
        return;
      }

      const today = startOfDay(new Date()).getTime();
      const max = range?.max();
      const grid = cells()
        .map((day) => {
          const marks = [
            hasService(day) ? '<span class="mini-mark is-service"></span>' : '',
            hasDowntime(day) ? '<span class="mini-mark is-downtime"></span>' : '',
            hasOperating(day, true) ? '<span class="mini-mark is-op-in"></span>' : '',
            hasOperating(day, false) ? '<span class="mini-mark is-op-out"></span>' : '',
          ].join('');
          const future = Boolean(max) && isoDate(day) > max;
          const classes = [
            'mini-day',
            day.getMonth() === month.getMonth() ? '' : 'is-outside',
            day.getTime() === today ? 'is-today' : '',
            future ? 'is-future' : '',
          ].filter(Boolean).join(' ');
          // aria-disabled rather than disabled: a disabled button swallows
          // the pointer events a drag passing over it still needs.
          return `<button type="button" class="${classes}" data-mini-day="${day.toISOString()}" data-mini-date="${isoDate(day)}"${future ? ' aria-disabled="true"' : ''}>
                    <span class="mini-num">${day.getDate()}</span>
                    <span class="mini-marks">${marks}</span>
                  </button>`;
        })
        .join('');

      // No title: the dock is unlabelled by design, the overlay names itself.
      // With the bar in the header, the month is drawn here only while open.
      const head = headHost ? '' : headHtml();
      if (headHost && collapsed) {
        container.innerHTML = '';
        return;
      }
      container.innerHTML = collapsed
        ? `<div class="mini is-collapsed${ranged}">${head}</div>`
        : `
        <div class="mini${ranged}">
          ${head}
          <div class="mini-dows">${['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d) => `<span>${d}</span>`).join('')}</div>
          <div class="mini-grid">${grid}</div>
          ${range ? '<p class="mini-hint" aria-live="polite"></p>' : ''}
          <div class="mini-legend">
            <span><span class="mini-mark is-service"></span>Service</span>
            <span><span class="mini-mark is-downtime"></span>Downtime</span>
            <span title="Operating within its rostered service time"><span class="mini-mark is-op-in"></span>Ran in schedule</span>
            <span title="Operating outside its rostered service time"><span class="mini-mark is-op-out"></span>Ran outside</span>
          </div>
        </div>`;
      paint();
    }

    // Marks the selected days in place, without rebuilding the grid, so a
    // drag can repaint on every move without losing the pointer.
    function paint() {
      if (!range) return;
      let start;
      let end;
      // What to show, most immediate first: a drag under way, then a pick
      // half made (previewed to the day under the pointer), then the range.
      const previewing = Boolean(drag?.moved || pending);
      if (drag?.moved) {
        [start, end] = [drag.from, drag.over].sort();
      } else if (pending) {
        [start, end] = [pending, hover ?? pending].sort();
      } else {
        ({ start, end } = range.get() ?? {});
      }
      container.querySelectorAll('[data-mini-date]').forEach((cell) => {
        const date = cell.dataset.miniDate;
        const inside = Boolean(start) && date >= start && date <= end;
        cell.classList.toggle('is-in-range', inside);
        cell.classList.toggle('is-range-start', inside && date === start);
        cell.classList.toggle('is-range-end', inside && date === end);
        cell.classList.toggle('is-preview', inside && previewing);
        cell.classList.toggle('is-pending', date === pending);
        cell.setAttribute('aria-pressed', String(inside));
      });

      const hint = container.querySelector('.mini-hint');
      if (hint) {
        hint.textContent = pending
          ? `From ${shortDate(pending)}: now pick an end date. Esc cancels.`
          : 'Pick a start date, then an end date.';
      }
    }

    const shortDate = (iso) => new Date(`${iso}T00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' });

    // A day chosen by click, tap or keyboard: the first is the start, the
    // second the end, in either order. The same day twice is that one day.
    function pick(date) {
      if (pending === null) {
        pending = date;
        hover = date;
        paint();
        return;
      }
      const [start, end] = [pending, date].sort();
      pending = null;
      hover = null;
      range.select(start, end);
      paint();
    }

    // Drop a half made pick, e.g. on Escape or when the month is folded away.
    function cancelPick() {
      if (pending === null) return false;
      pending = null;
      hover = null;
      paint();
      return true;
    }

    // Days under the pointer, clamped to the last selectable one so a drag
    // running on into the future still ends on today.
    function dateAt(x, y) {
      const cell = document.elementFromPoint(x, y)?.closest('[data-mini-date]');
      if (!cell || !container.contains(cell)) return null;
      const max = range.max();
      return cell.dataset.miniDate > max ? max : cell.dataset.miniDate;
    }

    if (range) {
      container.addEventListener('pointerdown', (event) => {
        const cell = event.target.closest('[data-mini-date]');
        if (!cell || event.button !== 0 || cell.getAttribute('aria-disabled') === 'true') return;
        // Keeps the press from selecting text or scrolling while dragging.
        event.preventDefault();
        drag = { from: cell.dataset.miniDate, over: cell.dataset.miniDate, moved: false };
        container.setPointerCapture(event.pointerId);
      });
      container.addEventListener('pointermove', (event) => {
        const date = dateAt(event.clientX, event.clientY);
        if (drag) {
          if (date && date !== drag.over) {
            drag.over = date;
            drag.moved = drag.over !== drag.from;
            paint();
          }
        } else if (pending && date !== hover) {
          // Between the two clicks, preview the range to the day pointed at.
          hover = date ?? pending;
          paint();
        }
      });
      container.addEventListener('pointerleave', () => {
        if (!drag && pending && hover !== pending) {
          hover = pending;
          paint();
        }
      });
      container.addEventListener('pointerup', () => {
        if (!drag) return;
        const { from, over, moved } = drag;
        drag = null;
        if (moved) {
          // A drag across days picks them in one go, and drops any half pick.
          pending = null;
          hover = null;
          const [start, end] = [from, over].sort();
          range.select(start, end);
          paint();
        } else {
          // Pressed and let go on one day: a click.
          pick(from);
        }
      });
      container.addEventListener('pointercancel', () => {
        drag = null;
        paint();
      });
      container.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && cancelPick()) event.stopPropagation();
      });
    }

    function onClick(event) {
      const toggle = event.target.closest('[data-mini-toggle]');
      const step = event.target.closest('[data-mini-month]');
      const day = event.target.closest('[data-mini-day]');
      const expand = event.target.closest('[data-mini-expand]');

      // Folding and paging both stay inside the dock, so they are checked
      // before the click can fall through to opening the full calendar.
      if (toggle) {
        collapsed = !collapsed;
        if (collapsed) cancelPick();
        render();
        return;
      }
      if (step) {
        month = new Date(month.getFullYear(), month.getMonth() + Number(step.dataset.miniMonth), 1);
        render();
        refresh();
        return;
      }
      if (expand) {
        onOpen(range ? new Date(`${range.get().end}T00:00`) : new Date());
        return;
      }
      if (range) {
        // A mouse or touch press was handled on pointer up. A keyboard press
        // (detail 0) picks the same way, start then end, so the grid works
        // without a pointer.
        if (day && event.detail === 0 && day.getAttribute('aria-disabled') !== 'true') {
          pick(day.dataset.miniDate);
        }
        return;
      }
      if (day) onOpen(new Date(day.dataset.miniDay));
    }
    // The bar may be drawn somewhere else (headHost); its buttons work the same.
    container.addEventListener('click', onClick);
    headHost?.addEventListener('click', onClick);

    if (headHost) render(); // the bar, before the month's data arrives
    refresh();
    return {
      refresh,
      paint,
      isCollapsed: () => collapsed,
      // Fold or unfold from outside, e.g. a click elsewhere on the page.
      setCollapsed(next) {
        if (next === collapsed) return;
        collapsed = next;
        if (collapsed) cancelPick();
        render();
      },
      // Whether a start date is picked and waiting for its end; Escape then
      // cancels the pick before it closes anything.
      cancelPick,
      // Page to the month holding `date`.
      show(date) {
        const next = new Date(date.getFullYear(), date.getMonth(), 1);
        if (next.getTime() === month.getTime()) return;
        month = next;
        render();
        refresh();
      },
    };
  }


  // ---- Mini month plus the full calendar it opens ----
  //
  // Both pages use this: the admin dock and the dashboard's Schedule view.
  // Keeping the wiring here means the two behave the same, and the full
  // calendar is built only when someone first opens it.

  function mount(elements, options = {}) {
    // `head` and `panel` are optional: given, the month bar sits in `head`
    // (the page header) and the month opens in `panel` as an overlay below it.
    const { mini: miniElement, overlay, body, close, head = null, panel = null } = elements;
    let full = null;

    function open(day) {
      // The full calendar replaces the month overlay rather than sitting on it.
      if (panel) mini.setCollapsed(true);
      overlay.hidden = false;
      document.body.classList.add('is-overlaid');

      if (full) {
        full.goTo(day ?? new Date());
      } else {
        // Opens on the week; the 3 day option is in the calendar's controls.
        full = create(body, { days: 7, anchor: day ?? new Date(), range: options.range, onBlock: options.onBlock });
      }
      close.focus();
    }

    function shut() {
      overlay.hidden = true;
      document.body.classList.remove('is-overlaid');
    }

    const mini = createMini(miniElement, {
      onOpen: open,
      collapsed: options.collapsed,
      range: options.range,
      headHost: head,
      onFold: (collapsed) => {
        if (panel) panel.hidden = collapsed;
      },
    });

    if (head && panel) {
      // On a phone the overlay spans the screen just under the header
      // (css/calendar.css). The header wraps at narrow widths, so its bottom
      // edge is measured rather than assumed.
      const header = head.closest('header');
      if (header) {
        const markHeader = () => {
          document.documentElement.style.setProperty('--app-header-bottom', `${header.getBoundingClientRect().bottom}px`);
        };
        markHeader();
        window.addEventListener('resize', markHeader);
      }

      // An open month overlay closes on a press anywhere else on the page,
      // except in the full calendar, which may have been opened from it.
      document.addEventListener('pointerdown', (event) => {
        if (mini.isCollapsed()) return;
        if (head.contains(event.target) || panel.contains(event.target) || overlay.contains(event.target)) return;
        mini.setCollapsed(true);
      });
    }

    // A click anywhere on the dock that is not a day or a month arrow still
    // does the obvious thing. Not when picking a range, where a stray click
    // at the end of a drag would open the overlay over the selection.
    miniElement.addEventListener('click', (event) => {
      // Nor in a header bar's overlay: there the expand button and the days
      // open it, and a stray click on the overlay should not.
      if (options.range || panel) return;
      if (!event.target.closest('[data-mini-day], [data-mini-month], [data-mini-toggle]')) open();
    });
    miniElement.addEventListener('keydown', (event) => {
      // Only the dock itself: Enter on a day or arrow inside it is that
      // button's own click.
      if (event.target !== miniElement) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        open();
      }
    });

    close.addEventListener('click', shut);
    // The backdrop, but not the panel sitting on it.
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) shut();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      // The full calendar first, if it is open; then a half made date pick;
      // then the month overlay.
      if (!overlay.hidden) {
        if (!full?.cancelPick()) shut();
      } else if (mini.cancelPick()) {
        // Cancelled the pick; the month stays open to start again.
      } else if (panel && !mini.isCollapsed()) {
        mini.setCollapsed(true);
        head.querySelector('[data-mini-toggle]')?.focus();
      }
    });

    return {
      open,
      close: shut,
      // Repaint the selected days, and the full calendar's slider and
      // selection while it is open, after the range changes elsewhere.
      paintRange() {
        mini.paint();
        if (!overlay.hidden) full?.paintRange();
      },
      refresh() {
        mini.refresh();
        full?.refresh();
      },
    };
  }

  window.ServiceCalendar = { create, createMini, mount };
})();
