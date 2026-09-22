// Utilisation: the fleet panel's KPI tiles and the Utilisation view, both
// drawn from /api/metrics for the current selection.

(function () {
  // Colours are the --util-* custom properties in dashboard.css.
  const STATES = [
    { key: 'working_seconds', code: 'WT', colour: 'wt', label: 'Working — moving' },
    { key: 'operating_delay_seconds', code: 'OD', colour: 'od', label: 'Operating delay — stopped away from depot, or no fix' },
    { key: 'standby_seconds', code: 'SB', colour: 'sb', label: 'Standby — stopped at depot' },
    { key: 'not_reporting_seconds', code: 'NR', colour: 'nr', label: 'Not reporting — no telemetry' },
  ];

  const KPIS = [
    { key: 'asset_utilisation', label: 'ASSET UTILISATION', short: 'ASSET UTIL.', formula: 'OT / CT' },
    { key: 'effective_utilisation', label: 'EFFECTIVE UTILISATION', short: 'EFF. UTIL.', formula: 'WT in ST / ST' },
    { key: 'operating_efficiency', label: 'OPERATING EFFICIENCY', short: 'OP. EFF.', formula: 'WT / OT' },
  ];

  const BUCKETS = ['calendar_seconds', 'operating_seconds', 'scheduled_seconds', 'scheduled_working_seconds', 'unscheduled_seconds', ...STATES.map((s) => s.key)];

  const EMPTY = { buckets: {}, kpis: {}, unavailable: {}, notes: {} };

  // The roster behind the scheduled row, fetched once. Null until it loads.
  let schedule = null;

  const ratio = (part, whole) => (part != null && whole ? part / whole : null);

  // One vehicle's figures, or the selection's pooled into one.
  function pool(entries) {
    if (entries.length === 1) return entries[0];

    const buckets = {};
    for (const key of BUCKETS) {
      buckets[key] = entries.every((entry) => entry.buckets[key] != null)
        ? entries.reduce((total, entry) => total + entry.buckets[key], 0)
        : null;
    }

    const kpis = {
      asset_utilisation: ratio(buckets.operating_seconds, buckets.calendar_seconds),
      effective_utilisation: ratio(buckets.scheduled_working_seconds, buckets.scheduled_seconds),
      operating_efficiency: ratio(buckets.working_seconds, buckets.operating_seconds),
    };

    // A reason, or a note, holds for the pool only if it holds for every vehicle.
    const unavailable = {};
    const notes = {};
    for (const key of [...BUCKETS, ...KPIS.map((kpi) => kpi.key)]) {
      if (entries.every((entry) => entry.unavailable[key])) unavailable[key] = entries[0].unavailable[key];
      if (entries.every((entry) => entry.notes?.[key])) notes[key] = entries[0].notes[key];
    }

    return { buckets, kpis, unavailable, notes };
  }

  function renderKpis(figures) {
    document.getElementById('fleet-kpis').innerHTML = KPIS.map((kpi) => `
      <div class="kpi-mini" title="${escapeHtml(figures.unavailable[kpi.key] ?? kpi.formula)}">
        <span class="kpi-mini-label">${kpi.short}</span>
        <span class="kpi-mini-value">${formatPercent(figures.kpis[kpi.key])}</span>
      </div>`).join('');

    document.getElementById('util-kpis').innerHTML = KPIS.map((kpi) => `
      <div class="util-kpi-card">
        <span class="util-kpi-label">${kpi.label}</span>
        <span class="util-kpi-value">${formatPercent(figures.kpis[kpi.key])}</span>
        <span class="util-kpi-formula">${escapeHtml(figures.unavailable[kpi.key] ?? kpi.formula)}</span>
      </div>`).join('');
  }

  function renderPie(figures) {
    const calendar = figures.buckets.calendar_seconds;
    let angle = 0;
    const stops = STATES.map((state) => {
      const start = angle;
      angle += (ratio(figures.buckets[state.key], calendar) ?? 0) * 360;
      return `var(--util-${state.colour}) ${start}deg ${angle}deg`;
    });

    document.getElementById('util-pie').style.background = calendar ? `conic-gradient(${stops.join(', ')})` : '';
    document.getElementById('util-pie-value').textContent = formatPercent(figures.kpis.asset_utilisation);

    document.getElementById('util-legend').innerHTML = !calendar ? '' : STATES.map((state) => {
      const reason = figures.unavailable[state.key];
      const seconds = figures.buckets[state.key];
      return `
        <div class="util-legend-item"${reason ? ` title="${escapeHtml(reason)}"` : ''}>
          <span class="util-legend-swatch" style="background: var(--util-${state.colour})"></span>
          <span class="util-legend-label">${escapeHtml(state.label)}</span>
          <span class="util-legend-hours">${reason ? '—' : formatDuration(seconds)}</span>
          <span class="util-legend-pct">${reason ? '—' : formatPercent(ratio(seconds, calendar))}</span>
        </div>`;
    }).join('');
  }

  function renderTimeModel(figures, pooled) {
    const b = figures.buckets;
    const calendar = b.calendar_seconds;
    const title = document.getElementById('util-tum-title');
    const rows = document.getElementById('util-tum-rows');
    const legend = document.getElementById('util-tum-legend');

    if (!calendar) {
      title.textContent = 'Time usage model';
      rows.innerHTML = '';
      legend.innerHTML = '';
      return;
    }

    title.textContent = `Time usage model · Calendar time ${formatDuration(calendar)}${pooled ? ' (vehicle-hours, pooled)' : ''}`;

    // A segment wide enough for its name gets it; a narrow one gets its code.
    const segment = (colour, seconds, name, code) => {
      if (!seconds) return '';
      const text = `${name} (${code}) · ${formatDuration(seconds)}`;
      const major = seconds / calendar >= 0.2;
      return `<span class="util-tum-seg${major ? ' is-major' : ''}" style="flex: ${seconds} 1 0; background: var(--util-${colour})" title="${escapeHtml(text)}">${escapeHtml(major ? text : code)}</span>`;
    };
    const ghost = (seconds) => (seconds ? `<span class="util-tum-seg is-ghost" style="flex: ${seconds} 1 0"></span>` : '');
    const row = (segments) => `<div class="util-tum-row">${segments.join('')}</div>`;

    const scheduledRow = b.scheduled_seconds == null
      ? `<span class="util-tum-seg is-ghost is-major" style="flex: 1">${escapeHtml(figures.unavailable.scheduled_seconds ?? 'Scheduled time unknown')}</span>`
      : segment('st', b.scheduled_seconds, 'Scheduled', 'ST') + segment('ut', b.unscheduled_seconds, 'Unscheduled', 'UT');

    rows.innerHTML = [
      row([segment('ct', calendar, 'Calendar time', 'CT')]),
      row([
        segment('ot', b.operating_seconds, 'Operating time', 'OT'),
        segment('sb', b.standby_seconds, 'Standby', 'SB'),
        segment('nr', b.not_reporting_seconds, 'Not reporting', 'NR'),
      ]),
      row([
        segment('wt', b.working_seconds, 'Working time', 'WT'),
        segment('od', b.operating_delay_seconds, 'Operating delay', 'OD'),
        ghost(b.standby_seconds),
        ghost(b.not_reporting_seconds),
      ]),
      `<span class="util-tum-caption">${escapeHtml(rosterCaption(figures))}</span>`,
      row([scheduledRow]),
    ].join('');

    const entries = [
      ...STATES.map((state) => [state.colour, state.code, b[state.key]]),
      ['st', 'ST', b.scheduled_seconds],
      ['ut', 'UT', b.unscheduled_seconds],
    ];
    legend.innerHTML = entries
      .map(([colour, code, seconds]) => `<span><span class="util-legend-swatch" style="background: var(--util-${colour})"></span>${code} ${formatDuration(seconds)}</span>`)
      .join('');
  }

  // S21: what the scheduled row is measured against. An empty roster is a
  // real state, not a missing figure, so it is said plainly rather than left
  // to read as though the fleet never ran.
  function rosterCaption(figures) {
    const note = figures.notes?.scheduled_seconds;
    if (note) return note;
    if (!schedule) return 'Against the service roster';

    const days = Object.entries(schedule.schedule ?? {}).filter(([, periods]) => periods.length);
    if (!days.length) return 'Against the service roster';

    const shown = days
      .map(([day, periods]) => `${day.slice(0, 3)} ${periods.map((p) => `${p[0]}-${p[1]}`).join(', ')}`)
      .join(' · ');
    return `Against the service roster · ${shown}${schedule.timezone ? ` (${schedule.timezone})` : ''}`;
  }

  function renderTable(entries, total) {
    const columns = ['VEHICLE', ...KPIS.map((kpi) => kpi.short), 'WORKING', 'NOT REPORTING'];
    const row = (name, figures, attributes) => `
      <div ${attributes}>
        <span class="util-table-name">${escapeHtml(name)}</span>
        ${KPIS.map((kpi) => `<span>${formatPercent(figures.kpis[kpi.key])}</span>`).join('')}
        <span>${formatDuration(figures.buckets.working_seconds)}</span>
        <span>${formatDuration(figures.buckets.not_reporting_seconds)}</span>
      </div>`;

    document.getElementById('util-table').innerHTML = !entries.length ? '' : [
      `<div class="util-table-header">${columns.map((column) => `<span>${column}</span>`).join('')}</div>`,
      ...entries.map((entry) =>
        row(Vehicles.nameOf(entry.vehicle_id), entry, `class="util-table-row" data-vehicle="${escapeHtml(entry.vehicle_id)}"`)),
      total ? row('Fleet total', total, 'class="util-table-row util-table-average"') : '',
    ].join('');
  }

  function draw(figures, entries, pooled) {
    renderKpis(figures);
    renderPie(figures);
    renderTimeModel(figures, pooled);
    renderTable(entries, pooled ? figures : null);
  }

  function render(data) {
    const entries = data.vehicles;
    if (!entries.length) return showError('No vehicles selected.');

    const pooled = entries.length > 1;
    const scope = pooled ? `Fleet total · ${entries.length} vehicles` : Vehicles.nameOf(entries[0].vehicle_id);
    document.getElementById('util-scope').textContent = `${scope} · ${formatInstant(data.from)} → ${formatInstant(data.to)}`;
    draw(pool(entries), entries, pooled);
  }

  function showError(message) {
    document.getElementById('util-scope').textContent = `Utilisation unavailable: ${message}`;
    draw(EMPTY, [], false);
  }

  document.addEventListener('DOMContentLoaded', () => {
    // The roster is small and changes rarely, so it is read once rather than
    // on every selection change.
    getSchedule().then((data) => { schedule = data; }).catch(() => { schedule = null; });

    // A vehicle's row in the table scopes the whole dashboard to it.
    document.getElementById('util-table').addEventListener('click', (event) => {
      const row = event.target.closest('[data-vehicle]');
      if (row) Vehicles.select(row.dataset.vehicle);
    });
  });

  window.Utilisation = { render, showError };
})();
