// Vehicle chips: "All vehicles" plus one chip per vehicle, any number of
// which can be on at once. Shared by the dashboard's vehicle filter
// (js/vehicles.js) and the admin Figures tab (js/figures.js), so the two pick
// vehicles the same way.
//
// No chip on means the whole fleet, which is what "All vehicles" shows and
// returns to. Turning on every vehicle one by one also lands there, and
// turning off the last one goes back to it, so there is never an empty
// selection that matches nothing.

(function () {
  /**
   * @param {HTMLElement} container - Where the chips are drawn.
   * @param {Object} [options]
   * @param {(ids: string[]) => void} [options.onChange] - The new selection,
   *   [] for the whole fleet, after each change made by a click.
   */
  function create(container, { onChange } = {}) {
    let fleet = []; // [{ id, name }]
    let selected = new Set(); // empty means the whole fleet

    const nameOf = (id) => fleet.find((vehicle) => vehicle.id === id)?.name ?? `Vehicle ${id}`;

    function normalise() {
      // Every vehicle on is the whole fleet; say so with "All vehicles".
      if (fleet.length && fleet.every((vehicle) => selected.has(vehicle.id))) selected.clear();
    }

    function render() {
      const chip = (id, label, on) =>
        `<button type="button" class="chip${on ? ' is-active' : ''}" data-vehicle="${escapeHtml(id)}" aria-pressed="${on}">${escapeHtml(label)}</button>`;
      container.innerHTML = [
        chip('all', 'All vehicles', selected.size === 0),
        ...fleet.map((vehicle) => chip(vehicle.id, nameOf(vehicle.id), selected.has(vehicle.id))),
      ].join('');
    }

    function change(next) {
      selected = new Set(next);
      normalise();
      render();
      onChange?.([...selected]);
    }

    container.addEventListener('click', (event) => {
      const chip = event.target.closest('[data-vehicle]');
      if (!chip) return;
      const id = chip.dataset.vehicle;
      if (id === 'all') {
        change([]);
        return;
      }
      const next = new Set(selected);
      next.has(id) ? next.delete(id) : next.add(id);
      change(next);
    });

    render();

    return {
      /** The fleet to offer, from /api/vehicles; ids no longer in it drop out. */
      setFleet(vehicles) {
        fleet = vehicles.map(({ id, name }) => ({ id, name }));
        const known = new Set(fleet.map((vehicle) => vehicle.id));
        selected = new Set([...selected].filter((id) => known.has(id)));
        normalise();
        render();
      },
      /** The selected ids, [] for the whole fleet. */
      get: () => [...selected],
      /** As the API's `vehicles` parameter: "1,2", or null for the whole fleet.
          In fleet order, so picking 2 then 1 asks for the same as 1 then 2. */
      query: () =>
        selected.size
          ? fleet.filter((vehicle) => selected.has(vehicle.id)).map((vehicle) => vehicle.id).join(',')
          : null,
      has: (id) => selected.size === 0 || selected.has(id),
      /** Replace the selection without announcing it, e.g. from a link. */
      set(ids) {
        selected = new Set(ids);
        normalise();
        render();
      },
      /** Turn one vehicle on or off, announcing it as a click would. */
      toggle(id) {
        const next = new Set(selected);
        next.has(id) ? next.delete(id) : next.add(id);
        change(next);
      },
      /** Select just this vehicle, announcing it. */
      only(id) {
        change([id]);
      },
      /** Select these vehicles ([] for the whole fleet), announcing it. */
      choose(ids) {
        change(ids);
      },
      nameOf,
    };
  }

  window.VehicleChips = { create };
})();
