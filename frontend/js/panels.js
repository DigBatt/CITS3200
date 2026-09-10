// Dashboard chrome carried over from drafts/kynan/Nuway Prototype.dc.html.
//
// Purely visual: switches which panel/section is shown. None of this reads
// or writes real vehicle data yet -- see the `data-stub`/`data-endpoint`
// attributes in index.html for where live wiring will attach later.
//
// Deliberately independent of main.js/map.js/timeline.js/api.js so the
// existing date-range picker (and its data flow) is untouched.

document.addEventListener('DOMContentLoaded', () => {
  const tabs = document.querySelectorAll('#app-tabs .app-tab');
  const viewMap = document.getElementById('view-map');
  const viewUtilisation = document.getElementById('view-utilisation');
  const panels = {
    fleet: document.getElementById('panel-fleet'),
    operator: document.getElementById('panel-operator'),
    rider: document.getElementById('panel-rider'),
  };

  function setView(view) {
    tabs.forEach((tab) => tab.classList.toggle('is-active', tab.dataset.view === view));

    if (view === 'utilisation') {
      viewMap.hidden = true;
      viewUtilisation.hidden = false;
      return;
    }

    viewMap.hidden = false;
    viewUtilisation.hidden = true;
    Object.entries(panels).forEach(([name, panel]) => {
      panel.hidden = name !== view;
    });
  }

  tabs.forEach((tab) => tab.addEventListener('click', () => setView(tab.dataset.view)));

  // Vehicle filter chips: single-select, visual only for now.
  const vehicleChips = document.getElementById('vehicle-filter-chips');
  vehicleChips?.addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (!chip) return;
    vehicleChips.querySelectorAll('.chip').forEach((c) => c.classList.remove('is-active'));
    chip.classList.add('is-active');
  });

  // Rider stop chips: single-select, visual only for now.
  const stopChips = document.getElementById('stop-chips');
  stopChips?.addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (!chip) return;
    stopChips.querySelectorAll('.chip').forEach((c) => c.classList.remove('is-active'));
    chip.classList.add('is-active');
  });

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

  // Header clock: cosmetic only.
  const clock = document.getElementById('app-clock');
  if (clock) {
    const tick = () => {
      clock.textContent = new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    };
    tick();
    setInterval(tick, 1000);
  }
});
