// Admin page logic: auth guard, tab switching, downtime records and the
// service schedule.
//
// Downtime is stored by the backend (S18, backend/downtime.py). Every change
// goes to /api/downtime and the table is redrawn from the response, so
// nothing is held only here. An overlapping period is refused with a 409
// until the operator presses "Save anyway", which resends it with confirm.
//
// The datetime-local inputs are wall clock with no zone; the API speaks UTC.

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

// ---- Requests for the service schedule ----
//
// Resolves to the parsed body, or throws with the API's error message.

async function api(path, options) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  }
  return body;
}

// ---- Service schedule (S21) ----
//
// The roster lives in config/app.yaml, so saving here rewrites that block and
// the utilisation figures move with it. The whole week is sent at once: it is
// one config file, so one validated write beats a half applied edit.
//
// A period names the vehicles it is for, or none to mean the whole fleet. Two
// periods may overlap when they are for different vehicles, which is the point
// of a per vehicle roster; the server rejects an overlap within one vehicle.
//
// AUTH (S13): reading is public and stays public, the dashboard shows
// scheduled time to anyone. Saving is for operators and administrators, so
// when sign in exists, guard the save below and the PUT it calls.

let schedule = null;   // { monday: [{start, end, vehicles, operator}], ... }
let scheduleDays = [];
let scheduleFleet = [];
let removeOpen = null;

async function loadSchedule() {
  try {
    const data = await api('/api/schedule');
    scheduleDays = data.days;
    scheduleFleet = data.vehicles ?? [];
    schedule = data.schedule;
    document.getElementById('schedule-tz').textContent = data.timezone ?? 'local time';
    renderSync(data);
    renderSchedule();
    setScheduleStatus(data.configured ? '' : 'No service schedule is in the system yet.');
  } catch (err) {
    showScheduleError(`Could not load the schedule: ${err.message}`);
  }
}

// An empty or absent vehicle list means the whole fleet, so "All" is on when
// nothing is named rather than when everything is.
function vehicleChips(day, index, vehicles) {
  const all = !vehicles || !vehicles.length;
  const chip = (id, label, on, colour) =>
    `<button type="button" class="sched-chip${on ? ' is-on' : ''}"
       data-day="${day}" data-index="${index}" data-vehicle="${escHtml(id)}"
       style="--sched-vehicle:${escHtml(colour ?? 'currentColor')}"
       aria-pressed="${on}">${escHtml(label)}</button>`;

  return `
    <div class="sched-scope">
      ${chip('all', 'All', all, null)}
      ${scheduleFleet.map(v => chip(v.id, v.name ?? v.id, !all && vehicles.includes(v.id), v.colour)).join('')}
    </div>`;
}

// A date input gives YYYY-MM-DD; building the Date from parts keeps it on the
// day the operator picked rather than shifting it through UTC.
function fmtDate(iso) {
  const [y, m, d] = String(iso).split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
}

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

// Says when a period starts counting and when it stops, so a change booked
// ahead is visible rather than silently waiting.
function periodStatus(period) {
  const today = todayIso();
  const parts = [];

  if (period.starts_on) {
    parts.push(period.starts_on > today
      ? `Starts ${fmtDate(period.starts_on)}, not active yet`
      : `Active since ${fmtDate(period.starts_on)}`);
  }
  if (period.ends_on) {
    parts.push(period.ends_on > today
      ? `No longer active from ${fmtDate(period.ends_on)}`
      : `Ended ${fmtDate(period.ends_on)}`);
  }
  if (!parts.length) return '';

  const ended = period.ends_on && period.ends_on <= today;
  const pending = period.starts_on && period.starts_on > today;
  return `<p class="sched-status${ended || pending ? ' is-inactive' : ''}">${escHtml(parts.join(' · '))}</p>`;
}

// Removal is dated: the period stays on the roster, and on screen, until the
// day it stops applying. "Now" deletes the row outright.
function removePanel(key, period) {
  return `
    <div class="sched-remove">
      <span class="sched-remove-label">Remove</span>
      <button type="button" class="btn-xs danger" data-remove-now="${key}">Now</button>
      <span class="sched-remove-label">or from</span>
      <input type="date" class="form-input" data-remove-date="${key}"
             value="${period.ends_on ?? ''}" min="${todayIso()}" aria-label="Remove from date">
      ${period.ends_on ? `<button type="button" class="btn-xs" data-remove-cancel="${key}">Keep it</button>` : ''}
      <button type="button" class="btn-xs" data-remove-close="${key}">Done</button>
    </div>`;
}

function renderSchedule() {
  const today = todayIso();

  document.getElementById('schedule-days').innerHTML = scheduleDays.map(day => {
    const periods = schedule[day] ?? [];
    const rows = periods.map((period, index) => {
      const key = `${day}:${index}`;
      const inactive = (period.ends_on && period.ends_on <= today) || (period.starts_on && period.starts_on > today);

      return `
      <div class="sched-period${inactive ? ' is-inactive' : ''}">
        <div class="sched-times">
          <input type="time" class="form-input" value="${period.start}"
                 data-day="${day}" data-index="${index}" data-edge="start" aria-label="Start time">
          <span>to</span>
          <input type="time" class="form-input" value="${period.end}"
                 data-day="${day}" data-index="${index}" data-edge="end" aria-label="End time">
          <button type="button" class="btn-xs danger" data-remove-open="${key}"
                  aria-expanded="${removeOpen === key}">Remove</button>
        </div>
        ${vehicleChips(day, index, period.vehicles)}
        <label class="sched-operator">
          <span>Operator</span>
          <input type="text" class="form-input" maxlength="80" placeholder="Who drives it (optional)"
                 value="${escHtml(period.operator ?? '')}" data-operator="${key}" aria-label="Operator">
        </label>
        <label class="sched-from">
          <input type="checkbox" data-starts-toggle="${key}" ${period.starts_on ? 'checked' : ''}>
          <span>Start on</span>
          <input type="date" class="form-input" data-starts-date="${key}"
                 value="${period.starts_on ?? ''}" ${period.starts_on ? '' : 'disabled'}
                 aria-label="Start on date">
        </label>
        ${periodStatus(period)}
        ${removeOpen === key ? removePanel(key, period) : ''}
      </div>`;
    }).join('');

    return `
      <div class="schedule-day">
        <div class="schedule-day-head">
          <span class="schedule-day-name">${day}</span>
          <button type="button" class="btn-xs" data-add="${day}">Add period</button>
        </div>
        <div class="schedule-periods">
          ${rows || '<p class="schedule-closed">Not in service</p>'}
        </div>
      </div>`;
  }).join('');
}

// The roster synced from calendar.online, read only: its drives are not rows
// here and Save never sends them; they show on the calendar. This says where
// they come from, whether the last sync worked, and lets an admin re-read the
// calendar without waiting for the next one.
function renderSync(data) {
  const box = document.getElementById('schedule-sync');
  const sync = data.sync;
  box.hidden = !sync;
  if (!sync) return;

  const when = (iso) => new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const upcoming = Object.values(data.synced ?? {}).flat()
    .filter(period => period.starts_on >= todayIso()).length;
  const parts = [`Drives sync from ${sync.source}, read only, and show on the calendar with their operator.`];
  parts.push(sync.synced_at
    ? `Last synced ${when(sync.synced_at)}: ${sync.drives} drive${sync.drives === 1 ? '' : 's'}, ${upcoming} still to come.`
    : 'Not synced yet.');
  if (sync.error) parts.push(`⚠ The last attempt failed (${when(sync.error_at)}): ${sync.error} The last good copy is still in use.`);
  if (sync.conflicts?.length) {
    const list = sync.conflicts.map(c => `${when(c.start)} ${c.operator ?? ''}`.trim()).join('; ');
    parts.push(`⚠ Left out, as they overlap a period below for the same bus: ${list}.`);
  }
  const text = document.getElementById('schedule-sync-text');
  text.textContent = parts.join(' ');
  box.classList.toggle('has-error', Boolean(sync.error || sync.conflicts?.length));
}

document.getElementById('btn-schedule-sync').addEventListener('click', async () => {
  const button = document.getElementById('btn-schedule-sync');
  button.disabled = true;
  button.textContent = 'Syncing…';
  try {
    // Only the sync status is taken from the answer: unsaved edits to the
    // rows below stay as they are.
    renderSync(await api('/api/schedule/sync', { method: 'POST' }));
    window.AdminCalendar?.refresh();
  } catch (err) {
    showScheduleError(`Could not sync: ${err.message}`);
  } finally {
    button.disabled = false;
    button.textContent = 'Sync now';
  }
});

function showScheduleError(message) {
  const box = document.getElementById('schedule-error');
  box.textContent = message ? `⚠ ${message}` : '';
  box.classList.toggle('visible', Boolean(message));
}

function setScheduleStatus(message) {
  document.getElementById('schedule-status').textContent = message;
}

// Edits are held here until Save; nothing is written per keystroke.
// Look a period up from a "day:index" key.
function periodAt(key) {
  const [day, index] = key.split(':');
  return schedule[day]?.[Number(index)];
}

document.getElementById('schedule-days').addEventListener('input', event => {
  const input = event.target;

  if (input.dataset.edge) {
    schedule[input.dataset.day][Number(input.dataset.index)][input.dataset.edge] = input.value;
  } else if (input.dataset.operator) {
    periodAt(input.dataset.operator).operator = input.value.trim() || null;
  } else if (input.dataset.startsDate) {
    periodAt(input.dataset.startsDate).starts_on = input.value || null;
  } else if (input.dataset.removeDate) {
    periodAt(input.dataset.removeDate).ends_on = input.value || null;
  } else {
    return;
  }
  setScheduleStatus('Unsaved changes.');
});

// A date input commits on change, which is when the status line is worth
// redrawing; doing it per keystroke would fight the picker.
document.getElementById('schedule-days').addEventListener('change', event => {
  if (event.target.dataset.startsDate || event.target.dataset.removeDate) renderSchedule();
});

document.getElementById('schedule-days').addEventListener('click', event => {
  const target = event.target;
  const add = target.closest('[data-add]');
  const vehicle = target.closest('[data-vehicle]');
  const openRemove = target.closest('[data-remove-open]');
  const removeNow = target.closest('[data-remove-now]');
  const keepIt = target.closest('[data-remove-cancel]');
  const closeRemove = target.closest('[data-remove-close]');
  const startsToggle = target.closest('[data-starts-toggle]');

  if (add) {
    (schedule[add.dataset.add] ??= []).push({
      start: '08:00', end: '17:00', vehicles: null, starts_on: null, ends_on: null, operator: null,
    });
    removeOpen = null;
  } else if (openRemove) {
    // A second click closes it, so the button toggles its own panel.
    removeOpen = removeOpen === openRemove.dataset.removeOpen ? null : openRemove.dataset.removeOpen;
  } else if (removeNow) {
    const [day, index] = removeNow.dataset.removeNow.split(':');
    schedule[day].splice(Number(index), 1);
    removeOpen = null;
  } else if (keepIt) {
    periodAt(keepIt.dataset.removeCancel).ends_on = null;
  } else if (closeRemove) {
    removeOpen = null;
  } else if (startsToggle) {
    // Off by default. Turning it on starts from today, which is the common
    // case; turning it off puts the period back in force always.
    const period = periodAt(startsToggle.dataset.startsToggle);
    period.starts_on = period.starts_on ? null : todayIso();
  } else if (vehicle) {
    const period = schedule[vehicle.dataset.day][Number(vehicle.dataset.index)];
    const id = vehicle.dataset.vehicle;

    if (id === 'all') {
      period.vehicles = null;
    } else if (!period.vehicles?.length) {
      // Picking a vehicle while "All" is on means that one, not the fleet
      // minus it. Adding and removing applies from there.
      period.vehicles = [id];
    } else {
      const next = period.vehicles.includes(id)
        ? period.vehicles.filter(v => v !== id)
        : [...period.vehicles, id];
      // Every vehicle, or none left, is the same as fleet wide.
      period.vehicles = (next.length === scheduleFleet.length || !next.length) ? null : next;
    }
  } else {
    return;
  }

  renderSchedule();
  setScheduleStatus('Unsaved changes.');
});

document.getElementById('btn-schedule-save').addEventListener('click', async () => {
  // AUTH (S13): admin only; a 401 here sends the page to sign in.
  const button = document.getElementById('btn-schedule-save');
  button.disabled = true;
  showScheduleError('');
  setScheduleStatus('Saving…');

  try {
    const saved = await api('/api/schedule', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(schedule),
    });
    schedule = saved.schedule;
    removeOpen = null;
    renderSync(saved);
    renderSchedule();
    setScheduleStatus(saved.configured ? 'Saved.' : 'Saved. Nothing is rostered, so all time counts as unscheduled.');
    window.AdminCalendar?.refresh();
  } catch (err) {
    // The server validates too, so this is where a bad row is reported.
    showScheduleError(err.message);
    setScheduleStatus('Not saved.');
  } finally {
    button.disabled = false;
  }
});

document.getElementById('btn-schedule-reset').addEventListener('click', () => {
  showScheduleError('');
  loadSchedule();
});

loadSchedule();

// ---- Calendar ----
//
// The header calendar and the full view are js/admin-calendar.js, loaded after
// the Figures tab, since the period they pick is that tab's.
 // ---- Snapshot metric selection (S16) ----

const snapshotCheckboxes = document.querySelectorAll(
  '#snapshot-metrics input[type="checkbox"]'
);

const snapshotSaveButton = document.getElementById('btn-snapshot-save');
const snapshotStatus = document.getElementById('snapshot-status');

let savedSnapshotMetrics = [];

function selectedSnapshotMetrics() {
  return Array.from(snapshotCheckboxes)
    .filter(checkbox => checkbox.checked)
    .map(checkbox => checkbox.value);
}

function updateSnapshotSaveButton() {
  const selected = selectedSnapshotMetrics();

  // Only enable Save when at least one metric is selected
  // and the selection differs from the saved settings, in any order.
  const sorted = (metrics) => JSON.stringify([...metrics].sort());
  snapshotSaveButton.disabled =
    selected.length === 0 ||
    sorted(selected) === sorted(savedSnapshotMetrics);
}

snapshotCheckboxes.forEach(checkbox => {
  checkbox.addEventListener('change', () => {
    snapshotStatus.textContent = '';
    updateSnapshotSaveButton();
  });
});

// Load the saved metric selection from the backend.
async function loadSnapshotSettings() {
  snapshotSaveButton.disabled = true;
  snapshotStatus.textContent = 'Loading snapshot settings...';

  try {
    const { ok, status, data } = await downtimeRequest(
      'GET',
      '/api/snapshot-settings'
    );

    if (!ok) {
      throw new Error(
        data?.error?.message ?? `Could not load snapshot settings (${status}).`
      );
    }

    savedSnapshotMetrics = data.metrics;

    snapshotCheckboxes.forEach(checkbox => {
      checkbox.checked = savedSnapshotMetrics.includes(checkbox.value);
    });

    snapshotStatus.textContent = '';
    updateSnapshotSaveButton();

  } catch (err) {
    snapshotStatus.textContent = err.message;
  }
}

// Save the administrator's selected metrics.
snapshotSaveButton.addEventListener('click', async () => {
  const selected = selectedSnapshotMetrics();

  if (!selected.length) {
    snapshotStatus.textContent = 'Please select at least one metric.';
    return;
  }

  snapshotSaveButton.disabled = true;
  snapshotStatus.textContent = 'Saving...';

  try {
    const { ok, status, data } = await downtimeRequest(
      'PUT',
      '/api/snapshot-settings',
      { metrics: selected }
    );

    if (!ok) {
      throw new Error(
        data?.error?.message ?? `Could not save snapshot settings (${status}).`
      );
    }

    savedSnapshotMetrics = data.metrics;
    snapshotStatus.textContent = 'Snapshot settings saved successfully.';

  } catch (err) {
    snapshotStatus.textContent = err.message;
  } finally {
    updateSnapshotSaveButton();
  }
});

loadSnapshotSettings();
