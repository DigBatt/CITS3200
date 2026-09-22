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

let schedule = null;   // { monday: [{start, end, vehicles}], ... }
let scheduleDays = [];
let scheduleFleet = [];

async function loadSchedule() {
  try {
    const data = await api('/api/schedule');
    scheduleDays = data.days;
    scheduleFleet = data.vehicles ?? [];
    schedule = data.schedule;
    document.getElementById('schedule-tz').textContent = data.timezone ?? 'local time';
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

function renderSchedule() {
  document.getElementById('schedule-days').innerHTML = scheduleDays.map(day => {
    const periods = schedule[day] ?? [];
    const rows = periods.map((period, index) => `
      <div class="sched-period">
        <div class="sched-times">
          <input type="time" class="form-input" value="${period.start}"
                 data-day="${day}" data-index="${index}" data-edge="start" aria-label="Start time">
          <span>to</span>
          <input type="time" class="form-input" value="${period.end}"
                 data-day="${day}" data-index="${index}" data-edge="end" aria-label="End time">
          <button type="button" class="btn-xs danger" data-remove="${day}" data-index="${index}">Remove</button>
        </div>
        ${vehicleChips(day, index, period.vehicles)}
      </div>`).join('');

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

function showScheduleError(message) {
  const box = document.getElementById('schedule-error');
  box.textContent = message ? `⚠ ${message}` : '';
  box.classList.toggle('visible', Boolean(message));
}

function setScheduleStatus(message) {
  document.getElementById('schedule-status').textContent = message;
}

// Edits are held here until Save; nothing is written per keystroke.
document.getElementById('schedule-days').addEventListener('input', event => {
  const input = event.target;
  if (!input.dataset.edge) return;
  schedule[input.dataset.day][Number(input.dataset.index)][input.dataset.edge] = input.value;
  setScheduleStatus('Unsaved changes.');
});

document.getElementById('schedule-days').addEventListener('click', event => {
  const add = event.target.closest('[data-add]');
  const remove = event.target.closest('[data-remove]');
  const vehicle = event.target.closest('[data-vehicle]');

  if (add) {
    (schedule[add.dataset.add] ??= []).push({ start: '08:00', end: '17:00', vehicles: null });
  } else if (remove) {
    schedule[remove.dataset.remove].splice(Number(remove.dataset.index), 1);
  } else if (vehicle) {
    const period = schedule[vehicle.dataset.day][Number(vehicle.dataset.index)];
    const id = vehicle.dataset.vehicle;

    if (id === 'all') {
      period.vehicles = null;
    } else {
      // Coming from "All", the first pick starts from the whole fleet so that
      // de-selecting one leaves the rest, which is what the click means.
      const current = period.vehicles?.length ? period.vehicles : scheduleFleet.map(v => v.id);
      const next = current.includes(id) ? current.filter(v => v !== id) : [...current, id];
      // Every vehicle, or none, is the same as fleet wide.
      period.vehicles = (next.length === scheduleFleet.length || !next.length) ? null : next;
    }
  } else {
    return;
  }

  renderSchedule();
  setScheduleStatus('Unsaved changes.');
});

document.getElementById('btn-schedule-save').addEventListener('click', async () => {
  // AUTH (S13): an operator or administrator only action.
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
    renderSchedule();
    setScheduleStatus(saved.configured ? 'Saved.' : 'Saved. Nothing is rostered, so all time counts as unscheduled.');
    miniCalendar.refresh();
    fullCalendar?.refresh();
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

// ---- Calendar: the docked mini month, and the full view it opens ----
//
// The mini month is always on screen. The full calendar is built the first
// time it is opened, so a session that never opens it never fetches for it.
//
// AUTH (S13): both are view only, over reads that stay public.

const overlay = document.getElementById('cal-overlay');
let fullCalendar = null;

function openCalendar(day) {
  overlay.hidden = false;
  document.body.classList.add('is-overlaid');

  if (fullCalendar) {
    fullCalendar.goTo(day ?? new Date());
  } else {
    // Opens on the week; the 3 day option is in the calendar's own controls.
    fullCalendar = ServiceCalendar.create(document.getElementById('cal-overlay-body'), {
      days: 7,
      anchor: day ?? new Date(),
    });
  }
  document.getElementById('cal-overlay-close').focus();
}

function closeCalendar() {
  overlay.hidden = true;
  document.body.classList.remove('is-overlaid');
}

const miniCalendar = ServiceCalendar.createMini(document.getElementById('mini-calendar'), {
  onOpen: openCalendar,
});

// The dock as a whole opens the calendar, so a click anywhere on it that is
// not a day or a month arrow still does the obvious thing.
document.getElementById('mini-calendar').addEventListener('click', event => {
  if (!event.target.closest('[data-mini-day], [data-mini-month]')) openCalendar();
});
document.getElementById('mini-calendar').addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    openCalendar();
  }
});

document.getElementById('cal-overlay-close').addEventListener('click', closeCalendar);
// Clicking the backdrop, but not the panel on it.
overlay.addEventListener('click', event => {
  if (event.target === overlay) closeCalendar();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !overlay.hidden) closeCalendar();
});
