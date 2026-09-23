
(function () {
  let stops = [];

  async function init() {
    wireToggle();
    try {
      stops = (await getStops()).stops;
    } catch (error) {
      console.warn(`Stops unavailable: ${error.message}`);
      return;
    }
    drawStops(stops);
  }

  function wireToggle() {
    const toggle = document.getElementById('layer-toggle-stops');
    if (!toggle) return;
    setStopsVisible(toggle.checked);
    toggle.addEventListener('change', () => setStopsVisible(toggle.checked));
  }

  window.Stops = { init, all: () => stops };
})();
