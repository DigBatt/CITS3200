function createVehicleControl(container, { onChange } = {}) {
  const selected = new Set();

  async function render() {
    try {
      const data = await getVehicles();

      container.innerHTML = '';

      // All vehicles
      const allButton = document.createElement('button');
      allButton.type = 'button';
      allButton.className = 'chip is-active';
      allButton.dataset.vehicle = 'all';
      allButton.textContent = 'All vehicles';
      container.appendChild(allButton);

      // Real vehicles from /api/vehicles
      for (const vehicle of data.vehicles) {
        const button = document.createElement('button');

        button.type = 'button';
        button.className = 'chip';
        button.dataset.vehicle = vehicle.id;
        button.textContent = vehicle.name;

        if (vehicle.status === 'inactive') {
          button.classList.add('is-inactive');
          button.title = 'Inactive';
        }

        button.addEventListener('click', () => {
          if (selected.has(vehicle.id)) {
            selected.delete(vehicle.id);
            button.classList.remove('is-active');
          } else {
            selected.add(vehicle.id);
            button.classList.add('is-active');
          }

          // Nothing selected = whole fleet
          if (selected.size === 0) {
            allButton.classList.add('is-active');
            onChange?.(null);
          } else {
            allButton.classList.remove('is-active');
            onChange?.([...selected].join(','));
          }
        });

        container.appendChild(button);
      }

      // Clicking All resets filter
      allButton.addEventListener('click', () => {
        selected.clear();

        container.querySelectorAll('.chip').forEach(button => {
          button.classList.remove('is-active');
        });

        allButton.classList.add('is-active');
        onChange?.(null);
      });

    } catch (error) {
      console.error('Failed to load vehicles:', error);
    }
  }

  render();
}
