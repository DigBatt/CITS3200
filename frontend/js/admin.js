// Admin page logic: auth guard, tab switching, and downtime records.
//
// Downtime is stored by the backend (S18). Every change goes to /api/downtime
// and the table is redrawn from the response, so nothing is held only here.
//
// The datetime-local inputs are wall clock with no zone; the API speaks UTC.
// toIso and toInput below are the only places that conversion happens.

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

// The API's error shape is { error: { code, message } }.
async function api(path, options) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}

// A local wall time from the form, as the UTC instant the API stores.
function toIso(value) {
  return new Date(value).toISOString();
}

// A stored UTC instant, as the local wall time the form shows.
function toInput(iso) {
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function loadDowntime() {
  const tbody = document.getElementById('downtime-tbody');
  try {
    downtimeRecords = (await api('/api/downtime')).records;
    renderDowntime();
  } catch (err) {
    tbody.innerHTML =
      `<tr><td colspan="5"><p class="empty-state">Could not load downtime records: ${escHtml(err.message)}</p></td></tr>`;
  }
}

function renderDowntime() {
  const tbody = document.getElementById('downtime-tbody');
  if (!downtimeRecords.length) {
    tbody.innerHTML =
      '<tr><td colspan="5"><p class="empty-state">No downtime records yet.</p></td></tr>';
    return;
  }
  tbody.innerHTML = downtimeRecords.map(r => `
    <tr data-id="${r.id}">
      <td class="mono">${escHtml(r.vehicle_id)}</td>
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
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

document.getElementById('btn-downtime-save').addEventListener('click', async () => {
  const vehicle = document.getElementById('dt-vehicle').value;
  const start   = document.getElementById('dt-start').value;
  const end     = document.getElementById('dt-end').value;
  const reason  = document.getElementById('dt-reason').value.trim();
  const warning = document.getElementById('downtime-overlap-warning');
  const button  = document.getElementById('btn-downtime-save');

  if (!vehicle || !start || !end || !reason) {
    alert('Please fill in all fields.');
    return;
  }

  // S18: an end earlier than its start is rejected rather than stored. The
  // server enforces this too; checking here saves a round trip.
  if (new Date(end) <= new Date(start)) {
    alert('End time must be after start time.');
    return;
  }

  const body = JSON.stringify({ vehicle_id: vehicle, start: toIso(start), end: toIso(end), reason });
  const request = {
    method: editingId ? 'PATCH' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  };

  button.disabled = true;
  try {
    const path = editingId ? `/api/downtime/${editingId}` : '/api/downtime';
    const saved = await api(path, request);

    // S18: an overlapping period warns, but the record is already stored.
    warning.classList.toggle('visible', saved.overlaps.length > 0);

    editingId = null;
    clearDowntimeForm(saved.overlaps.length > 0);
    await loadDowntime();
  } catch (err) {
    alert(`Could not save the record: ${err.message}`);
  } finally {
    button.disabled = false;
  }
});

document.getElementById('btn-downtime-cancel').addEventListener('click', () => {
  editingId = null;
  clearDowntimeForm();
});

function clearDowntimeForm(keepWarning = false) {
  document.getElementById('dt-start').value = '';
  document.getElementById('dt-end').value = '';
  document.getElementById('dt-reason').value = '';
  document.getElementById('downtime-form-title').textContent = 'ADD DOWNTIME RECORD';
  document.getElementById('btn-downtime-cancel').hidden = true;
  if (!keepWarning) {
    document.getElementById('downtime-overlap-warning').classList.remove('visible');
  }
}

function startEdit(id) {
  const rec = downtimeRecords.find(r => r.id === id);
  if (!rec) return;
  editingId = id;
  document.getElementById('dt-vehicle').value = rec.vehicle_id;
  document.getElementById('dt-start').value = toInput(rec.start);
  document.getElementById('dt-end').value = toInput(rec.end);
  document.getElementById('dt-reason').value = rec.reason;
  document.getElementById('downtime-form-title').textContent = 'EDIT DOWNTIME RECORD';
  document.getElementById('btn-downtime-cancel').hidden = false;
  document.getElementById('tab-downtime').scrollIntoView({ behavior: 'smooth' });
}

async function deleteRecord(id) {
  if (!confirm('Delete this downtime record?')) return;
  try {
    await api(`/api/downtime/${id}`, { method: 'DELETE' });
    if (editingId === id) {
      editingId = null;
      clearDowntimeForm();
    }
    await loadDowntime();
  } catch (err) {
    alert(`Could not delete the record: ${err.message}`);
  }
}

loadDowntime();
