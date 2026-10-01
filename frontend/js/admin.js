function redirectToSignIn() {
  const here = window.location.pathname + window.location.search;
  window.location.href = `/admin-login?${new URLSearchParams({ next: here })}`;
}

async function checkSignedIn() {
  try {
    const { signed_in: signedIn } = await fetch('/api/admin/me', { cache: 'no-store' }).then((r) => r.json());
    if (!signedIn) redirectToSignIn();
  } catch {
    // Server unreachable: the admin endpoints will fail on their own.
  }
}
checkSignedIn();
window.addEventListener('pageshow', (event) => {
  if (event.persisted) checkSignedIn();
});

document.getElementById('btn-signout').addEventListener('click', async () => {
  try {
    await fetch('/api/admin/logout', { method: 'POST' });
  } finally {
    window.location.href = '/';
  }
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

// ---- Downtime records stored by /api/downtime ----
let downtimeRecords = [];
let editingId = null;
// Set once the server has warned of an overlap; the next save confirms it.
let confirmOverlap = false;

const OVERLAP_WARNING_DEFAULT = document.getElementById('downtime-overlap-warning').textContent;

// Resolves to { ok, status, data }. A lapsed session goes back to sign-in.
async function downtimeRequest(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  });
  if (response.status === 401) {
    redirectToSignIn();
    throw new Error('Signed out');
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  return { ok: response.ok, status: response.status, data };
}

async function loadDowntime() {
  const tbody = document.getElementById('downtime-tbody');
  try {
    const { ok, status, data } = await downtimeRequest('GET', '/api/downtime');
    if (!ok) throw new Error(data?.error?.message ?? `Could not load downtime records (${status}).`);
    downtimeRecords = data.records;
    renderDowntime();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5"><p class="empty-state">${escHtml(err.message)}</p></td></tr>`;
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

// A UTC timestamp from the API as a datetime local input value.
function toLocalInput(iso) {
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// the server refused an overlapping period; show what it clashes with
// and let the next save store it anyway.
function showOverlap(overlaps) {
  const list = overlaps
    .map(r => `${fmtLocal(r.start)} – ${fmtLocal(r.end)} (${r.reason})`)
    .join('; ');
  document.getElementById('downtime-overlap-warning').textContent =
    `⚠ This period overlaps existing downtime for this vehicle: ${list}. Press "Save anyway" to store it, or change the times.`;
  document.getElementById('downtime-overlap-warning').classList.add('visible');
  document.getElementById('btn-downtime-save').textContent = 'Save anyway';
  confirmOverlap = true;
}

function resetOverlap() {
  confirmOverlap = false;
  const warning = document.getElementById('downtime-overlap-warning');
  warning.classList.remove('visible');
  warning.textContent = OVERLAP_WARNING_DEFAULT;
  document.getElementById('btn-downtime-save').textContent = 'Save record';
}

['dt-vehicle', 'dt-start', 'dt-end'].forEach(id =>
  document.getElementById(id).addEventListener('input', resetOverlap));

document.getElementById('btn-downtime-save').addEventListener('click', async () => {
  const vehicle = document.getElementById('dt-vehicle').value;
  const start   = document.getElementById('dt-start').value;
  const end     = document.getElementById('dt-end').value;
  const reason  = document.getElementById('dt-reason').value.trim();

  if (!vehicle || !start || !end || !reason) {
    alert('Please fill in all fields.');
    return;
  }

  // datetime local values are the browser's local time; send them as UTC.
  const startDate = new Date(start);
  const endDate   = new Date(end);

  // an end earlier than its start is rejected rather than stored.
  if (endDate <= startDate) {
    alert('End time must be after start time.');
    return;
  }

  const body = {
    vehicle_id: vehicle,
    start: startDate.toISOString(),
    end: endDate.toISOString(),
    reason,
  };
  if (confirmOverlap) body.confirm = true;

  let result;
  try {
    result = editingId
      ? await downtimeRequest('PATCH', `/api/downtime/${editingId}`, body)
      : await downtimeRequest('POST', '/api/downtime', body);
  } catch (err) {
    if (err.message !== 'Signed out') alert('Could not reach the server. The record was not saved.');
    return;
  }

  const { ok, status, data } = result;
  if (status === 409 && data?.overlaps) {
    showOverlap(data.overlaps);
    return;
  }
  if (!ok) {
    alert(data?.error?.message ?? `Could not save the record (${status}).`);
    return;
  }

  editingId = null;
  clearDowntimeForm();
  await loadDowntime();
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
  resetOverlap();
}

function startEdit(id) {
  const rec = downtimeRecords.find(r => r.id === id);
  if (!rec) return;
  editingId = id;
  resetOverlap();
  document.getElementById('dt-vehicle').value = rec.vehicle_id;
  document.getElementById('dt-start').value = toLocalInput(rec.start);
  document.getElementById('dt-end').value = toLocalInput(rec.end);
  document.getElementById('dt-reason').value = rec.reason;
  document.getElementById('downtime-form-title').textContent = 'EDIT DOWNTIME RECORD';
  document.getElementById('btn-downtime-cancel').hidden = false;
  document.getElementById('tab-downtime').scrollIntoView({ behavior: 'smooth' });
}

async function deleteRecord(id) {
  if (!confirm('Delete this downtime record?')) return;
  let result;
  try {
    result = await downtimeRequest('DELETE', `/api/downtime/${id}`);
  } catch (err) {
    if (err.message !== 'Signed out') alert('Could not reach the server. The record was not deleted.');
    return;
  }
  if (!result.ok) {
    alert(result.data?.error?.message ?? `Could not delete the record (${result.status}).`);
    return;
  }
  if (editingId === id) {
    editingId = null;
    clearDowntimeForm();
  }
  await loadDowntime();
}

loadDowntime();