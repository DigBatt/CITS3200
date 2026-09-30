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
    showMap();
    Object.entries(panels).forEach(([name, panel]) => {
      panel.hidden = name !== view;
    });
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

  // The docked mini month and the timeline under it are mounted by main.js,
  // which owns the range they pick.

  // The header wraps at narrow widths, so its height is measured rather than
  // assumed; the dock hangs just below whatever it ends up being.
  const dock = document.getElementById('mini-cal-dock');
  const header = document.querySelector('.app-header');
  const placeDock = () => {
    dock.style.top = `${header.getBoundingClientRect().bottom + 10}px`;
  };
  placeDock();
  window.addEventListener('resize', placeDock);

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
