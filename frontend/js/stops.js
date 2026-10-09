
(function () {
  const STORAGE_KEY = 'nuway.selectedRoute';

  let stops = [];
  let routes = [];
  let selected = null; // null means every stop reads the same
  let onChange = null;

  function routeOf(routeId) {
    return routes.find((route) => route.id === routeId) ?? null;
  }

  // The stop's routes, in the order the config lists them. An id with no route
  // left in the config is dropped rather than shown raw.
  function routesFor(stop) {
    return routes.filter((route) => stop.routes.includes(route.id));
  }

  // Each route led by a dot in its own colour (as drawn when it is picked in
  // the Route filter), so the popup says which line is which. Names and
  // colours come from a file an administrator edits, so everything is escaped.
  function popupHtml(stop) {
    const onRoutes = routesFor(stop);
    const routeLine = onRoutes.length
      ? onRoutes.map((route) => {
        const dot = route.colour
          ? `<span class="stop-popup-route-dot" style="background: ${escapeHtml(route.colour)}"></span>`
          : '';
        return `<li>${dot}${escapeHtml(route.name)}</li>`;
      }).join('')
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
    drawRoutePath(routeOf(selected));
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
    const row = document.getElementById('route-filter-chips');
    if (!bar || !row) return;

    // With one route the choice is still highlight it or not; with none there
    // is nothing to choose from.
    bar.hidden = routes.length === 0;

    // Each route's chip is led by a dot in the route's colour, the same as in
    // the stop popups, so the chips double as the legend for route colours.
    const chip = (id, label, isActive, colour = null) => {
      const dot = colour ? `<span class="route-chip-dot" style="background: ${escapeHtml(colour)}"></span>` : '';
      return `<button type="button" class="chip${isActive ? ' is-active' : ''}" data-route="${escapeHtml(id)}">${dot}${escapeHtml(label)}</button>`;
    };
    row.innerHTML = [
      chip('all', 'All routes', selected === null),
      ...routes.map((route) => chip(route.id, route.name, route.id === selected, route.colour)),
    ].join('');
  }

  // The Focus routes chip, off by default; on fades the buses' GPS trails
  // and shows the selected route's line over them (js/map.js). The stops
  // themselves are always shown.
  function wireRouteFocusToggle() {
    const toggle = document.getElementById('layer-toggle-focus-route');
    if (!toggle) return;
    setRouteFocus(toggle.checked);
    toggle.addEventListener('change', () => setRouteFocus(toggle.checked));
  }

  // The basemap is muted by default (css/colours.css); this switch shows its
  // own colours, for anyone finding their way by its parks and roads.
  function wireFullColourToggle() {
    const toggle = document.getElementById('layer-toggle-full-colour');
    const mapEl = document.getElementById('map');
    if (!toggle || !mapEl) return;
    const apply = () => mapEl.classList.toggle('map-full-colour', toggle.checked);
    apply();
    toggle.addEventListener('change', apply);
  }

  function wireChips() {
    document.getElementById('route-filter-chips')?.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (chip) select(chip.dataset.route === 'all' ? null : chip.dataset.route);
    });
  }

  async function init(options = {}) {
    onChange = options.onChange ?? null;
    wireRouteFocusToggle();
    wireFullColourToggle();
    wireChips();

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
    drawRoutePath(routeOf(selected));
    setCampusBounds(stops); // js/map.js: what the Rider tab frames instead of the fleet's extent
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
