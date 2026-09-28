
(function () {
  const STORAGE_KEY = 'nuway.selectedRoute';

  let stops = [];
  let routes = [];
  let selected = null; // null means every stop reads the same
  let onChange = null;

  function routeOf(routeId) {
    return routes.find((route) => route.id === routeId) ?? null;
  }

  // Names, in the order the config lists the routes. An id with no route left
  // in the config is dropped rather than shown raw.
  function routeNamesFor(stop) {
    return routes.filter((route) => stop.routes.includes(route.id)).map((route) => route.name);
  }

  // Names come from a file an administrator edits, so everything is escaped.
  function popupHtml(stop) {
    const names = routeNamesFor(stop);
    const routeLine = names.length
      ? names.map((name) => `<li>${escapeHtml(name)}</li>`).join('')
      : '<li class="is-empty">Not on any route</li>';
    return `
      <div class="stop-popup-id">${escapeHtml(stop.id)}</div>
      <div class="stop-popup-name">${escapeHtml(stop.name)}</div>
      <div class="stop-popup-label">ROUTES</div>
      <ul class="stop-popup-routes">${routeLine}</ul>`;
  }

  function select(routeId) {
    if (routeId === selected) return;
    selected = routeId;
    remember(routeId);
    render();
    highlightRoute(stops, selected, routeOf(selected)?.colour);
    onChange?.(selected);
  }

  // blocked or cleared store just means the
  // dashboard opens on all routes.
  function remember(routeId) {
    try {
      if (routeId === null) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, routeId);
    } catch (error) {
      /* storage unavailable */
    }
  }

  function recall() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      // The route may have been renamed or removed from the config since.
      return routes.some((route) => route.id === stored) ? stored : null;
    } catch (error) {
      return null;
    }
  }

  function render() {
    const bar = document.getElementById('route-filter');
    const menu = document.getElementById('route-select');
    if (!bar || !menu) return;

    // With one route the choice is still highlight it or not; with none there
    // is nothing to choose from.
    bar.hidden = routes.length === 0;

    // A menu rather than chips: route names are long, and a chip each pushed
    // the filter bar onto a second line.
    const option = (id, label, isSelected) =>
      `<option value="${escapeHtml(id)}"${isSelected ? ' selected' : ''}>${escapeHtml(label)}</option>`;
    menu.innerHTML = [
      option('all', 'All routes', selected === null),
      ...routes.map((route) => option(route.id, route.name, route.id === selected)),
    ].join('');
  }

  function wireToggle() {
    const toggle = document.getElementById('layer-toggle-stops');
    if (!toggle) return;
    setStopsVisible(toggle.checked);
    toggle.addEventListener('change', () => setStopsVisible(toggle.checked));
  }

  function wireMenu() {
    document.getElementById('route-select')?.addEventListener('change', (event) => {
      select(event.target.value === 'all' ? null : event.target.value);
    });
  }

  async function init(options = {}) {
    onChange = options.onChange ?? null;
    wireToggle();
    wireMenu();

    try {
      const [stopsBody, routesBody] = await Promise.all([getStops(), getRoutes()]);
      stops = stopsBody.stops;
      routes = routesBody.routes;
    } catch (error) {
      console.warn(`Stops unavailable: ${error.message}`);
      return;
    }

    selected = recall();
    render();
    drawStops(stops, { popupHtml });
    highlightRoute(stops, selected, routeOf(selected)?.colour);
  }

  // In service order, which is the route's order and not the stop file's.
  function stopsOnRoute(routeId) {
    const byId = new Map(stops.map((stop) => [stop.id, stop]));
    return (routeOf(routeId)?.stop_ids ?? []).map((id) => byId.get(id)).filter(Boolean);
  }

  window.Stops = {
    init,
    select,
    stopsOnRoute,
    all: () => stops,
    allRoutes: () => routes,
    getSelectedRoute: () => selected,
  };
})();
