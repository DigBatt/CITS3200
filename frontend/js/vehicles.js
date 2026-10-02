// The vehicle filter.
//
// Renders the list from /api/vehicles: the filter chips, the fleet panel rows
// and the map legend.
//
// Also owns the liveness presentation: a vehicle the server reports as
// inactive is greyed AND labelled. The threshold comes from the server; this
// module never computes liveness. The same goes for the green/yellow/red
// light beside "Last seen", which is the server's `freshness`.
//
// Clearing the filter restores the whole fleet.
//
// The selection is any set of vehicles, or the whole fleet. A chip or a fleet
// row adds that vehicle to the selection, or takes it out again if it was
// already in; "All vehicles" clears it. Taking out the last one, or picking
// every vehicle, is the whole fleet again.

(function () {
  let fleet = [];
  let freshnessRule = null;
  let selected = new Set(); // empty means the whole fleet
  let onChange = null;
  let latestRefresh = 0;
  let refreshError = null;

  function nameOf(id) {
    return fleet.find((vehicle) => vehicle.id === id)?.name ?? `Vehicle ${id}`;
  }

  // The selected ids in fleet order, or null for the whole fleet. Fleet order,
  // so picking 2 then 1 asks for the same as 1 then 2, and the map is not
  // refitted for a selection that has not changed.
  function getSelection() {
    if (selected.size === 0) return null;
    const order = fleet.map((vehicle) => vehicle.id);
    return [...selected].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  }

  // Replace the selection: one id, a list of ids, or null for the whole fleet.
  function select(ids) {
    const next = new Set(ids === null ? [] : [].concat(ids));
    if (fleet.length && fleet.every((vehicle) => next.has(vehicle.id))) next.clear();
    if (next.size === selected.size && [...next].every((id) => selected.has(id))) return;
    selected = next;
    render();
    onChange?.(getSelection());
  }

  // Add a vehicle to the selection, or take it out if it is already in.
  function toggle(id) {
    const next = new Set(selected);
    if (!next.delete(id)) next.add(id);
    select([...next]);
  }

  // Refetch liveness. Called on every load, so it keeps pace with live polling.
  async function refresh() {
    const request = ++latestRefresh;
    try {
      const data = await getVehicles();
      if (request !== latestRefresh) return;
      fleet = data.vehicles;
      freshnessRule = data.freshness_rule ?? null;
      refreshError = null;
    } catch (error) {
      if (request !== latestRefresh) return;
      refreshError = error.message;
    }
    render();
  }

  function formatAge(seconds) {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
    return `${Math.round(seconds / 3600)} h`;
  }

  function note(vehicle) {
    if (vehicle.last_seen === null) return 'No telemetry received';
    if (vehicle.status === 'active') return `Last packet ${formatAge(vehicle.seconds_since_last_seen)} ago`;
    return `Last seen ${formatInstant(vehicle.last_seen)}`;
  }

  // Spelt out for the tooltip and screen readers, since colour alone says
  // nothing to either.
  function freshnessLabel(freshness) {
    const weekdays = freshnessRule?.green_within_weekdays ?? 1;
    const days = freshnessRule?.red_after_days;
    const lastWeekday = weekdays === 1 ? 'the last weekday' : `the last ${weekdays} weekdays`;
    if (freshness === 'green') return `Seen today or on ${lastWeekday}`;
    if (freshness === 'yellow') return `Not seen since before ${lastWeekday}`;
    return days == null ? 'Not seen for a long time' : `Not seen for more than ${days} days`;
  }

  function freshnessDot(vehicle) {
    if (!vehicle.freshness) return '';
    const label = escapeHtml(freshnessLabel(vehicle.freshness));
    return `<span class="freshness-dot freshness-${escapeHtml(vehicle.freshness)}" role="img" aria-label="${label}" title="${label}"></span>`;
  }

  // Only an active vehicle's readings are current enough to show.
  function stats(vehicle) {
    const position = vehicle.status === 'active' ? vehicle.last_position : null;
    if (!position) return ['—', '—', '—'];
    return [
      position.speed_mps === null ? '— km/h' : `${(position.speed_mps * 3.6).toFixed(1)} km/h`,
      position.battery_percent === null ? '— %' : `${Math.round(position.battery_percent)}%`,
      position.gps_status === null ? 'GPS —' : position.gps_status < 0 ? 'No fix' : 'GPS fix',
    ];
  }

  function rowHtml(vehicle) {
    const active = vehicle.status === 'active';
    const classes = ['vehicle-row', active ? '' : 'is-offline', selected.has(vehicle.id) ? 'is-selected' : '']
      .filter(Boolean)
      .join(' ');
    return `
      <div class="${classes}" data-vehicle-row="${escapeHtml(vehicle.id)}">
        <div class="vehicle-row-main">
          <div class="vehicle-row-top">
            <span class="vehicle-id">${escapeHtml(nameOf(vehicle.id))}</span>
            <span class="vehicle-badge ${active ? 'badge-active' : 'badge-inactive'}">${active ? 'ACTIVE' : 'INACTIVE'}</span>
          </div>
          <div class="vehicle-note">${freshnessDot(vehicle)}${escapeHtml(note(vehicle))}</div>
          <div class="vehicle-stats">
            ${stats(vehicle).map((value) => `<span>${escapeHtml(value)}</span>`).join('')}
          </div>
        </div>
        <div class="vehicle-chip-num" style="box-shadow: inset 0 -3px 0 ${escapeHtml(vehicle.colour ?? 'transparent')}">${escapeHtml(vehicle.id.padStart(2, '0'))}</div>
      </div>`;
  }

  function render() {
    const active = fleet.filter((vehicle) => vehicle.status === 'active').length;
    document.getElementById('fleet-active-count').textContent = refreshError
      ? 'Vehicles unavailable'
      : `${active} of ${fleet.length} active`;

    const chip = (id, label, isActive) =>
      `<button type="button" class="chip${isActive ? ' is-active' : ''}" data-vehicle="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
    document.getElementById('vehicle-filter-chips').innerHTML = [
      chip('all', 'All vehicles', selected.size === 0),
      ...fleet.map((vehicle) => chip(vehicle.id, nameOf(vehicle.id), selected.has(vehicle.id))),
    ].join('');

    document.getElementById('vehicle-list').innerHTML = fleet.length
      ? fleet.map(rowHtml).join('')
      : `<p class="empty-state">${escapeHtml(refreshError ?? 'No vehicles configured.')}</p>`;

    const legend = document.getElementById('map-legend');
    legend.innerHTML = fleet
      .map((vehicle) => `
        <span class="map-legend-item">
          <span class="map-legend-dot" style="background: ${escapeHtml(vehicle.colour ?? 'transparent')}"></span>${escapeHtml(nameOf(vehicle.id))}
        </span>`)
      .join('');
    legend.hidden = fleet.length === 0;
  }

  function init(options = {}) {
    onChange = options.onChange ?? null;

    document.getElementById('vehicle-filter-chips').addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (!chip) return;
      if (chip.dataset.vehicle === 'all') select(null);
      else toggle(chip.dataset.vehicle);
    });

    document.getElementById('vehicle-list').addEventListener('click', (event) => {
      const row = event.target.closest('.vehicle-row');
      if (row) toggle(row.dataset.vehicleRow);
    });
  }

  window.Vehicles = { init, refresh, select, toggle, nameOf, getSelection };
})();
