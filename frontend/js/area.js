// Named map areas a view can be pinned to (S11 follow-up): the same
// "fit to every visible vehicle" problem the Rider tab has (js/panels.js,
// js/map.js:pinMapTo()) also shows up on Fleet -- nUWAy 2 runs in Eglinton,
// far enough from the rest of the fleet that fitting to everyone zooms the
// whole map out past useful. The chips here let an operator pin to one area
// instead, the same chip-row pattern as js/vehicles.js and the route filter
// (js/stops.js).

(function () {
  const STORAGE_KEY = 'nuway.selectedArea';

  // nUWAy 2 runs along Viridian Boulevard in Eglinton, from the Marmion
  // Avenue corner down to the Amberton Beach carpark
  // (https://therevproject.com/tracking/nuway2.php). Unlike UWA -- whose
  // bounds track the configured stops, js/map.js:getCampusBounds() -- there
  // is no config to read an exact extent from here, so this is a fixed box
  // generous enough to cover that corridor without surveyed road
  // coordinates: PLACEHOLDER, tighten it once an Eglinton stop (or similar)
  // is configured.
  const EGLINTON_BOUNDS = L.latLngBounds([-31.604, 115.660], [-31.585, 115.683]);

  const AREAS = [
    { id: 'uwa', label: 'UWA Campus', boundsFn: getCampusBounds },
    { id: 'eglinton', label: 'Eglinton', boundsFn: () => EGLINTON_BOUNDS },
  ];

  let selected = null; // null means every vehicle, the normal framing

  function areaOf(id) {
    return AREAS.find((area) => area.id === id) ?? null;
  }

  function applyPin(id) {
    const area = areaOf(id);
    if (area) pinMapTo(area.boundsFn);
    else unpinMap();
  }

  function select(id) {
    if (id === selected) return;
    selected = id;
    remember(id);
    render();
    applyPin(id);
  }

  // Re-applies a selection's pin even if it is already `selected` -- for when
  // something else has changed the map's actual pin without going through
  // select(), so select()'s own "nothing to do" guard above would otherwise
  // wrongly leave it alone. The Rider tab is the one case of this: it pins to
  // the campus itself (js/panels.js:enterRiderDefaults()) regardless of
  // whatever area was selected, so leaving it must unconditionally put the
  // real pin back, not just confirm the id hasn't changed.
  function restore(id) {
    selected = id;
    remember(id);
    render();
    applyPin(id);
  }

  // A blocked or cleared store just means the dashboard opens on every area.
  function remember(id) {
    try {
      if (id === null) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, id);
    } catch (error) {
      /* storage unavailable */
    }
  }

  function recall() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return AREAS.some((area) => area.id === stored) ? stored : null;
    } catch (error) {
      return null;
    }
  }

  function render() {
    const row = document.getElementById('area-filter-chips');
    if (!row) return;

    const chip = (id, label, isActive) =>
      `<button type="button" class="chip${isActive ? ' is-active' : ''}" data-area="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
    row.innerHTML = [
      chip('all', 'All areas', selected === null),
      ...AREAS.map((area) => chip(area.id, area.label, area.id === selected)),
    ].join('');
  }

  function wireChips() {
    document.getElementById('area-filter-chips')?.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (chip) select(chip.dataset.area === 'all' ? null : chip.dataset.area);
    });
  }

  function init() {
    wireChips();
    selected = recall();
    render();
    const area = areaOf(selected);
    if (area) pinMapTo(area.boundsFn); // may not resolve to bounds yet (UWA, before stops load) -- setCampusBounds() picks it up once they do
  }

  window.Area = {
    init,
    select,
    restore,
    getSelection: () => selected,
  };
})();
