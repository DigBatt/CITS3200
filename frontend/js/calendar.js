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

  function clockMinutes(text) {
    const [hours, minutes] = String(text).split(':').map(Number);
    return hours * 60 + minutes;
  }

  function create(container, options = {}) {
    // The dashboard is fixed at a week; the admin page can switch.
    const fixedSpan = options.fixedDays ?? null;
    let span = fixedSpan ?? options.days ?? 3;
    // The day in focus. A 3 day view puts it in the middle, a week shows the
    // week containing it. Held as a date, not an offset, so a caller can open
    // the calendar on a day the user picked elsewhere.
    let anchor = startOfDay(options.anchor ?? new Date());

    let schedule = null;
    let vehicles = [];
    let downtime = [];
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
        const [scheduleData, vehicleData, downtimeData] = await Promise.all([
          getSchedule(),
          getVehicles(),
          getDowntime({ from: from.toISOString(), to: to.toISOString() }),
        ]);

        schedule = scheduleData;
        vehicles = vehicleData.vehicles ?? [];
        downtime = downtimeData.records ?? [];
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
      const roster = schedule?.schedule ?? {};
      return (roster[DAY_NAMES[day.getDay()]] ?? [])
        .filter((period) => !period.vehicles?.length || period.vehicles.includes(vehicleId))
        .map((period) => ({
          from: clockMinutes(period.start),
          to: clockMinutes(period.end),
          label: `${period.start}–${period.end}`,
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
        }));
    }

    const band = (from, to, className, title, text = '') =>
      `<div class="${className}" style="top:${pct(from / DAY_MINUTES)};height:${pct((to - from) / DAY_MINUTES)}" title="${escape(title)}">${escape(text)}</div>`;

    function dayColumn(day, selected) {
      const today = day.toDateString() === new Date().toDateString();
      const now = new Date();
      const width = selected.length ? 100 / selected.length : 100;
      const wide = span < 7 && selected.length < 3;

      const lanes = selected
        .map((vehicle, index) => {
          const scheduled = periodsFor(day, vehicle.id)
            .map((period) =>
              band(period.from, period.to, 'cal-scheduled', `${vehicle.name ?? vehicle.id} scheduled ${period.label}`, wide ? period.label : ''),
            )
            .join('');
          const down = downtimeFor(day, vehicle.id)
            .map((block) =>
              band(block.from, block.to, 'cal-downtime', `${vehicle.name ?? vehicle.id} down ${block.label} — ${block.reason}`),
            )
            .join('');
          return `<div class="cal-lane" style="left:${pct((index * width) / 100)};width:${pct(width / 100)};--cal-vehicle:${escape(vehicle.colour ?? 'currentColor')}" title="${escape(vehicle.name ?? vehicle.id)}">${scheduled}${down}</div>`;
        })
        .join('');

      const nowLine = today
        ? `<div class="cal-now" style="top:${pct(minutesInto(day, now) / DAY_MINUTES)}" title="Now ${escape(hhmm(now))}"><span>${escape(hhmm(now))}</span></div>`
        : '';

      return `
        <div class="cal-day${today ? ' is-today' : ''}">
          <div class="cal-day-head">
            <span class="cal-day-name">${escape(day.toLocaleDateString([], { weekday: 'short' }))}</span>
            <span class="cal-day-date">${escape(day.toLocaleDateString([], { day: '2-digit', month: 'short' }))}</span>
          </div>
          <div class="cal-day-body">
            ${HOUR_LABELS.slice(1, -1).map((hour) => `<div class="cal-gridline" style="top:${pct(hour / 24)}"></div>`).join('')}
            ${lanes || '<p class="cal-no-vehicles">No vehicles shown</p>'}
            ${nowLine}
          </div>
        </div>`;
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
          <span class="cal-range">${escape(rangeLabel())}</span>
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
            <span class="cal-key"><span class="cal-swatch is-now"></span>Now</span>
          </div>
          <div class="cal-grid">
            <div class="cal-hours">
              ${HOUR_LABELS.map((hour) => `<span style="top:${pct(hour / 24)}">${pad(hour)}:00</span>`).join('')}
            </div>
            ${days().map((day) => dayColumn(day, selected)).join('')}
          </div>
          <p class="cal-caption">${escape(caption())}</p>
        </div>`;
    }

    container.addEventListener('click', (event) => {
      const vehicle = event.target.closest('[data-cal-vehicle]');
      const step = event.target.closest('[data-cal-step]');
      const view = event.target.closest('[data-cal-span]');

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

    refresh();
    timer = setInterval(render, 60000);

    return {
      refresh,
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


  // ---- Mini month ----
  //
  // A month at a glance, docked on the admin page. Each day carries a mark
  // for what happened on it: service rostered, downtime reported, or both.
  // Clicking a day opens the full calendar on that day, which is why
  // ServiceCalendar.create takes an anchor.
  //
  // It says nothing about which vehicle: at this size a mark per bus would be
  // unreadable, and the full view is one click away for that.

  function createMini(container, options = {}) {
    const onOpen = options.onOpen ?? (() => {});
    let month = startOfDay(new Date());
    month.setDate(1);

    let schedule = null;
    let downtime = [];
    let error = null;

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
        const [scheduleData, downtimeData] = await Promise.all([
          getSchedule(),
          getDowntime({
            from: window[0].toISOString(),
            to: new Date(window[41].getTime() + DAY_MS).toISOString(),
          }),
        ]);
        schedule = scheduleData;
        downtime = downtimeData.records ?? [];
        error = null;
      } catch (exc) {
        error = exc.message;
      }
      render();
    }

    const hasService = (day) => Boolean((schedule?.schedule ?? {})[DAY_NAMES[day.getDay()]]?.length);

    const hasDowntime = (day) => {
      const next = new Date(day.getTime() + DAY_MS);
      return downtime.some((record) => new Date(record.start) < next && new Date(record.end) > day);
    };

    function render() {
      if (error) {
        container.innerHTML = `<p class="cal-error">${escape(error)}</p>`;
        return;
      }
      if (!schedule) {
        container.innerHTML = '<p class="cal-empty">Loading…</p>';
        return;
      }

      const today = startOfDay(new Date()).getTime();
      const grid = cells()
        .map((day) => {
          const marks = [
            hasService(day) ? '<span class="mini-mark is-service"></span>' : '',
            hasDowntime(day) ? '<span class="mini-mark is-downtime"></span>' : '',
          ].join('');
          const classes = [
            'mini-day',
            day.getMonth() === month.getMonth() ? '' : 'is-outside',
            day.getTime() === today ? 'is-today' : '',
          ].filter(Boolean).join(' ');
          return `<button type="button" class="${classes}" data-mini-day="${day.toISOString()}">
                    <span class="mini-num">${day.getDate()}</span>
                    <span class="mini-marks">${marks}</span>
                  </button>`;
        })
        .join('');

      // No title: the dock is unlabelled by design, the overlay names itself.
      container.innerHTML = `
        <div class="mini">
          <div class="mini-head">
            <button type="button" class="mini-step" data-mini-month="-1" aria-label="Previous month">&#8249;</button>
            <span class="mini-month">${escape(month.toLocaleDateString([], { month: 'long', year: 'numeric' }))}</span>
            <button type="button" class="mini-step" data-mini-month="1" aria-label="Next month">&#8250;</button>
          </div>
          <div class="mini-dows">${['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d) => `<span>${d}</span>`).join('')}</div>
          <div class="mini-grid">${grid}</div>
          <div class="mini-legend">
            <span><span class="mini-mark is-service"></span>Service</span>
            <span><span class="mini-mark is-downtime"></span>Downtime</span>
          </div>
        </div>`;
    }

    container.addEventListener('click', (event) => {
      const step = event.target.closest('[data-mini-month]');
      const day = event.target.closest('[data-mini-day]');

      // Paging the month must not open the overlay, so it is checked first.
      if (step) {
        month = new Date(month.getFullYear(), month.getMonth() + Number(step.dataset.miniMonth), 1);
        render();
        refresh();
        return;
      }
      if (day) onOpen(new Date(day.dataset.miniDay));
    });

    refresh();
    return { refresh };
  }

  window.ServiceCalendar = { create, createMini };
})();
