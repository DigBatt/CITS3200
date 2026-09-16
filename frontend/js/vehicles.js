// The vehicle filter.
//
// Renders the list from /api/vehicles: the filter chips, the fleet panel rows
// and the map legend.
//
// Also owns the liveness presentation: a vehicle the server reports as
// inactive is greyed AND labelled. The threshold comes from the server; this
// module never computes liveness.
//
// Clearing the filter restores the whole fleet.
//
// The selection is one vehicle or the whole fleet. A chip or a fleet row
// selects that vehicle; "All vehicles", or the selected row again, clears it.

(function () {
  let fleet = [];
  let selected = null; // null means the whole fleet
  let onChange = null;
  let latestRefresh = 0;
  let refreshError = null;

  function nameOf(id) {
    return fleet.find((vehicle) => vehicle.id === id)?.name ?? `Vehicle ${id}`;
  }

  function select(id) {
    if (id === selected) return;
    selected = id;
    render();
    onChange?.(selected);
  }

  // Refetch liveness. Called on every load, so it keeps pace with live polling.
  async function refresh() {
    const request = ++latestRefresh;
    try {
      const data = await getVehicles();
      if (request !== latestRefresh) return;
      fleet = data.vehicles;
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
    const classes = ['vehicle-row', active ? '' : 'is-offline', vehicle.id === selected ? 'is-selected' : '']
      .filter(Boolean)
      .join(' ');
    return `
      <div class="${classes}" data-vehicle-row="${escapeHtml(vehicle.id)}">
        <div class="vehicle-row-main">
          <div class="vehicle-row-top">
            <span class="vehicle-id">${escapeHtml(nameOf(vehicle.id))}</span>
            <span class="vehicle-badge ${active ? 'badge-active' : 'badge-inactive'}">${active ? 'ACTIVE' : 'INACTIVE'}</span>
          </div>
          <div class="vehicle-note">${escapeHtml(note(vehicle))}</div>
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
      chip('all', 'All vehicles', selected === null),
      ...fleet.map((vehicle) => chip(vehicle.id, nameOf(vehicle.id), vehicle.id === selected)),
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
      if (chip) select(chip.dataset.vehicle === 'all' ? null : chip.dataset.vehicle);
    });

    document.getElementById('vehicle-list').addEventListener('click', (event) => {
      const row = event.target.closest('.vehicle-row');
      if (row) select(row.dataset.vehicleRow === selected ? null : row.dataset.vehicleRow);
    });
  }

  window.Vehicles = { init, refresh, select, nameOf, getSelection: () => selected };
})();
