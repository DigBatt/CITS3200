// Figures tab (#70, #71): every GMG time usage model figure for the whole
// fleet over a reporting period, from /api/metrics.
//
// A figure the data cannot support is shown as unavailable with the reason
// the backend gives, never as zero or a blank; js/tum.js decides which is
// which. Definitions and the period covered are stated alongside (#70).
//
// The period is whole days in Perth, which is how the API reads a bare date
// (docs/api.md). A period running to today stops at now rather than the end
// of today: the model would otherwise count the hours still to come as time
// the fleet was not reporting, and drag every ratio down.
//
// Needs js/api.js, js/timeline.js, js/format.js and js/tum.js loaded first.

(function () {
  const els = {
    tab: document.querySelector('.app-tab[data-tab="figures"]'),
    fromDate: document.getElementById('figures-from-date'),
    toDate: document.getElementById('figures-to-date'),
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

  function renderTime(figures) {
    const calendar = figures.buckets.calendar_seconds;
    els.time.innerHTML = TUM.TIME.map((category) => {
      const { value, reason } = TUM.read(figures, 'buckets', category.key);
      const cells = reason
        ? `<td colspan="2">${unavailable(reason)}</td>`
        : `<td class="mono">${formatDuration(value)}</td><td class="mono">${formatPercent(TUM.ratio(value, calendar))}</td>`;
      return `
        <tr class="${reason ? 'is-unavailable' : ''}">
          <td class="figures-time-category" style="--depth: ${category.depth}">
            <span class="figures-time-name">${escapeHtml(category.name)} <span class="figure-formula">${category.code}</span></span>
            <span class="figures-time-definition">${escapeHtml(category.definition)}</span>
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
    els.scope.textContent = entries.length > 1
      ? `All ${entries.length} vehicles · times are vehicle-hours, summed`
      : `${entries.length} vehicle`;

    const figures = TUM.pool(entries);
    renderKpis(figures);
    renderTime(figures);
  }

  async function load() {
    const request = ++latest;
    const today = Timeline.getPerthDateString();
    const from = els.fromDate.value;
    const to = els.toDate.value;

    // Checked here as well as by the API, so the message names the fields
    // on this page rather than the API's parameters.
    let problem = '';
    if (!from || !to) problem = 'Choose both a From and a To date.';
    else if (from > to) problem = "'From' must not be after 'To'.";
    else if (from > today) problem = 'Future dates are not available yet.';
    if (problem) {
      showError(problem);
      clear();
      return;
    }

    showError('');
    els.kpis.classList.add('is-loading');
    try {
      // Left out, `to` defaults to now on the server.
      const data = await getMetrics({ from, to: to >= today ? undefined : to });
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

  // Defaults to today, the API's own default period.
  const today = Timeline.getPerthDateString();
  els.fromDate.value = today;
  els.toDate.value = today;
  els.fromDate.max = today;
  els.toDate.max = today;

  els.fromDate.addEventListener('change', load);
  els.toDate.addEventListener('change', load);
  // Loaded when the tab is opened, and again on each reopening, since a
  // period running to today moves on while the tab is closed.
  els.tab.addEventListener('click', load);
})();
