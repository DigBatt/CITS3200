
(function () {
  let stops = [];

  async function init() {
    try {
      stops = (await getStops()).stops;
    } catch (error) {
      console.warn(`Stops unavailable: ${error.message}`);
      return;
    }
    drawStops(stops);
  }

  window.Stops = { init, all: () => stops };
})();
