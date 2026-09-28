// The vehicle filter.
//
// Renders the list from /api/vehicles: the Vehicle menu, the fleet panel rows
// and the map legend.
//
// Also owns the liveness presentation: a vehicle the server reports as
// inactive is greyed AND labelled. The threshold comes from the server; this
// module never computes liveness.
//
// Clearing the filter restores the whole fleet.
//
// The selection is one vehicle or the whole fleet. The Vehicle menu or a fleet
// row selects that vehicle; "All vehicles", or the selected row again, clears it.

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
    if (vehicle.last_seen === null) return 'No telemetry yet';
    if (vehicle.status === 'active') return `Last packet ${formatAge(vehicle.seconds_since_last_seen)} ago`;
    return `Last seen ${formatInstant(vehicle.last_seen)}`;
  }

  // Only an active vehicle's readings are current enough to show. They go in
  // the row's tooltip, since the row itself is one line; readings the vehicle
  // did not send are left out rather than shown as placeholders.
  function stats(vehicle) {
    const position = vehicle.status === 'active' ? vehicle.last_position : null;
    if (!position) return [];
    return [
      position.speed_mps === null ? null : `${(position.speed_mps * 3.6).toFixed(1)} km/h`,
      position.battery_percent === null ? null : `Battery ${Math.round(position.battery_percent)}%`,
      position.gps_status === null ? null : position.gps_status < 0 ? 'No GPS fix' : 'GPS fix',
    ].filter(Boolean);
  }

  // One line: colour dot, name, status badge, then when it last reported.
  function rowHtml(vehicle) {
    const active = vehicle.status === 'active';
    const classes = ['vehicle-row', active ? '' : 'is-offline', vehicle.id === selected ? 'is-selected' : '']
      .filter(Boolean)
      .join(' ');
    const readings = stats(vehicle);
    return `
      <div class="${classes}" data-vehicle-row="${escapeHtml(vehicle.id)}"${readings.length ? ` title="${escapeHtml(readings.join(' · '))}"` : ''}>
        <span class="vehicle-dot" style="background: ${escapeHtml(vehicle.colour ?? 'var(--text-3)')}"></span>
        <span class="vehicle-id">${escapeHtml(nameOf(vehicle.id))}</span>
        <span class="vehicle-badge ${active ? 'badge-active' : 'badge-inactive'}">${active ? 'ACTIVE' : 'INACTIVE'}</span>
        <span class="vehicle-note">${escapeHtml(note(vehicle))}</span>
      </div>`;
  }

  function render() {
    const active = fleet.filter((vehicle) => vehicle.status === 'active').length;
    document.getElementById('fleet-active-count').textContent = refreshError
      ? 'Unavailable'
      : `${active} / ${fleet.length} reporting`;

    // Header pill: green while at least one vehicle is reporting, amber
    // otherwise, so "Live" never looks healthy with nothing coming in.
    const reporting = !refreshError && active > 0;
    document.getElementById('app-live').classList.toggle('is-stale', !reporting);
    document.getElementById('app-live-text').textContent = reporting
      ? `Live · ${active} of ${fleet.length} reporting`
      : 'Live · no vehicle data';

    // Render runs on every live poll; rebuilding the options each time would
    // close the menu under the user, so they are replaced only when they change.
    const menu = document.getElementById('vehicle-select');
    const options = [
      '<option value="all">All vehicles</option>',
      ...fleet.map((vehicle) => `<option value="${escapeHtml(vehicle.id)}">${escapeHtml(nameOf(vehicle.id))}</option>`),
    ].join('');
    if (menu.dataset.options !== options) {
      menu.innerHTML = options;
      menu.dataset.options = options;
    }
    menu.value = selected ?? 'all';

    const dot = document.getElementById('vehicle-select-dot');
    const colour = fleet.find((vehicle) => vehicle.id === selected)?.colour;
    dot.hidden = !colour;
    dot.style.background = colour ?? '';

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

    document.getElementById('vehicle-select').addEventListener('change', (event) => {
      select(event.target.value === 'all' ? null : event.target.value);
    });

    document.getElementById('vehicle-list').addEventListener('click', (event) => {
      const row = event.target.closest('.vehicle-row');
      if (row) select(row.dataset.vehicleRow === selected ? null : row.dataset.vehicleRow);
    });
  }

  window.Vehicles = { init, refresh, select, nameOf, getSelection: () => selected };
})();
