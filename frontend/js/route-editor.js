// Route editor (admin page, Routes tab).
//
// Stops are the nodes of the network: one record each, shared by every route
// that serves them, so moving or renaming a stop changes it everywhere. A
// route is a path through them, in order, shaped by guide points that are
// never stops. Each leg, the stretch arriving at a point, follows the campus
// paths (backend/path_network.py) unless it is drawn straight, for a way the
// map does not have.
//
//   GET  /api/network         stops and routes, each route with its points
//   GET  /api/network/paths   the campus paths, drawn faintly and snapped to
//   POST /api/network/legs    a route's legs, worked out as points change
//   PUT  /api/network         save: rewrites config/stops.json
//
// Nothing is written until Save. Every edit can be undone (Ctrl+Z) and
// redone (Ctrl+R, or Ctrl+Shift+Z / Ctrl+Y) until then; Cmd works as Ctrl.
// Double-click a guide point to remove it, or a stop to take it off the open
// route. Select a point (click it, or its row) to set whether it snaps onto
// the campus paths; a point that does not can sit anywhere, such as across a
// lawn the map has no path over. AUTH (S13): every call is admin only.

(function () {
  const COLOURS = ['#D4741F', '#1F7FD4', '#2E7D32', '#C2185B', '#6A1B9A', '#00838F', '#8D6E63', '#F9A825'];
  // How close, in screen pixels, a click must be to a stop to pick it.
  const PICK_PX = 14;
  // How far, in metres, a new point snaps onto a path.
  const SNAP_M = 25;

  const el = (id) => document.getElementById(id);

  // ---- State ----
  //
  // stops:  Map of ref -> {id, ref, name, latitude, longitude}. A saved stop's
  //         ref is its id; a new one's is "new-N" until it is saved.
  // routes: [{id, ref, name, colour, loop, points}], each point
  //         {stop: ref} or {latitude, longitude}, with `straight` and the
  //         `path` of the leg arriving at it.
  let saved = null;      // the last loaded network, for Discard
  let stops = new Map();
  let routes = [];
  let selected = null;   // ref of the route open in the sidebar
  let selectedPoint = null; // uid of the selected point on the open route
  // Each point gets a uid, so a selection survives reordering and undo.
  let uidCount = 0;
  const uid = () => `p${++uidCount}`;
  let addMode = 'guide';
  let dirty = false;
  let newCount = 0;
  let paths = null;      // {nodes, edges, attribution}, or null without a snapshot
  let map = null;
  const layers = {};

  // ---- Undo and redo ----
  //
  // A snapshot of the whole editable state before each edit. Paths are in
  // it too, so undoing never waits on the server.
  const HISTORY_LIMIT = 100;
  let undoStack = [];
  let redoStack = [];

  const snapshot = () => structuredClone({ stops: [...stops.values()], routes, selected, selectedPoint, newCount });

  function restore(state) {
    stops = new Map(state.stops.map((stop) => [stop.ref, stop]));
    routes = state.routes;
    selected = state.selected;
    newCount = state.newCount;
    selectedPoint = state.selectedPoint;
  }

  // Call before changing anything.
  function record() {
    undoStack.push(snapshot());
    if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
    redoStack = [];
    updateHistoryButtons();
  }

  function clearHistory() {
    undoStack = [];
    redoStack = [];
    updateHistoryButtons();
  }

  function step(from, to, verb) {
    if (!from.length) return;
    to.push(snapshot());
    restore(from.pop());
    // History starts at the last load or save, so with nothing left to undo
    // the editor is back to what is saved.
    setDirty(undoStack.length > 0);
    renderAll();
    drawAll();
    updateHistoryButtons();
    flash(verb);
  }
  const undo = () => step(undoStack, redoStack, 'Undone.');
  const redo = () => step(redoStack, undoStack, 'Redone.');

  function updateHistoryButtons() {
    const undoButton = el('net-undo'), redoButton = el('net-redo');
    if (undoButton) undoButton.disabled = !undoStack.length;
    if (redoButton) redoButton.disabled = !redoStack.length;
  }

  const stopOf = (ref) => stops.get(ref);
  const routeOf = (ref) => routes.find((route) => route.ref === ref);
  const current = () => routeOf(selected);
  const positionOf = (point) => {
    if (point.stop != null) {
      const stop = stopOf(point.stop);
      return [stop.latitude, stop.longitude];
    }
    return [point.latitude, point.longitude];
  };
  const routesServing = (ref) => routes.filter((route) => route.points.some((p) => p.stop === ref));

  function fromServer(data) {
    stops = new Map(data.stops.map((stop) => [stop.id, { ...stop, ref: stop.id, snap: stop.snap ?? true }]));
    routes = data.routes.map((route) => ({
      id: route.id,
      ref: route.id,
      name: route.name,
      colour: route.colour ?? '#D4741F',
      loop: route.loop,
      points: route.points.map((point) => ({
        uid: uid(),
        ...(point.stop_id != null ? { stop: point.stop_id } : { latitude: point.latitude, longitude: point.longitude, snap: point.snap ?? true }),
        straight: point.straight,
        path: point.path,
      })),
    }));
    if (selected && !routeOf(selected)) selected = null;
    selectedPoint = null;
  }

  function setDirty(value = true) {
    dirty = value;
    el('net-save').disabled = !dirty;
    el('net-discard').disabled = !dirty;
    el('net-status').textContent = dirty ? 'Unsaved changes.' : '';
  }

  function showError(message) {
    const box = el('net-error');
    box.textContent = message ? `⚠ ${message}` : '';
    box.classList.toggle('visible', Boolean(message));
  }

  // ---- Geometry ----

  const toRad = (d) => (d * Math.PI) / 180;
  function metres(a, b) {
    const x = toRad(b[1] - a[1]) * Math.cos(toRad((a[0] + b[0]) / 2));
    const y = toRad(b[0] - a[0]);
    return 6371008.8 * Math.hypot(x, y);
  }

  // The nearest place on the campus paths, if within SNAP_M and snapping.
  // Whether a point snaps: a stop's setting is on the stop, shared by every
  // route; a guide point's is its own. New points take the map's default.
  const snapsByDefault = () => el('net-snap').checked;
  const snapOf = (point) => (point.stop != null ? stopOf(point.stop).snap : point.snap) !== false;

  function snapToPaths(latlng, enabled = snapsByDefault()) {
    if (!paths || !enabled) return latlng;
    const k = Math.cos(toRad(latlng[0]));
    let best = null;
    for (const [u, v] of paths.edges) {
      const a = paths.nodes[u], b = paths.nodes[v];
      const ax = (a[1] - latlng[1]) * k, ay = a[0] - latlng[0];
      const dx = (b[1] - a[1]) * k, dy = b[0] - a[0];
      const span = dx * dx + dy * dy;
      const t = span === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / span));
      const point = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
      const d = metres(latlng, point);
      if (!best || d < best.d) best = { point, d };
    }
    return best && best.d <= SNAP_M ? best.point : latlng;
  }

  // ---- Legs ----

  // Work out every leg of these routes again, on the server, which routes
  // along the same path network the saved file will use. Meanwhile each
  // changed leg shows as a straight line, so a drag never waits on the
  // network.
  async function refreshLegs(targets) {
    for (const route of targets) {
      route.points.forEach((point, i) => {
        if (i === 0 && !route.loop) { point.path = []; return; }
        const before = route.points[(i - 1 + route.points.length) % route.points.length];
        point.path = [positionOf(before), positionOf(point)];
      });
    }
    drawAll();
    try {
      await Promise.all(targets.map(async (route) => {
        const body = {
          loop: route.loop,
          points: route.points.map((point) => {
            const [latitude, longitude] = positionOf(point);
            return { latitude, longitude, straight: point.straight };
          }),
        };
        // Only the newest answer for a route lands: an older one, or one for
        // a route that has since been undone, is dropped.
        const version = route.legsVersion = (route.legsVersion ?? 0) + 1;
        const data = await api('/api/network/legs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (route.legsVersion !== version || !routes.includes(route)) return;
        data.legs.forEach((leg, i) => {
          if (route.points[i]) {
            route.points[i].path = leg?.path ?? [];
            route.points[i].routed = leg?.routed ?? true;
          }
        });
      }));
    } catch (err) {
      showError(`Could not work out the route's legs: ${err.message}`);
    }
    drawAll();
  }

  // ---- Map ----

  function initMap() {
    map = L.map('net-map', { zoomControl: true }).setView([-31.98133, 115.81797], 16);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);
    map.createPane('net-paths').style.zIndex = 330;
    map.createPane('net-others').style.zIndex = 340;
    map.createPane('net-route').style.zIndex = 360;
    layers.paths = L.layerGroup().addTo(map);
    layers.others = L.layerGroup().addTo(map);
    layers.route = L.layerGroup().addTo(map);
    layers.points = L.layerGroup().addTo(map);
    // Clicks wait to see whether they are a double-click, which zooms the
    // map as usual instead of placing two points.
    map.on('click', (e) => onSingleClick(() => onMapClick(e)));
    map.on('dblclick', cancelSingleClick);
    el('net-show-paths').addEventListener('change', drawPaths);
  }

  function drawPaths() {
    layers.paths.clearLayers();
    if (!paths || !el('net-show-paths').checked) return;
    const lines = paths.edges.map(([u, v]) => [paths.nodes[u], paths.nodes[v]]);
    // Blue rather than grey: the tiles draw footpaths in greys already, and
    // these are the ones a leg can actually follow.
    L.polyline(lines, {
      pane: 'net-paths', color: '#0284c7', weight: 2.5, opacity: 0.5, interactive: false,
    }).addTo(layers.paths);
  }

  function drawAll() {
    if (!map) return;
    layers.others.clearLayers();
    layers.route.clearLayers();
    layers.points.clearLayers();

    // Every other route, faint, so a new one can be drawn alongside them.
    for (const route of routes) {
      if (route.ref === selected) continue;
      const line = route.points.flatMap((p) => p.path ?? []);
      if (line.length > 1) {
        L.polyline(line, { pane: 'net-others', color: route.colour, weight: 3, opacity: 0.3, interactive: false })
          .addTo(layers.others);
      }
    }

    const route = current();
    if (route) {
      // One line per leg: solid along the paths, dashed where drawn straight.
      // Clicking a leg puts a guide point in it there.
      route.points.forEach((point, i) => {
        if (!point.path || point.path.length < 2) return;
        const straight = point.straight || point.routed === false;
        L.polyline(point.path, {
          pane: 'net-route', color: route.colour, weight: 5, opacity: 0.9,
          dashArray: straight ? '6 6' : null, lineCap: 'round',
        })
          .on('click', (e) => { L.DomEvent.stopPropagation(e); onSingleClick(() => insertGuide(i, e.latlng)); })
          .on('dblclick', (e) => { L.DomEvent.stopPropagation(e); cancelSingleClick(); })
          .bindTooltip(straight ? 'Drawn straight · click to add a guide point' : 'Follows the paths · click to add a guide point', { sticky: true })
          .addTo(layers.route);
      });
    }

    // Stops: numbered when on the open route, grey when not.
    const order = new Map();
    if (route) route.points.forEach((p, i) => { if (p.stop != null) order.set(p.stop, i); });
    let number = 0;
    const numbers = new Map([...order.keys()].map((ref) => [ref, ++number]));
    const chosen = route?.points.find((p) => p.uid === selectedPoint);
    for (const stop of stops.values()) {
      const on = order.has(stop.ref);
      const classes = ['net-stop', on && 'is-on', chosen?.stop === stop.ref && 'is-selected', stop.snap === false && 'is-free']
        .filter(Boolean).join(' ');
      const marker = L.marker([stop.latitude, stop.longitude], {
        draggable: true,
        icon: L.divIcon({
          className: 'net-stop-icon',
          html: `<span class="${classes}" style="--net-colour:${escHtml(route?.colour ?? '#1c1917')}">${on ? numbers.get(stop.ref) : ''}</span>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        }),
        zIndexOffset: on ? 1000 : 0,
      });
      marker.bindTooltip(escHtml(stop.name) + (stop.snap === false ? ' · free, not snapped' : ''), { direction: 'top', offset: [0, -10] });
      marker.on('click', (e) => { L.DomEvent.stopPropagation(e); onSingleClick(() => addStopToRoute(stop.ref)); });
      marker.on('dblclick', (e) => { L.DomEvent.stopPropagation(e); cancelSingleClick(); removeStopByDoubleClick(stop.ref); });
      marker.on('dragstart', record);
      marker.on('drag', (e) => moveStopLive(stop, e.target.getLatLng()));
      marker.on('dragend', (e) => moveStop(stop, e.target.getLatLng()));
      marker.addTo(layers.points);
    }

    // Guide points: small, and only those of the open route.
    if (route) {
      route.points.forEach((point, i) => {
        if (point.stop != null) return;
        const classes = ['net-guide', point.uid === selectedPoint && 'is-selected', point.snap === false && 'is-free']
          .filter(Boolean).join(' ');
        L.marker([point.latitude, point.longitude], {
          draggable: true,
          icon: L.divIcon({ className: 'net-guide-icon', html: `<span class="${classes}"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] }),
          title: `Guide point ${i + 1}${point.snap === false ? ' (free)' : ''}`,
          zIndexOffset: point.uid === selectedPoint ? 1500 : 500,
        })
          .on('click', (e) => { L.DomEvent.stopPropagation(e); onSingleClick(() => selectPoint(point.uid)); })
          .on('dblclick', (e) => { L.DomEvent.stopPropagation(e); cancelSingleClick(); removePoint(i); })
          .on('contextmenu', (e) => { L.DomEvent.stopPropagation(e); removePoint(i); })
          .on('dragstart', record)
          .on('drag', (e) => moveGuideLive(route, i, e.target.getLatLng()))
          .on('dragend', (e) => moveGuide(route, i, e.target.getLatLng()))
          .addTo(layers.points);
      });
    }
  }

  // The stop under a click, if any.
  function stopNear(latlng) {
    const at = map.latLngToContainerPoint(latlng);
    let best = null;
    for (const stop of stops.values()) {
      const d = at.distanceTo(map.latLngToContainerPoint([stop.latitude, stop.longitude]));
      if (d <= PICK_PX && (!best || d < best.d)) best = { stop, d };
    }
    return best?.stop ?? null;
  }

  // A click on a marker is held back briefly, so the first click of a
  // double-click does not add the stop it is about to remove.
  const DOUBLE_CLICK_MS = 250;
  let pendingClick = null;
  function onSingleClick(action) {
    cancelSingleClick();
    pendingClick = setTimeout(() => { pendingClick = null; action(); }, DOUBLE_CLICK_MS);
  }
  function cancelSingleClick() {
    clearTimeout(pendingClick);
    pendingClick = null;
  }

  // On the open route: take the stop off it, and nothing else, since other
  // routes may serve it. With no route open: delete the stop. Both undo.
  function removeStopByDoubleClick(ref) {
    const route = current();
    if (!route) { deleteStop(ref); return; }
    const index = route.points.findIndex((p) => p.stop === ref);
    if (index < 0) return;
    removePoint(index);
    flash(`Took ${stopOf(ref).name} off this route. Ctrl+Z to undo.`);
  }

  function onMapClick(e) {
    const near = stopNear(e.latlng);
    if (near) { addStopToRoute(near.ref); return; }
    const at = snapToPaths([e.latlng.lat, e.latlng.lng]);
    const route = current();
    record();
    if (!route) {
      // No route open: the map places stops, for a route to use later.
      const stop = newStop(at);
      renderAll();
      drawAll();
      flash(`Added ${stop.name}. Rename it in the stop list.`);
      return;
    }
    if (addMode === 'stop') {
      const stop = newStop(at);
      const point = { uid: uid(), stop: stop.ref, straight: false, path: [] };
      route.points.push(point);
      selectedPoint = point.uid;
    } else {
      const point = { uid: uid(), latitude: at[0], longitude: at[1], snap: snapsByDefault(), straight: false, path: [] };
      route.points.push(point);
      selectedPoint = point.uid;
    }
    changed([route]);
  }

  // ---- Edits ----

  function changed(targets = [current()].filter(Boolean)) {
    setDirty();
    renderAll();
    refreshLegs(targets);
  }

  function newStop([latitude, longitude], name) {
    const ref = `new-${++newCount}`;
    const stop = { id: null, ref, name: name ?? `New stop ${newCount}`, latitude, longitude, snap: snapsByDefault() };
    stops.set(ref, stop);
    setDirty();
    return stop;
  }

  function addStopToRoute(ref) {
    const route = current();
    if (!route) { focusStop(ref); return; }
    const already = route.points.find((p) => p.stop === ref);
    if (already) {
      // Already on the route: a click selects it instead.
      selectPoint(already.uid);
      return;
    }
    record();
    const point = { uid: uid(), stop: ref, straight: false, path: [] };
    route.points.push(point);
    selectedPoint = point.uid;
    changed([route]);
  }

  function insertGuide(index, latlng) {
    record();
    const route = current();
    const at = snapToPaths([latlng.lat, latlng.lng]);
    // Into the leg arriving at `index`: the new point takes the leg's first
    // half and keeps its drawing style.
    const straight = route.points[index].straight;
    const at0 = index === 0 ? route.points.length : index;
    const point = { uid: uid(), latitude: at[0], longitude: at[1], snap: snapsByDefault(), straight, path: [] };
    route.points.splice(at0, 0, point);
    selectedPoint = point.uid;
    changed([route]);
  }

  function removePoint(index) {
    record();
    const route = current();
    const [removed] = route.points.splice(index, 1);
    if (removed?.uid === selectedPoint) selectedPoint = null;
    changed([route]);
  }

  function moveGuideLive(route, index, latlng) {
    const point = route.points[index];
    point.latitude = latlng.lat;
    point.longitude = latlng.lng;
  }

  function moveGuide(route, index, latlng) {
    const at = snapToPaths([latlng.lat, latlng.lng], snapOf(route.points[index]));
    moveGuideLive(route, index, { lat: at[0], lng: at[1] });
    changed([route]);
  }

  function moveStopLive(stop, latlng) {
    stop.latitude = latlng.lat;
    stop.longitude = latlng.lng;
  }

  // A stop is shared, so moving it reroutes every route that serves it.
  function moveStop(stop, latlng) {
    const at = snapToPaths([latlng.lat, latlng.lng], stop.snap !== false);
    moveStopLive(stop, { lat: at[0], lng: at[1] });
    const serving = routesServing(stop.ref);
    if (serving.length > 1) flash(`Moved ${stop.name} on ${serving.length} routes.`);
    changed(serving);
  }

  function toggleKind(index) {
    record();
    const route = current();
    const point = route.points[index];
    if (point.stop != null) {
      // A stop becomes a guide point where it is; the stop itself stays,
      // for the other routes and to be reused.
      const [latitude, longitude] = positionOf(point);
      route.points[index] = { uid: point.uid, latitude, longitude, snap: stopOf(point.stop).snap, straight: point.straight, path: point.path };
    } else {
      // A guide point becomes a stop: an existing one right there, or a new one.
      const here = [point.latitude, point.longitude];
      const existing = [...stops.values()].find((s) => metres(here, [s.latitude, s.longitude]) < 8
        && !route.points.some((p) => p.stop === s.ref));
      const stop = existing ?? newStop(here);
      if (!existing) stop.snap = point.snap !== false;
      route.points[index] = { uid: point.uid, stop: stop.ref, straight: point.straight, path: point.path };
    }
    changed([route]);
  }

  function selectPoint(pointUid) {
    selectedPoint = selectedPoint === pointUid ? null : pointUid;
    renderSidebar();
    drawAll();
    const row = document.querySelector(`.net-point[data-uid="${pointUid}"]`);
    row?.scrollIntoView({ block: 'nearest' });
  }

  // Turn snapping on or off for one point, or one stop (on every route).
  // Turning it on pulls the point onto the nearest path, if one is close.
  function toggleSnap(target) {
    record();
    const isStop = target.stop != null || target.ref != null;
    const holder = target.stop != null ? stopOf(target.stop) : target;
    holder.snap = !(holder.snap !== false);
    const affected = target.ref != null || target.stop != null ? routesServing(holder.ref) : [current()];
    let message = `${isStop ? holder.name : 'This guide point'} can now sit anywhere.`;
    if (holder.snap) {
      const here = [holder.latitude, holder.longitude];
      const at = snapToPaths(here, true);
      if (metres(here, at) > 0.05) {
        holder.latitude = at[0];
        holder.longitude = at[1];
        message = `Snapped onto the nearest path, ${Math.round(metres(here, at))} m away.`;
      } else {
        message = paths ? `No path within ${SNAP_M} m. It will snap when dragged near one.` : 'Snaps to paths.';
      }
    }
    changed(affected.filter(Boolean));
    // After changed(), which would otherwise replace it with "Unsaved changes."
    flash(message);
  }

  function toggleStraight(index) {
    record();
    const route = current();
    route.points[index].straight = !route.points[index].straight;
    changed([route]);
  }

  function movePoint(from, to) {
    const route = current();
    if (from === to || to < 0 || to >= route.points.length) return;
    record();
    const [point] = route.points.splice(from, 1);
    route.points.splice(to, 0, point);
    changed([route]);
  }

  function deleteStop(ref) {
    record();
    const stop = stopOf(ref);
    const serving = routesServing(ref);
    for (const route of serving) route.points = route.points.filter((p) => p.stop !== ref);
    stops.delete(ref);
    flash(`Removed ${stop.name}${serving.length ? ` from ${serving.length} route${serving.length > 1 ? 's' : ''}` : ''}.`);
    changed(serving);
  }

  function newRoute() {
    record();
    const used = new Set(routes.map((r) => r.colour.toUpperCase()));
    const colour = COLOURS.find((c) => !used.has(c)) ?? COLOURS[routes.length % COLOURS.length];
    const route = { id: null, ref: `new-route-${++newCount}`, name: 'New route', colour, loop: false, points: [] };
    routes.push(route);
    selected = route.ref;
    setDirty();
    renderAll();
    drawAll();
    el('net-route-name')?.select();
  }

  function deleteRoute() {
    record();
    const route = current();
    routes = routes.filter((r) => r !== route);
    selected = null;
    flash(`Removed ${route.name}. Save to make it final.`);
    setDirty();
    renderAll();
    drawAll();
  }

  function focusStop(ref) {
    openBar(true);
    const input = document.querySelector(`[data-stop-name="${CSS.escape(ref)}"]`);
    input?.focus();
    input?.select();
    const stop = stopOf(ref);
    map?.panTo([stop.latitude, stop.longitude]);
  }

  let flashTimer = null;
  function flash(message) {
    el('net-status').textContent = message;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => setDirty(dirty), 4000);
  }

  // ---- Rendering: the bar and the sidebar ----

  function renderAll() {
    renderBar();
    renderSidebar();
  }

  function openBar(open) {
    el('net-bar-body').hidden = !open;
    el('net-bar-toggle').setAttribute('aria-expanded', String(open));
  }

  function renderBar() {
    el('net-bar-summary').textContent =
      `${routes.length} route${routes.length === 1 ? '' : 's'} · ${stops.size} stop${stops.size === 1 ? '' : 's'}`
      + (selected ? ` · editing ${current().name}` : '');

    el('net-routes').innerHTML = routes.map((route) => {
      const count = route.points.filter((p) => p.stop != null).length;
      return `
        <li>
          <button type="button" class="net-item${route.ref === selected ? ' is-on' : ''}" data-open-route="${escHtml(route.ref)}">
            <span class="net-swatch" style="background:${escHtml(route.colour)}"></span>
            <span class="net-item-name">${escHtml(route.name)}</span>
            <span class="net-item-meta">${count} stop${count === 1 ? '' : 's'}${route.loop ? ' · loop' : ''}</span>
          </button>
        </li>`;
    }).join('') || '<li class="net-empty">No routes yet.</li>';

    el('net-stops').innerHTML = [...stops.values()].map((stop) => {
      const serving = routesServing(stop.ref).length;
      return `
        <li class="net-stop-row">
          <input class="form-input net-stop-name" value="${escHtml(stop.name)}" data-stop-name="${escHtml(stop.ref)}" aria-label="Stop name">
          <span class="net-item-meta">${serving ? `${serving} route${serving === 1 ? '' : 's'}` : 'on no route'}</span>
          <button type="button" class="btn-xs net-snap-chip${stop.snap === false ? ' is-free' : ''}" data-snap-stop="${escHtml(stop.ref)}"
                  aria-pressed="${stop.snap !== false}" title="Whether dragging this stop snaps it onto a path">${stop.snap === false ? 'Free' : 'Snaps'}</button>
          <button type="button" class="btn-xs" data-find-stop="${escHtml(stop.ref)}" title="Show on the map">Find</button>
          <button type="button" class="btn-xs danger" data-delete-stop="${escHtml(stop.ref)}">Remove</button>
        </li>`;
    }).join('') || '<li class="net-empty">No stops yet.</li>';
  }

  function renderSidebar() {
    const route = current();
    const side = el('net-sidebar');
    if (!route) {
      side.innerHTML = `
        <div class="net-side-empty">
          <p><strong>Open a route</strong> from the list above, or start a new one.</p>
          <button type="button" class="btn-primary" data-new-route>New route</button>
          <p class="net-hint">With no route open, a click on the map adds a stop. Drag a stop to move it on every route that serves it.</p>
          ${paths ? '' : '<p class="net-hint">⚠ No campus path network, so every leg is drawn straight. Run <code>python -m backend.path_network refresh</code>.</p>'}
        </div>`;
      return;
    }

    let stopNumber = 0;
    const rows = route.points.map((point, i) => {
      const isStop = point.stop != null;
      const stop = isStop ? stopOf(point.stop) : null;
      const shared = isStop ? routesServing(point.stop).length - 1 : 0;
      const hasLeg = i > 0 || route.loop;
      const off = point.routed === false && !point.straight;
      const isSelected = point.uid === selectedPoint;
      const snaps = snapOf(point);
      return `
        <li class="net-point${isStop ? ' is-stop' : ''}${isSelected ? ' is-selected' : ''}" draggable="true" data-index="${i}" data-uid="${point.uid}">
          <span class="net-handle" aria-hidden="true">⋮⋮</span>
          <span class="net-point-mark" style="--net-colour:${escHtml(route.colour)}">${isStop ? ++stopNumber : ''}</span>
          <span class="net-point-body">
            ${isStop
              ? `<input class="form-input net-point-name" value="${escHtml(stop.name)}" data-stop-name="${escHtml(stop.ref)}" aria-label="Stop name">
                 ${shared > 0 ? `<span class="net-point-note">Also on ${shared} other route${shared > 1 ? 's' : ''}</span>` : ''}`
              : '<span class="net-point-label">Guide point</span>'}
            ${isSelected ? `
              <label class="net-snap-switch" title="${isStop ? 'For this stop on every route' : 'For this guide point'}">
                <input type="checkbox" data-snap-point="${point.uid}" ${snaps ? 'checked' : ''}>
                Snap to paths${isStop && shared > 0 ? ' (on every route)' : ''}
              </label>` : (!snaps ? '<span class="net-free-badge" title="Placed off the paths; select it to change">Free</span>' : '')}
            ${hasLeg ? `
              <button type="button" class="net-leg${point.straight ? ' is-straight' : ''}" data-straight="${i}"
                      title="The leg arriving here">${point.straight ? '╌ Drawn straight' : '↝ Follows paths'}</button>
              ${off ? '<span class="net-point-note is-warn">No path joins these; drawn straight.</span>' : ''}` : ''}
          </span>
          <span class="net-point-actions">
            <button type="button" class="btn-xs" data-kind="${i}">${isStop ? 'Make guide' : 'Make stop'}</button>
            <button type="button" class="btn-xs" data-up="${i}" aria-label="Move up" ${i === 0 ? 'disabled' : ''}>↑</button>
            <button type="button" class="btn-xs" data-down="${i}" aria-label="Move down" ${i === route.points.length - 1 ? 'disabled' : ''}>↓</button>
            <button type="button" class="btn-xs danger" data-remove="${i}" aria-label="Remove">✕</button>
          </span>
        </li>`;
    }).join('');

    const stopsOn = route.points.filter((p) => p.stop != null).length;
    const length = route.points.reduce((sum, p) => sum + (p.path ?? []).slice(1)
      .reduce((s, q, j) => s + metres(p.path[j], q), 0), 0);

    side.innerHTML = `
      <div class="net-route-head">
        <input type="color" class="net-colour" id="net-route-colour" value="${escHtml(route.colour)}" aria-label="Route colour">
        <input class="form-input net-route-name" id="net-route-name" value="${escHtml(route.name)}" aria-label="Route name">
      </div>
      <div class="net-route-opts">
        <label class="net-check"><input type="checkbox" id="net-route-loop" ${route.loop ? 'checked' : ''}> Loop back to the first point</label>
        <span class="net-item-meta">${stopsOn} stop${stopsOn === 1 ? '' : 's'} · ${(length / 1000).toFixed(2)} km</span>
      </div>
      <p class="net-hint">Click the map to add a ${addMode === 'stop' ? 'stop' : 'guide point'}, or a grey stop to add it. Click a leg to add a guide point in it. Click a point to select it and set whether it snaps to the paths. Double-click a point to remove it. Ctrl+Z undoes, Ctrl+R redoes.</p>
      <ol class="net-points" id="net-points">${rows || '<li class="net-empty">No points yet. Click the map.</li>'}</ol>
      <div class="net-side-foot">
        <button type="button" class="btn-xs" data-close-route>Close</button>
        <button type="button" class="btn-xs danger" data-delete-route>Delete route</button>
      </div>`;
  }

  // ---- Events ----

  function wire() {
    el('net-bar-toggle').addEventListener('click', () => openBar(el('net-bar-body').hidden));
    el('net-new-route').addEventListener('click', newRoute);

    document.querySelectorAll('[data-add-mode]').forEach((button) => {
      button.addEventListener('click', () => {
        addMode = button.dataset.addMode;
        document.querySelectorAll('[data-add-mode]').forEach((b) => {
          b.classList.toggle('is-on', b === button);
          b.setAttribute('aria-pressed', String(b === button));
        });
        renderSidebar();
      });
    });

    el('tab-routes').addEventListener('click', (e) => {
      const t = e.target;
      const on = (attr) => t.closest(`[${attr}]`);
      if (on('data-open-route')) {
        selected = on('data-open-route').dataset.openRoute;
        selectedPoint = null;
        renderAll();
        drawAll();
        const line = current().points.flatMap((p) => p.path ?? []);
        if (line.length > 1) map.fitBounds(L.latLngBounds(line), { padding: [30, 30] });
      } else if (on('data-new-route')) newRoute();
      else if (on('data-close-route')) { selected = null; selectedPoint = null; renderAll(); drawAll(); }
      else if (on('data-delete-route')) deleteRoute();
      else if (on('data-snap-stop')) toggleSnap(stopOf(on('data-snap-stop').dataset.snapStop));
      else if (on('data-find-stop')) focusStop(on('data-find-stop').dataset.findStop);
      else if (on('data-delete-stop')) deleteStop(on('data-delete-stop').dataset.deleteStop);
      else if (on('data-kind')) toggleKind(Number(on('data-kind').dataset.kind));
      else if (on('data-straight')) toggleStraight(Number(on('data-straight').dataset.straight));
      else if (on('data-remove')) removePoint(Number(on('data-remove').dataset.remove));
      else if (on('data-up')) movePoint(Number(on('data-up').dataset.up), Number(on('data-up').dataset.up) - 1);
      else if (on('data-down')) movePoint(Number(on('data-down').dataset.down), Number(on('data-down').dataset.down) + 1);
      else if (on('data-snap-point')) {
        const point = current().points.find((p) => p.uid === on('data-snap-point').dataset.snapPoint);
        if (point) toggleSnap(point);
      } else if (t.closest('.net-point') && !t.closest('button, input, label')) {
        selectPoint(t.closest('.net-point').dataset.uid);
      }
    });

    // Names update as typed; the list and map catch up when the field is left.
    // A burst of typing in one field is one step to undo, not one per key.
    let typingIn = null;
    el('tab-routes').addEventListener('focusin', (e) => { if (e.target !== typingIn) typingIn = null; });
    el('tab-routes').addEventListener('input', (e) => {
      const t = e.target;
      if ((t.dataset.stopName || t.id === 'net-route-name' || t.id === 'net-route-colour') && typingIn !== t) {
        record();
        typingIn = t;
      }
      if (t.dataset.stopName) {
        stopOf(t.dataset.stopName).name = t.value;
        setDirty();
      } else if (t.id === 'net-route-name') {
        current().name = t.value;
        setDirty();
      } else if (t.id === 'net-route-colour') {
        current().colour = t.value;
        setDirty();
        drawAll();
      }
    });
    el('tab-routes').addEventListener('change', (e) => {
      const t = e.target;
      if (t.id === 'net-route-loop') {
        record();
        current().loop = t.checked;
        changed([current()]);
      } else if (t.dataset.stopName || t.id === 'net-route-name') {
        renderAll();
        drawAll();
      }
    });

    // Drag a row to reorder the route.
    let dragFrom = null;
    el('net-sidebar').addEventListener('dragstart', (e) => {
      const row = e.target.closest('.net-point');
      if (!row) return;
      dragFrom = Number(row.dataset.index);
      e.dataTransfer.effectAllowed = 'move';
      row.classList.add('is-dragging');
    });
    el('net-sidebar').addEventListener('dragover', (e) => {
      if (dragFrom === null) return;
      e.preventDefault();
      document.querySelectorAll('.net-point.is-drop').forEach((r) => r.classList.remove('is-drop'));
      e.target.closest('.net-point')?.classList.add('is-drop');
    });
    el('net-sidebar').addEventListener('drop', (e) => {
      const row = e.target.closest('.net-point');
      if (dragFrom !== null && row) {
        e.preventDefault();
        movePoint(dragFrom, Number(row.dataset.index));
      }
      dragFrom = null;
    });
    el('net-sidebar').addEventListener('dragend', () => {
      dragFrom = null;
      renderSidebar();
    });

    el('net-save').addEventListener('click', save);
    el('net-discard').addEventListener('click', () => {
      fromServer(saved);
      clearHistory();
      setDirty(false);
      showError('');
      renderAll();
      drawAll();
    });

    el('net-undo').addEventListener('click', undo);
    el('net-redo').addEventListener('click', redo);

    // Ctrl+Z undo; Ctrl+R, Ctrl+Shift+Z or Ctrl+Y redo. Cmd works as Ctrl.
    // Only on this tab, and in a text field Ctrl+Z is left to undo typing.
    // Ctrl+R would otherwise reload the page; F5 still does.
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !el('tab-routes').hidden && selectedPoint) {
        selectedPoint = null;
        renderSidebar();
        drawAll();
        return;
      }
      if (el('tab-routes').hidden || !(e.ctrlKey || e.metaKey) || e.altKey) return;
      const key = e.key.toLowerCase();
      const typing = e.target.matches?.('input[type="text"], input:not([type]), textarea');
      if (key === 'z' && !e.shiftKey) {
        if (typing) return;
        e.preventDefault();
        undo();
      } else if (key === 'r' || key === 'y' || (key === 'z' && e.shiftKey)) {
        if (typing && key !== 'r') return;
        e.preventDefault();
        redo();
      }
    });

    window.addEventListener('beforeunload', (e) => {
      if (dirty) { e.preventDefault(); e.returnValue = ''; }
    });
  }

  // ---- Load and save ----

  async function load() {
    try {
      const [network, pathData] = await Promise.all([
        api('/api/network'),
        api('/api/network/paths').catch(() => null),
      ]);
      saved = network;
      paths = pathData;
      fromServer(network);
      clearHistory();
      setDirty(false);
      renderAll();
      drawPaths();
      drawAll();
      if (stops.size) {
        map.invalidateSize();
        map.fitBounds(L.latLngBounds([...stops.values()].map((s) => [s.latitude, s.longitude])), { padding: [40, 40] });
      }
    } catch (err) {
      showError(`Could not load the routes: ${err.message}`);
    }
  }

  async function save() {
    const button = el('net-save');
    button.disabled = true;
    showError('');
    el('net-status').textContent = 'Saving…';
    const body = {
      stops: [...stops.values()].map((stop) => ({
        id: stop.id, key: stop.id ? null : stop.ref, name: stop.name.trim(),
        latitude: stop.latitude, longitude: stop.longitude, snap: stop.snap !== false,
      })),
      routes: routes.map((route) => ({
        id: route.id, name: route.name.trim(), colour: route.colour.toUpperCase(), loop: route.loop,
        points: route.points.map((point) => (point.stop != null
          ? { stop: point.stop, straight: point.straight }
          : { latitude: point.latitude, longitude: point.longitude, snap: point.snap !== false, straight: point.straight })),
      })),
    };
    try {
      const data = await api('/api/network', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const open = current();
      saved = data;
      fromServer(data);
      // Keep the route open across the save, under its new id if it had none.
      if (open) selected = (routes.find((r) => r.ref === open.id) ?? routes.find((r) => r.name === open.name.trim()))?.ref ?? null;
      // What is saved is the new starting point: undo stops here.
      clearHistory();
      setDirty(false);
      flash('Saved. The dashboard shows the new routes on its next load.');
      renderAll();
      drawAll();
    } catch (err) {
      showError(err.message);
      el('net-status').textContent = 'Not saved.';
      button.disabled = false;
    }
  }

  // The map needs its tab visible to size itself, so it starts on first open.
  let started = false;
  document.querySelector('.app-tab[data-tab="routes"]').addEventListener('click', () => {
    if (!started) {
      started = true;
      initMap();
      wire();
      load();
    }
    setTimeout(() => map.invalidateSize(), 0);
  });
})();
