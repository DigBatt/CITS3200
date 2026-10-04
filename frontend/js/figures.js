// Figures tab (#70, #71): every GMG time usage model figure for one or more
// vehicles over a reporting period, from /api/metrics.
//
// A figure the data cannot support is shown as unavailable with the reason
// the backend gives, never as zero or a blank; js/tum.js decides which is
// which. Definitions and the period covered are stated alongside (#70).
//
// The period is chosen to the minute in Perth time and sent to the API in
// UTC. One running past now stops at now: the model would otherwise count the
// time still to come as time the fleet was not reporting, and drag every
// ratio down. The vehicles are the same chips as the dashboard's filter
// (js/vehicle-chips.js), one or more on; none on is the whole fleet.
//
// The admin page's calendar picks the same period (js/admin-calendar.js):
// setPeriod() is how its picks land here, and onPeriodChange() is how edits
// made here reach it.
//
// Figures.show() fills in a period and vehicles and opens the tab, which is
// how a block clicked in the full calendar lands here; a link of the form
// /admin?tab=figures&vehicles=1&from=<ISO>&to=<ISO> does the same on load,
// for the dashboard's calendar.
//
// Needs js/api.js, js/timeline.js, js/format.js, js/tum.js and
// js/vehicle-chips.js loaded first.

(function () {
  const els = {
    tab: document.querySelector('.app-tab[data-tab="figures"]'),
    fromInput: document.getElementById('figures-from-input'),
    toInput: document.getElementById('figures-to-input'),
    chips: document.getElementById('figures-vehicle-chips'),
    from: document.getElementById('figures-from'),
    to: document.getElementById('figures-to'),
    scope: document.getElementById('figures-scope'),
    error: document.getElementById('figures-error'),
    kpis: document.getElementById('figures-kpis'),
    time: document.getElementById('figures-time'),
  };

  // Only the newest request may draw, so a slow answer for an old period
  // cannot overwrite a newer one.
  let latest = 0;

  const chips = VehicleChips.create(els.chips, { onChange: () => load() });
  // Told when the period changes here, by hand or by show(): the calendar.
  const periodListeners = [];
  const announcePeriod = () => {
    if (!els.fromInput.value || !els.toInput.value) return;
    const period = { from: toUtc(els.fromInput.value), to: toUtc(els.toInput.value) };
    periodListeners.forEach((listener) => listener(period));
  };

  // The inputs hold Perth wall clock time, "YYYY-MM-DDTHH:MM"; the API wants
  // UTC instants. These are the only two places that conversion happens.
  const toInput = (instant) => {
    const date = new Date(instant);
    return `${Timeline.getPerthDateString(date)}T${Timeline.getPerthTimeString(date)}`;
  };
  const toUtc = (value) => Timeline.perthToUtcIso(...value.split('T'));

  function showError(message) {
    els.error.textContent = message;
    els.error.classList.toggle('visible', Boolean(message));
  }

  const unavailable = (reason) =>
    `<span class="figure-unavailable">Unavailable</span><span class="figure-reason">${escapeHtml(TUM.sentence(reason))}</span>`;

  function renderKpis(figures) {
    els.kpis.innerHTML = TUM.KPIS.map((kpi) => {
      const { value, reason } = TUM.read(figures, 'kpis', kpi.key);
      return `
        <div class="figure-card${reason ? ' is-unavailable' : ''}">
          <p class="figure-name">${escapeHtml(kpi.name)} <span class="figure-formula">${escapeHtml(kpi.formula)}</span></p>
          <p class="figure-value">${reason ? unavailable(reason) : formatPercent(value)}</p>
          <p class="figure-definition">${escapeHtml(kpi.definition)}</p>
        </div>`;
    }).join('');
  }

  // A figure that is real but needs explaining, e.g. scheduled time with no
  // roster, or how the downtime log was applied (S19). The downtime summary
  // is one bus's own, so a pool lists each vehicle's that has any.
  function notesFor(key, figures, entries) {
    if (key === 'downtime_seconds' && entries.length > 1) {
      return entries
        .filter((entry) => entry.downtime?.recorded_seconds)
        .map((entry) => `${chips.nameOf(entry.vehicle_id)}: ${entry.downtime.summary}`);
    }
    const note = figures.notes?.[key];
    return note ? [note] : [];
  }

  function renderTime(figures, entries) {
    const calendar = figures.buckets.calendar_seconds;
    els.time.innerHTML = TUM.TIME.map((category) => {
      const { value, reason } = TUM.read(figures, 'buckets', category.key);
      const cells = reason
        ? `<td colspan="2">${unavailable(reason)}</td>`
        : `<td class="mono">${formatDuration(value)}</td><td class="mono">${formatPercent(TUM.ratio(value, calendar))}</td>`;
      const notes = reason ? [] : notesFor(category.key, figures, entries);
      return `
        <tr class="${reason ? 'is-unavailable' : ''}">
          <td class="figures-time-category" style="--depth: ${category.depth}">
            <span class="figures-time-name">${escapeHtml(category.name)} <span class="figure-formula">${category.code}</span></span>
            <span class="figures-time-definition">${escapeHtml(category.definition)}</span>
            ${notes.map((note) => `<span class="figures-time-note">${escapeHtml(note)}</span>`).join('')}
          </td>
          ${cells}
        </tr>`;
    }).join('');
  }

  function clear() {
    els.from.textContent = '—';
    els.to.textContent = '—';
    els.scope.textContent = '—';
    els.kpis.innerHTML = '';
    els.time.innerHTML = '';
  }

  function render(data) {
    const entries = data.vehicles;
    els.from.textContent = formatInstant(data.from);
    els.to.textContent = formatInstant(data.to);
    // Pooled times are vehicle-hours: two buses over one day is two days of
    // calendar time. Said here so the hours in the table are not misread.
    const picked = chips.get();
    const who = picked.length
      ? picked.map((id) => chips.nameOf(id)).join(', ')
      : `All ${entries.length} vehicles`;
    els.scope.textContent = entries.length > 1 ? `${who} · times are vehicle-hours, summed` : who;

    const figures = TUM.pool(entries);
    renderKpis(figures);
    renderTime(figures, entries);
  }

  async function load() {
    const request = ++latest;
    const now = new Date();

    // Checked here as well as by the API, so the message names the fields
    // on this page rather than the API's parameters.
    let problem = '';
    if (!els.fromInput.value || !els.toInput.value) problem = 'Choose both a From and a To time.';
    const from = problem ? null : toUtc(els.fromInput.value);
    const to = problem ? null : toUtc(els.toInput.value);
    if (!problem && from >= to) problem = "'From' must be before 'To'.";
    else if (!problem && new Date(from) > now) problem = 'Future times are not available yet.';
    if (problem) {
      showError(problem);
      clear();
      return;
    }

    showError('');
    els.kpis.classList.add('is-loading');
    try {
      // Left out, `to` defaults to now on the server.
      const data = await getMetrics({
        vehicles: chips.query(),
        from,
        to: new Date(to) >= now ? undefined : to,
      });
      if (request !== latest) return;
      if (!data.vehicles.length) {
        showError('No vehicles are configured.');
        clear();
        return;
      }
      render(data);
    } catch (exc) {
      if (request !== latest) return;
      showError(`Could not load the figures: ${exc.message}`);
      clear();
    } finally {
      if (request === latest) els.kpis.classList.remove('is-loading');
    }
  }

  // Defaults to today so far, the API's own default period.
  const now = new Date();
  els.fromInput.value = `${Timeline.getPerthDateString(now)}T00:00`;
  els.toInput.value = toInput(now);

  els.fromInput.addEventListener('change', () => { announcePeriod(); load(); });
  els.toInput.addEventListener('change', () => { announcePeriod(); load(); });
  // Loaded when the tab is opened, and again on each reopening, since a
  // period running to now moves on while the tab is closed.
  els.tab.addEventListener('click', load);

  getVehicles()
    .then((data) => chips.setFleet(data.vehicles ?? []))
    .catch(() => showError('Could not load the vehicles; showing the whole fleet.'));

  /**
   * Open the tab on a period and vehicles, e.g. a block from the calendar.
   *
   * @param {{ vehicles?: string[], from: string, to: string }} what - UTC
   *   ISO instants, and vehicle ids ([] or absent for the whole fleet).
   */
  function show({ vehicles = [], from, to }) {
    chips.set(vehicles);
    els.fromInput.value = toInput(from);
    els.toInput.value = toInput(to);
    announcePeriod();
    els.tab.click(); // switches tabs (js/admin.js), which loads
    els.tab.scrollIntoView?.({ block: 'nearest' });
  }

  // A link from the dashboard's calendar:
  // /admin?tab=figures&vehicles=1,2&from=<ISO>&to=<ISO>
  const params = new URLSearchParams(window.location.search);
  if (params.get('tab') === 'figures') {
    const from = params.get('from');
    const to = params.get('to');
    const valid = (value) => value && !Number.isNaN(Date.parse(value));
    if (valid(from) && valid(to)) {
      show({ vehicles: (params.get('vehicles') || '').split(',').filter(Boolean), from, to });
    } else {
      els.tab.click();
    }
  }

  /**
   * Take a period from elsewhere, the calendar, without opening the tab or
   * announcing it back. Reloads only if the tab is on screen; otherwise
   * opening it does.
   *
   * @param {{ from: string, to: string|null }} period - UTC ISO instants;
   *   `to` null means now, as for a live period.
   */
  function setPeriod({ from, to }) {
    els.fromInput.value = toInput(from);
    els.toInput.value = toInput(to ?? new Date());
    if (!document.getElementById('tab-figures').hidden) load();
  }

  window.Figures = {
    show,
    setPeriod,
    /** The period now in From/To, as UTC ISO instants, or null if incomplete. */
    getPeriod: () => (els.fromInput.value && els.toInput.value
      ? { from: toUtc(els.fromInput.value), to: toUtc(els.toInput.value) }
      : null),
    onPeriodChange: (listener) => periodListeners.push(listener),
  };
})();
