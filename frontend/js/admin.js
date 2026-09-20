// Admin page logic: auth guard, tab switching, and downtime records.
//
// Downtime is held in memory until the /api/downtime endpoints exist (S18).
// Each TODO below marks where the fetch call replaces the local array.

// ---- Auth guard ----
// Redirect to the sign-in page if there is no admin session.
// Disabled until S13 (auth backend) provides /api/admin/me.
// function checkAuth() {
//   const loggedIn = sessionStorage.getItem('admin_session');
//   if (!loggedIn) {
//     window.location.href = '/admin-login';
//   }
// }
// checkAuth();

document.getElementById('btn-signout').addEventListener('click', () => {
  // STUB: call POST /api/admin/logout once S13 exists.
  sessionStorage.removeItem('admin_session');
  window.location.href = '/';
});

// ---- Tab switching ----
const tabs = document.querySelectorAll('.app-tab[data-tab]');
const panels = document.querySelectorAll('.admin-panel[id^="tab-"]');

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('is-active'));
    panels.forEach(p => p.hidden = true);
    tab.classList.add('is-active');
    document.getElementById('tab-' + tab.dataset.tab).hidden = false;
  });
});

// ---- Vehicle list for the downtime form ----
async function loadVehicles() {
  try {
    const data = await fetch('/api/vehicles').then(r => r.json());
    const sel = document.getElementById('dt-vehicle');
    sel.innerHTML = '';
    (data.vehicles ?? []).forEach(v => {
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = v.name ? `${v.name} (${v.id})` : v.id;
      sel.appendChild(opt);
    });
    if (!sel.options.length) {
      sel.innerHTML = '<option value="">No vehicles configured</option>';
    }
  } catch {
    document.getElementById('dt-vehicle').innerHTML =
      '<option value="">Could not load vehicles</option>';
  }
}
loadVehicles();

// ---- Downtime records ----
let downtimeRecords = [];
let editingId = null;

function renderDowntime() {
  const tbody = document.getElementById('downtime-tbody');
  if (!downtimeRecords.length) {
    tbody.innerHTML =
      '<tr><td colspan="5"><p class="empty-state">No downtime records yet.</p></td></tr>';
    return;
  }
  tbody.innerHTML = downtimeRecords.map(r => `
    <tr data-id="${r.id}">
      <td class="mono">${r.vehicle}</td>
      <td class="mono">${fmtLocal(r.start)}</td>
      <td class="mono">${fmtLocal(r.end)}</td>
      <td>${escHtml(r.reason)}</td>
      <td>
        <div class="row-actions">
          <button class="btn-xs" onclick="startEdit('${r.id}')">Edit</button>
          <button class="btn-xs danger" onclick="deleteRecord('${r.id}')">Delete</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function fmtLocal(iso) {
  const d = new Date(iso);
  return d.toLocaleString('en-AU', { dateStyle: 'short', timeStyle: 'short' });
}

function escHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function genId() {
  return Math.random().toString(36).slice(2, 10);
}

// S18: two periods overlap when each starts before the other ends.
function hasOverlap(vehicleId, start, end, excludeId = null) {
  return downtimeRecords.some(r => {
    if (r.id === excludeId || r.vehicle !== vehicleId) return false;
    return start < new Date(r.end) && end > new Date(r.start);
  });
}

document.getElementById('btn-downtime-save').addEventListener('click', () => {
  const vehicle = document.getElementById('dt-vehicle').value;
  const start   = document.getElementById('dt-start').value;
  const end     = document.getElementById('dt-end').value;
  const reason  = document.getElementById('dt-reason').value.trim();
  const warning = document.getElementById('downtime-overlap-warning');

  if (!vehicle || !start || !end || !reason) {
    alert('Please fill in all fields.');
    return;
  }

  const startDate = new Date(start);
  const endDate   = new Date(end);

  // S18: an end earlier than its start is rejected rather than stored.
  if (endDate <= startDate) {
    alert('End time must be after start time.');
    return;
  }

  // S18: an overlapping period warns before it is stored.
  if (hasOverlap(vehicle, startDate, endDate, editingId)) {
    warning.classList.add('visible');
  } else {
    warning.classList.remove('visible');
  }

  if (editingId) {
    const rec = downtimeRecords.find(r => r.id === editingId);
    if (rec) {
      rec.vehicle = vehicle;
      rec.start = start;
      rec.end = end;
      rec.reason = reason;
    }
    editingId = null;
  } else {
    downtimeRecords.push({ id: genId(), vehicle, start, end, reason });
  }

  clearDowntimeForm();
  renderDowntime();

  // TODO: POST /api/downtime (new) or PATCH /api/downtime/:id (edit) once S18 lands.
});

document.getElementById('btn-downtime-cancel').addEventListener('click', () => {
  editingId = null;
  clearDowntimeForm();
});

function clearDowntimeForm() {
  document.getElementById('dt-start').value = '';
  document.getElementById('dt-end').value = '';
  document.getElementById('dt-reason').value = '';
  document.getElementById('downtime-form-title').textContent = 'ADD DOWNTIME RECORD';
  document.getElementById('btn-downtime-cancel').hidden = true;
  document.getElementById('downtime-overlap-warning').classList.remove('visible');
}

function startEdit(id) {
  const rec = downtimeRecords.find(r => r.id === id);
  if (!rec) return;
  editingId = id;
  document.getElementById('dt-vehicle').value = rec.vehicle;
  document.getElementById('dt-start').value = rec.start;
  document.getElementById('dt-end').value = rec.end;
  document.getElementById('dt-reason').value = rec.reason;
  document.getElementById('downtime-form-title').textContent = 'EDIT DOWNTIME RECORD';
  document.getElementById('btn-downtime-cancel').hidden = false;
  document.getElementById('tab-downtime').scrollIntoView({ behavior: 'smooth' });
}

function deleteRecord(id) {
  if (!confirm('Delete this downtime record?')) return;
  downtimeRecords = downtimeRecords.filter(r => r.id !== id);
  renderDowntime();

  // TODO: DELETE /api/downtime/:id once S18 lands.
}

renderDowntime();