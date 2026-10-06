// The map pane's 3D view: a 2D / 3D toggle, and in 3D, one bus at a time on a
// 3D campus with the camera circling it (js/campus3d.js). The ‹ › arrows, or
// the arrow keys, step through the buses in the current selection.
//
// It shows the same position as the 2D map's end marker: each bus's last fix
// in the selected period. Live, that is where the bus is now, and each poll
// moves it on; moving the period moves the bus through campus. main.js hands
// over every load's positions through View3D.update.
//
// Two views of the same bus, switched with the Earth toggle:
//   campus  3D blocks from OpenFreeMap (js/campus3d.js), no key needed;
//   earth   Google's photorealistic 3D tiles (js/earth3d.js), which need a
//           Google Maps API key and are off without one (/api/earth).
// Both follow the same bus and the same Spin setting. Each view's modules
// are only fetched the first time it is needed.
//
// The campus view is warmed up in the background shortly after the page
// loads: built out of sight, paused, until its tiles and fonts are in, then
// put away. Switching to 3D then only reveals it. A first load otherwise
// waits on a chain of round trips to the tile server (style, tile index,
// tiles, fonts), several seconds from Perth. Skipped where it would cost the
// viewer: Save-Data, a 2G connection, a phone-sized screen, or the Rider tab.
// Earth is never warmed up, since each load is billed to the key's account.

(function () {
  // How much of a bus's track to draw behind it.
  const TRAIL_MS = 10 * 60 * 1000;
  // Where this browser remembers whether the camera spins. A convenience
  // only: without it, the default applies.
  const SPIN_KEY = 'dashboard.view3d.spin';

  const els = {
    pane: document.querySelector('.map-pane'),
    toggle: document.getElementById('map-3d-toggle'),
    toggleLabel: document.querySelector('.map-mode'),
    view: document.getElementById('campus3d'),
    hosts: { campus: document.getElementById('campus3d-map'), earth: document.getElementById('earth3d-map') },
    status: document.getElementById('campus3d-status'),
    dot: document.getElementById('campus3d-dot'),
    name: document.getElementById('campus3d-name'),
    meta: document.getElementById('campus3d-meta'),
    steps: document.querySelectorAll('[data-campus3d-step]'),
    spin: document.getElementById('campus3d-spin'),
    earth: document.getElementById('campus3d-earth'),
    earthLabel: document.getElementById('campus3d-earth-label'),
  };

  const MODULES = { campus: 'js/campus3d.js', earth: 'js/earth3d.js' };

  let buses = []; // one entry per vehicle in the latest load, in its order
  let currentId = null;
  // Per view: its mount promise, the mounted view once it is up, and the
  // last status message it gave, shown only while it is the active one.
  const views = {
    campus: { loading: null, api: null, status: '' },
    earth: { loading: null, api: null, status: '' },
  };
  let active = 'campus';
  let earthKey = null; // from /api/earth, once asked
  let earthAsked = null;

  // Degrees clockwise from north, from one fix to the next: the fallback
  // for a fix that carries no heading of its own.
  function bearing(a, b) {
    const rad = Math.PI / 180;
    const y = Math.sin((b.longitude - a.longitude) * rad) * Math.cos(b.latitude * rad);
    const x = Math.cos(a.latitude * rad) * Math.sin(b.latitude * rad)
      - Math.sin(a.latitude * rad) * Math.cos(b.latitude * rad) * Math.cos((b.longitude - a.longitude) * rad);
    return (Math.atan2(y, x) / rad + 360) % 360;
  }

  // One vehicle from /api/positions as the 3D view wants it: its last fix,
  // heading and recent trail, or no position at all.
  function toBus(vehicle, gapSeconds) {
    const fixes = vehicle.positions.filter((p) => p.latitude != null && p.longitude != null);
    const bus = { id: vehicle.vehicle_id, name: vehicle.name, colour: vehicle.colour, fix: null };
    if (!fixes.length) return bus;

    const last = fixes[fixes.length - 1];
    const heading = last.heading_deg ?? (fixes.length > 1 ? bearing(fixes[fixes.length - 2], last) : 0);
    const since = Date.parse(last.timestamp) - TRAIL_MS;
    bus.fix = {
      id: bus.id,
      colour: bus.colour,
      lng: last.longitude,
      lat: last.latitude,
      heading,
      // GPS height above the ellipsoid; the Earth view starts the ground there.
      altitude: last.altitude_m,
      timestamp: last.timestamp,
      speed: last.speed_mps,
      // Only since the bus last went quiet: the trail is one line, and it
      // was not on a straight one across the silence (splitAtGaps, js/map.js).
      trail: splitAtGaps(fixes.filter((p) => Date.parse(p.timestamp) >= since), gapSeconds)
        .pop()
        .map((p) => [p.longitude, p.latitude]),
    };
    return bus;
  }

  const current = () => buses.find((bus) => bus.id === currentId) ?? null;

  function describe(bus) {
    if (!bus.fix) return 'No position in the selected period';
    const speed = bus.fix.speed != null ? ` · ${(bus.fix.speed * 3.6).toFixed(1)} km/h` : '';
    return `At ${formatInstant(bus.fix.timestamp)}${speed}`;
  }

  function render() {
    const bus = current();
    const several = buses.length > 1;
    els.steps.forEach((button) => { button.disabled = !several; });
    if (!bus) {
      els.name.textContent = 'No buses selected';
      els.meta.textContent = '';
      els.dot.style.background = 'transparent';
    } else {
      els.name.textContent = bus.name ?? `Vehicle ${bus.id}`;
      els.meta.textContent = describe(bus);
      els.dot.style.background = bus.colour ?? 'transparent';
    }
    // Both views, so switching between them lands on the same bus.
    for (const view of Object.values(views)) view.api?.show(bus?.fix ?? null);
  }

  function showStatus() {
    const message = views[active].status;
    els.status.textContent = message;
    els.status.hidden = !message;
  }

  function stepBy(delta) {
    if (buses.length < 2) return;
    const index = Math.max(0, buses.findIndex((bus) => bus.id === currentId));
    currentId = buses[(index + delta + buses.length) % buses.length].id;
    render();
  }

  // ---- Loading the views ----

  // True while the campus view is being built out of sight (warmUp below).
  let warming = false;

  function load(name) {
    const view = views[name];
    if (view.loading) return view.loading;
    const onStatus = (message) => {
      view.status = message;
      if (active === name) showStatus();
    };
    const options = {
      onStatus,
      spin: els.spin.checked,
      // Built while warming up: stay still until shown.
      paused: warming,
      ...(name === 'earth' ? { apiKey: earthKey } : {}),
    };
    view.loading = import(new URL(MODULES[name], document.baseURI).href)
      .then((module) => module.mount(els.hosts[name], options))
      .then((mounted) => {
        view.api = mounted;
        if (!warming) mounted.setPaused?.(false);
        render();
      })
      .catch((error) => {
        console.error(error);
        if (!view.status) onStatus('Could not load this view.');
        view.loading = null; // Let the next try load it again.
      });
    return view.loading;
  }

  // Whether Earth can run here: it needs a key the server may not have.
  function askAboutEarth() {
    earthAsked ??= request('/api/earth')
      .then((answer) => {
        earthKey = answer.available ? answer.api_key : null;
        els.earth.disabled = !earthKey;
        els.earthLabel.classList.toggle('is-unavailable', !earthKey);
        els.earthLabel.title = earthKey
          ? "Real-life buildings, from Google's photorealistic 3D tiles"
          : answer.reason;
      })
      .catch(() => {
        els.earthLabel.title = 'Could not check whether the Earth view is set up.';
        earthAsked = null;
      });
    return earthAsked;
  }

  function setView(name) {
    active = name;
    for (const [key, host] of Object.entries(els.hosts)) host.hidden = key !== name;
    els.earth.checked = name === 'earth';
    showStatus();
    load(name);
    views[name].api?.resize();
  }

  // ---- 2D / 3D ----

  function setMode(is3d) {
    els.toggle.checked = is3d;
    els.toggleLabel.classList.toggle('is-on', is3d);
    // Shown for real now, even if it was still warming up out of sight.
    if (is3d && warming) {
      warming = false;
      els.view.classList.remove('is-warming');
    }
    els.view.hidden = !is3d;
    if (is3d) views.campus.api?.setPaused(false);
    els.pane.classList.toggle('is-3d', is3d);
    if (is3d) {
      askAboutEarth();
      setView(active);
    } else {
      // Leaflet measured nothing while covered; let it catch up.
      showMap();
    }
  }

  els.toggle.addEventListener('change', () => setMode(els.toggle.checked));

  // ---- Warming up ----

  const WARM_UP_AFTER_MS = 2500;

  function worthWarmingUp() {
    const connection = navigator.connection;
    if (connection?.saveData) return false;
    if (/2g$/.test(connection?.effectiveType ?? '')) return false;
    if (window.matchMedia('(max-width: 760px)').matches) return false;
    if (document.querySelector('#app-tabs .app-tab.is-active')?.dataset.view === 'rider') return false;
    return true;
  }

  // Build the campus view out of sight: present and sized, so the map loads
  // what is around the bus, but invisible and paused. Once it has drawn
  // everything, put it away; showing it later needs nothing more fetched.
  function warmUp() {
    if (views.campus.loading || !els.view.hidden || !worthWarmingUp()) return;
    warming = true;
    els.view.classList.add('is-warming');
    els.view.hidden = false;
    load('campus')
      .then(() => views.campus.api?.whenReady())
      .finally(() => {
        if (!warming) return; // switched to 3D meanwhile; it is on show
        warming = false;
        els.view.classList.remove('is-warming');
        els.view.hidden = true;
      });
  }

  window.addEventListener('load', () => {
    setTimeout(() => {
      const idle = window.requestIdleCallback ?? ((callback) => setTimeout(callback, 0));
      idle(warmUp, { timeout: 4000 });
    }, WARM_UP_AFTER_MS);
  });

  // ---- Spin ----

  // Spinning by default, unless this browser was told otherwise before, or
  // its owner prefers reduced motion. Switching it on is still their call.
  function readSpin() {
    try {
      const stored = localStorage.getItem(SPIN_KEY);
      if (stored !== null) return stored === 'on';
    } catch {
      // Storage blocked: fall through to the default.
    }
    return !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  els.spin.checked = readSpin();
  els.spin.addEventListener('change', () => {
    for (const view of Object.values(views)) view.api?.setSpin(els.spin.checked);
    try {
      localStorage.setItem(SPIN_KEY, els.spin.checked ? 'on' : 'off');
    } catch {
      // Not remembered, which is fine.
    }
  });

  // ---- Earth ----

  // Not remembered between visits: each Earth view loads Google's tiles, on
  // the key's account, so it is something to turn on deliberately.
  els.earth.addEventListener('change', () => setView(els.earth.checked ? 'earth' : 'campus'));

  els.steps.forEach((button) => button.addEventListener('click', () => stepBy(Number(button.dataset.campus3dStep))));
  els.view.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      stepBy(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });

  window.View3D = {
    /**
     * Take the vehicles from a positions load. The bus on screen stays on
     * screen if it is still selected; otherwise the first one with a
     * position is shown.
     *
     * @param {Array} vehicles - `vehicles` from /api/positions.
     * @param {?number} gapSeconds - a silence longer than this ends a trail.
     */
    update(vehicles, gapSeconds = null) {
      buses = vehicles.map((vehicle) => toBus(vehicle, gapSeconds));
      if (!buses.some((bus) => bus.id === currentId)) {
        currentId = (buses.find((bus) => bus.fix) ?? buses[0])?.id ?? null;
      }
      render();
    },
  };
})();
