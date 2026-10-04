document.addEventListener('DOMContentLoaded', () => {
  const tabs = document.querySelectorAll('#app-tabs .app-tab');
  const viewMap = document.getElementById('view-map');
  const viewUtilisation = document.getElementById('view-utilisation');
  const panels = {
    fleet: document.getElementById('panel-fleet'),
    rider: document.getElementById('panel-rider'),
  };

  // S11: the vehicle/route/area chips and the date-range picker are tools an
  // ordinary rider has no use for (S11.2) -- most people who open the site
  // land on this view, and S11.1/S11.3 are about it fitting one screen on a
  // phone without scrolling past them first. The route and area chips also
  // serve no purpose on Utilisation (which has no map to pin, and scopes its
  // report by vehicle, not route). Hidden rather than removed either way,
  // since e.g. Utilisation still needs the vehicle chips.
  //
  // `riderOverrides` is null when nothing has been overridden; while it
  // holds a value, the Rider tab's "today, live, every vehicle, campus only"
  // forcing is in effect and that value is what gets put back on leaving.
  let riderOverrides = null;

  function updateChromeVisibility(view) {
    const hideVehicle = view === 'rider';
    const hideRoute = view === 'rider' || view === 'utilisation';
    const hideArea = view === 'rider' || view === 'utilisation';
    const hideTimeline = view === 'rider';
    document.getElementById('vehicle-filter')?.classList.toggle('is-chrome-hidden', hideVehicle);
    document.getElementById('route-filter')?.classList.toggle('is-chrome-hidden', hideRoute);
    document.getElementById('area-filter')?.classList.toggle('is-chrome-hidden', hideArea);
    // The date-range picker is the header calendar, with the period control
    // inside its overlay, so the whole of it is hidden, bar and all.
    document.querySelector('.app-header .period-picker')?.classList.toggle('is-chrome-hidden', hideTimeline);
  }

  function enterRiderDefaults() {
    if (riderOverrides) return; // already applied -- e.g. clicking Rider again
    riderOverrides = {
      timeline: timelineControl?.getFieldState(),
      vehicle: Vehicles.getSelection(),
      area: window.Area?.getSelection(),
    };
    timelineControl?.setLiveToday();
    Vehicles.select(null); // every vehicle, not whichever ones Fleet had picked
    window.Area?.select(null); // the Area chips are hidden anyway; this is what the next line pins instead
    pinMapTo(getCampusBounds); // campus only, regardless of whatever area was pinned
  }

  function leaveRiderDefaults() {
    if (!riderOverrides) return;
    if (riderOverrides.timeline) timelineControl?.setFieldState(riderOverrides.timeline);
    Vehicles.select(riderOverrides.vehicle);
    // restore(), not select(): the Rider tab's forced campus pin (above)
    // changed the map's actual pin without going through Area at all, so
    // its own "id hasn't changed" guard in select() would otherwise wrongly
    // skip putting the real pin back when the saved selection is the same
    // null/area it already thinks is active.
    window.Area?.restore(riderOverrides.area);
    riderOverrides = null;
  }

  function setView(view) {
    tabs.forEach((tab) => tab.classList.toggle('is-active', tab.dataset.view === view));

    // Ahead of the Utilisation branch's early return below, since leaving
    // Rider for Utilisation must still restore the chips it depends on.
    if (view === 'rider') {
      enterRiderDefaults();
    } else {
      leaveRiderDefaults();
    }
    updateChromeVisibility(view);

    if (view === 'utilisation') {
      viewMap.hidden = true;
      viewUtilisation.hidden = false;
      return;
    }

    viewMap.hidden = false;
    viewUtilisation.hidden = true;
    showMap();
    Object.entries(panels).forEach(([name, panel]) => {
      panel.hidden = name !== view;
    });

    // The rider's stop picker hides every other stop to cut clutter (S15),
    // js/map.js:isolateStop(). That is Rider-only, so leaving the tab
    // restores every stop for Fleet; returning to it re-applies
    // whatever the picker still has chosen or waiting.
    if (view === 'rider') {
      window.Rider?.syncMapIsolation();
    } else {
      isolateStop(null);
    }
  }

  tabs.forEach((tab) => tab.addEventListener('click', () => setView(tab.dataset.view)));

  // Utilisation view: Pie / Time model toggle.
  const utilTabs = document.querySelectorAll('#util-tabs .util-tab');
  const utilPieCard = document.getElementById('util-pie-card');
  const utilTumCard = document.getElementById('util-tum-card');
  utilTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      utilTabs.forEach((t) => t.classList.toggle('is-active', t === tab));
      const isTum = tab.dataset.utilMode === 'tum';
      utilPieCard.hidden = isTum;
      utilTumCard.hidden = !isTum;
    });
  });

  // The calendar's month bar and its overlay are placed by js/calendar.js.

  // Collapsible vehicle/route filter bars: click the "VEHICLE" or "ROUTE"
  // label to fold away its chip row, for a less cluttered or larger map on
  // a smaller screen. Remembered per browser, the same way Stops remembers
  // the selected route (js/stops.js), so it stays folded across reloads.
  function initCollapsibleFilterBar(barId, storageKey) {
    const bar = document.getElementById(barId);
    const label = bar?.querySelector('.filter-bar-label');
    if (!bar || !label) return;

    function apply(collapsed) {
      bar.classList.toggle('is-collapsed', collapsed);
      label.setAttribute('aria-expanded', String(!collapsed));
    }

    function remember(collapsed) {
      try {
        if (collapsed) localStorage.setItem(storageKey, '1');
        else localStorage.removeItem(storageKey);
      } catch (error) {
        /* storage unavailable */
      }
    }

    function recall() {
      try {
        return localStorage.getItem(storageKey) === '1';
      } catch (error) {
        return false;
      }
    }

    label.addEventListener('click', () => {
      const collapsed = !bar.classList.contains('is-collapsed');
      apply(collapsed);
      remember(collapsed);
    });

    apply(recall());
  }

  initCollapsibleFilterBar('vehicle-filter', 'nuway.vehicleFilterCollapsed');
  initCollapsibleFilterBar('route-filter', 'nuway.routeFilterCollapsed');
  initCollapsibleFilterBar('area-filter', 'nuway.areaFilterCollapsed');

});
