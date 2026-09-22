document.addEventListener('DOMContentLoaded', () => {
  const tabs = document.querySelectorAll('#app-tabs .app-tab');
  const viewMap = document.getElementById('view-map');
  const viewUtilisation = document.getElementById('view-utilisation');
  const viewSchedule = document.getElementById('view-schedule');
  // Built on first open, so a visitor who never opens the tab never fetches it.
  let calendar = null;
  const panels = {
    fleet: document.getElementById('panel-fleet'),
    operator: document.getElementById('panel-operator'),
    rider: document.getElementById('panel-rider'),
  };

  function setView(view) {
    tabs.forEach((tab) => tab.classList.toggle('is-active', tab.dataset.view === view));

    if (view === 'utilisation' || view === 'schedule') {
      viewMap.hidden = true;
      viewUtilisation.hidden = view !== 'utilisation';
      viewSchedule.hidden = view !== 'schedule';

      // create() fetches on its own, so only an already built calendar is
      // refreshed; reopening the tab picks up a roster edited since.
      if (view === 'schedule') {
        if (calendar) calendar.refresh();
        // The dashboard always shows the week; only the admin page switches.
        else calendar = ServiceCalendar.create(document.getElementById('dashboard-calendar'), { fixedDays: 7 });
      }
      return;
    }

    viewMap.hidden = false;
    viewUtilisation.hidden = true;
    viewSchedule.hidden = true;
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
