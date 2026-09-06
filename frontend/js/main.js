const state = {
  view: 'fleet',
  mode: 'live',
  date: null,
  latestRecordedDate: null,
  vehicle: 'all',
  selected: null,
  layers: { trails: true, markers: true, gaps: false },
  fleetMeta: null,
  data: { vehicles: [], from: null, to: null },
  loading: false,
  refreshTimer: null
};

const els = {};

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

function perthDateString(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-AU', { timeZone: 'Australia/Perth', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
  const get = type => parts.find(p => p.type === type)?.value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

function perthDateFromIso(iso) { return iso ? perthDateString(new Date(iso)) : null; }
function formatPerth(iso, opts = {}) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-AU', { timeZone: 'Australia/Perth', day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit', second: opts.seconds ? '2-digit' : undefined });
}
function formatTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-AU', { timeZone: 'Australia/Perth', hour:'2-digit', minute:'2-digit', second:'2-digit' });
}
function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(seconds < 36000 ? 1 : 0)} h`;
}
function fmtSpeed(p) { return p?.speed_mps == null ? '—' : `${(p.speed_mps * 3.6).toFixed(1)} km/h`; }
function fmtBattery(p) { return p?.battery_percent == null ? '—' : `${Math.round(p.battery_percent)}%`; }
function gpsLabel(p) {
  if (!p || p.gps_status == null) return 'Unknown';
  return p.gps_status === -1 ? 'No fix' : p.gps_status === 0 ? 'Fix' : p.gps_status === 1 ? 'SBAS' : p.gps_status === 2 ? 'GBAS' : `Status ${p.gps_status}`;
}
function latestPosition(vehicle) { return vehicle?.positions?.length ? vehicle.positions[vehicle.positions.length - 1] : null; }
function vehicleName(id) { return state.fleetMeta?.vehicles?.find(v => v.id === id)?.name || `nUWAy ${id}`; }
function vehicleColour(id) { return state.fleetMeta?.vehicles?.find(v => v.id === id)?.colour || '#716879'; }

function haversine(a, b) {
  if (!a || !b || a.latitude == null || a.longitude == null || b.latitude == null || b.longitude == null) return 0;
  const R = 6371000, rad = x => x * Math.PI / 180;
  const dLat = rad(b.latitude - a.latitude), dLon = rad(b.longitude - a.longitude);
  const lat1 = rad(a.latitude), lat2 = rad(b.latitude);
  const h = Math.sin(dLat/2)**2 + Math.cos(lat1)*Math.cos(lat2)*Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function telemetryStats(vehicle) {
  const rows = vehicle?.positions || [];
  if (!rows.length) return { samples:0, span:0, recorded:0, moving:0, stationary:0, nofix:0, unknown:0, distance:0, avgSpeed:null, fixRate:null };
  const speedValues = rows.map(p => p.speed_mps).filter(Number.isFinite);
  const gpsKnown = rows.filter(p => p.gps_status != null);
  const fixRows = gpsKnown.filter(p => p.gps_status >= 0);
  let recorded=0, moving=0, stationary=0, nofix=0, unknown=0, distance=0;
  for (let i=0; i<rows.length-1; i++) {
    const a=rows[i], b=rows[i+1];
    const dt=(new Date(b.timestamp)-new Date(a.timestamp))/1000;
    if (!Number.isFinite(dt) || dt <= 0 || dt > 120) continue;
    recorded += dt;
    if (a.gps_status === -1) nofix += dt;
    else if (!Number.isFinite(a.speed_mps)) unknown += dt;
    else if (a.speed_mps > 0.5) moving += dt;
    else stationary += dt;
    distance += haversine(a,b);
  }
  const span=(new Date(rows[rows.length-1].timestamp)-new Date(rows[0].timestamp))/1000;
  return {
    samples:rows.length, span, recorded, moving, stationary, nofix, unknown, distance,
    avgSpeed:speedValues.length ? speedValues.reduce((a,b)=>a+b,0)/speedValues.length : null,
    fixRate:gpsKnown.length ? fixRows.length/gpsKnown.length : null
  };
}

function combinedStats() {
  const stats = state.data.vehicles.map(telemetryStats);
  return stats.reduce((a,s) => ({
    samples:a.samples+s.samples, recorded:a.recorded+s.recorded, moving:a.moving+s.moving,
    stationary:a.stationary+s.stationary, nofix:a.nofix+s.nofix, unknown:a.unknown+s.unknown,
    distance:a.distance+s.distance
  }), {samples:0,recorded:0,moving:0,stationary:0,nofix:0,unknown:0,distance:0});
}

function setStatus(message) {
  els.status.textContent = message || '';
  els.status.hidden = !message;
}

function currentDateForMode() {
  if (state.mode === 'today') return perthDateString();
  if (state.mode === 'calendar') return state.date;
  return null;
}

function configureRefresh() {
  clearInterval(state.refreshTimer);
  state.refreshTimer = null;
  if (state.mode !== 'live') return;
  const seconds = state.fleetMeta?.refresh_interval_seconds || 15;
  state.refreshTimer = setInterval(() => refreshData({ quiet: true, fit: false }), seconds * 1000);
}

async function refreshData({ quiet = false, fit = true } = {}) {
  if (state.loading) return;
  state.loading = true;
  if (!quiet) setStatus('Loading telemetry…');
  try {
    const data = await getPositions({ vehicle: state.vehicle, mode: state.mode, date: currentDateForMode() });
    state.data = data;
    if (state.mode === 'live' && data.to) {
      state.latestRecordedDate = perthDateFromIso(data.to);
      if (!state.date) state.date = state.latestRecordedDate;
      if (state.latestRecordedDate) els.dateFilter.value = state.latestRecordedDate;
    }
    const ids = data.vehicles.filter(v => v.count > 0).map(v => v.vehicle_id);
    if (!state.selected || !ids.includes(state.selected)) state.selected = ids[0] || data.vehicles[0]?.vehicle_id || null;
    renderAll({ fit });
    const total = data.vehicles.reduce((n,v)=>n+v.count,0);
    setStatus(total ? null : `No telemetry for ${summaryTimeLabel().toLowerCase()}${state.vehicle === 'all' ? '' : ` · ${vehicleName(state.vehicle)}`}.`);
  } catch (error) {
    setStatus(error.message);
  } finally {
    state.loading = false;
  }
}

function summaryTimeLabel() {
  if (state.mode === 'live') return 'Live repository';
  if (state.mode === 'today') return `Today · ${perthDateString()}`;
  return state.date ? `Calendar · ${state.date}` : 'Calendar';
}

function renderFilters() {
  document.querySelectorAll('.mode').forEach(btn => btn.classList.toggle('active', btn.dataset.mode === state.mode));
  els.dateFilter.disabled = state.mode !== 'calendar';
  if (state.date) els.dateFilter.value = state.date;
  els.vehicleChips.innerHTML = [
    `<button class="chip ${state.vehicle==='all'?'active':''}" data-vehicle="all">All vehicles</button>`,
    ...(state.fleetMeta?.vehicles || []).map(v => `<button class="chip ${state.vehicle===v.id?'active':''}" data-vehicle="${esc(v.id)}">${esc(v.name || v.id)}</button>`)
  ].join('');
  const vLabel = state.vehicle === 'all' ? 'All vehicles' : vehicleName(state.vehicle);
  els.filterSummary.textContent = `${vLabel} · ${summaryTimeLabel()}`;
}

function renderTabs() {
  document.querySelectorAll('.tab').forEach(btn => btn.classList.toggle('active', btn.dataset.view === state.view));
  const util = state.view === 'utilisation';
  els.mapWorkspace.hidden = util;
  els.utilisationView.hidden = !util;
  els.fleetPanel.hidden = state.view !== 'fleet';
  els.operatorPanel.hidden = state.view !== 'operator';
  els.riderPanel.hidden = state.view !== 'rider';
  if (!util) setTimeout(() => map?.invalidateSize(), 30);
}

function renderLegend() {
  const shown = state.data.vehicles.filter(v=>v.count>0);
  els.mapLegend.innerHTML = shown.map(v => `<span class="legend-item"><i class="legend-swatch" style="background:${esc(v.colour || vehicleColour(v.vehicle_id))}"></i>${esc(v.name || vehicleName(v.vehicle_id))}</span>`).join('') || '<span>No telemetry in selection</span>';
  els.dataBadge.textContent = state.mode === 'live' ? 'LATEST STORED TRACKS' : summaryTimeLabel().toUpperCase();
}

function renderFleetPanel() {
  const withData = state.data.vehicles.filter(v=>v.count>0).length;
  const totalSamples = state.data.vehicles.reduce((n,v)=>n+v.count,0);
  const overallFrom = state.data.vehicles.flatMap(v=>v.positions).map(p=>new Date(p.timestamp)).sort((a,b)=>a-b)[0];
  const overallTo = state.data.vehicles.flatMap(v=>v.positions).map(p=>new Date(p.timestamp)).sort((a,b)=>a-b).at(-1);
  const span = overallFrom && overallTo ? (overallTo-overallFrom)/1000 : 0;
  const rows = state.data.vehicles.map(v => {
    const p = latestPosition(v), has=v.count>0, selected=v.vehicle_id===state.selected;
    const meta = [has ? `${v.count} pts` : '0 pts', fmtSpeed(p), fmtBattery(p)].join('</span><span>');
    return `<div class="vehicle-row ${selected?'selected':''} ${has?'':'empty'}" data-select="${esc(v.vehicle_id)}">
      <div class="vehicle-main"><div class="vehicle-title"><strong>${esc(v.name || vehicleName(v.vehicle_id))}</strong><span class="badge ${has ? (p?.gps_status===-1?'no-fix':'has-data') : ''}">${has ? (p?.gps_status===-1?'NO FIX':'DATA') : 'NO DATA'}</span></div>
      <div class="vehicle-note">${has ? `Last sample ${esc(formatPerth(p.timestamp))}` : 'No telemetry in the selected period'}</div><div class="vehicle-meta"><span>${meta}</span></div></div>
      <div class="vehicle-num">${esc(v.vehicle_id.padStart?.(2,'0') || v.vehicle_id)}</div></div>`;
  }).join('');
  els.fleetPanel.innerHTML = `<div class="panel-heading"><h2>Vehicles</h2><span class="mono">${withData} of ${state.data.vehicles.length} with data</span></div>${rows}
    <div class="panel-section"><span class="section-label">MAP LAYERS</span>
      ${layerRow('trails','Recorded tracks')}${layerRow('markers','Last positions')}${layerRow('gaps','GPS no-fix points')}
      <div class="layer-row" style="opacity:.45;cursor:default"><span>Engage / disengage</span><span class="mono" style="font-size:9px">API PENDING</span></div>
    </div>
    <div class="kpi-strip"><div class="mini-kpi"><span>WITH DATA</span><strong>${withData}</strong></div><div class="mini-kpi"><span>SAMPLES</span><strong>${totalSamples.toLocaleString()}</strong></div><div class="mini-kpi"><span>SPAN</span><strong>${formatDuration(span)}</strong></div></div>`;
}

function layerRow(key,label) { return `<div class="layer-row" data-layer="${key}"><span>${label}</span><span class="switch ${state.layers[key]?'on':''}"></span></div>`; }

function renderOperatorPanel() {
  const vehicle = state.data.vehicles.find(v=>v.vehicle_id===state.selected) || state.data.vehicles[0];
  if (!vehicle) { els.operatorPanel.innerHTML='<div class="panel-section"><div class="empty-card">No vehicle is available for this selection.</div></div>'; return; }
  const p=latestPosition(vehicle), stats=telemetryStats(vehicle), has=vehicle.count>0;
  els.operatorPanel.innerHTML = `<div class="detail-header"><div class="detail-title"><h2>${esc(vehicle.name || vehicleName(vehicle.vehicle_id))}</h2><span class="badge ${has?'has-data':''}">${has?'TELEMETRY':'NO DATA'}</span></div>
    <div class="detail-grid"><div class="detail-cell"><span>SPEED</span><strong>${fmtSpeed(p)}</strong></div><div class="detail-cell"><span>BATTERY</span><strong>${fmtBattery(p)}</strong></div><div class="detail-cell"><span>GPS</span><strong>${esc(gpsLabel(p))}</strong></div><div class="detail-cell"><span>LAST SAMPLE</span><strong>${p?esc(formatTime(p.timestamp)):'—'}</strong></div></div></div>
    <div class="panel-section"><span class="section-label">SELECTED TRACK</span><div class="detail-grid"><div class="detail-cell"><span>POSITIONS</span><strong>${stats.samples}</strong></div><div class="detail-cell"><span>DISTANCE</span><strong>${stats.distance>=1000?(stats.distance/1000).toFixed(2)+' km':Math.round(stats.distance)+' m'}</strong></div><div class="detail-cell"><span>RECORDED</span><strong>${formatDuration(stats.recorded)}</strong></div><div class="detail-cell"><span>AVG SPEED</span><strong>${stats.avgSpeed==null?'—':(stats.avgSpeed*3.6).toFixed(1)+' km/h'}</strong></div></div></div>
    <div class="panel-heading"><h2>Event log</h2><span>API pending</span></div><div class="panel-section" style="padding-top:0"><div class="empty-card">The Map project does not yet define or expose engage/disengage events, so this view deliberately does not display prototype events as if they were real.</div></div>
    <div class="panel-section"><span class="section-label">OPERATOR DATA</span><div class="empty-card">Occupancy, operator identity and autonomy state are not present in the current telemetry schema. They can be wired here when those feeds are added.</div></div>`;
}

function renderRiderPanel() {
  const available=state.data.vehicles.filter(v=>v.count>0);
  els.riderPanel.innerHTML = `<div class="rider-wrap"><div class="rider-title"><strong>nuway shuttle</strong><span>Current position information from the fleet telemetry repository</span></div>
    ${available.map(v=>{const p=latestPosition(v);return `<div class="vehicle-card" data-select="${esc(v.vehicle_id)}"><div class="row"><strong>${esc(v.name || vehicleName(v.vehicle_id))}</strong><span class="mono">${esc(fmtSpeed(p))}</span></div><span>Last recorded ${esc(formatPerth(p?.timestamp))}</span><span>${p?.latitude==null?'Location unavailable':`${p.latitude.toFixed(5)}, ${p.longitude.toFixed(5)}`}</span></div>`}).join('') || '<div class="empty-card">No vehicle telemetry is available for this selection.</div>'}
    <div class="disabled-action">Rider stop request unavailable in this build</div>
    <div class="empty-card">The Map project explicitly lists <span class="mono">POST /api/stop-requests</span> as not implemented, and it contains no stop/route definition. The Rider view is retained without inventing stops, ETAs or passenger counts.</div></div>`;
}

function renderUtilisation() {
  const total=combinedStats();
  const recorded=total.recorded || 0;
  const parts=[
    ['Moving',total.moving,'oklch(0.36 0.13 300)'],['Stationary',total.stationary,'oklch(0.62 0.05 200)'],['GPS no fix',total.nofix,'oklch(0.72 0.14 75)'],['Unknown speed',total.unknown,'rgba(28,25,23,.28)']
  ];
  const gradient = recorded ? (()=>{let a=0;return parts.map(([,sec,col])=>{const b=a+sec/recorded*360;const x=`${col} ${a.toFixed(1)}deg ${b.toFixed(1)}deg`;a=b;return x}).join(',')})() : 'rgba(28,25,23,.08) 0deg 360deg';
  const movingShare = recorded ? total.moving/recorded : 0;
  const scope = state.vehicle==='all'?'Fleet telemetry':vehicleName(state.vehicle);
  const rows=state.data.vehicles.map(v=>{const s=telemetryStats(v);return `<div class="util-row clickable" data-select="${esc(v.vehicle_id)}"><strong>${esc(v.name || vehicleName(v.vehicle_id))}</strong><span class="mono">${s.samples}</span><span class="mono">${formatDuration(s.recorded)}</span><span class="mono">${s.recorded?(s.moving/s.recorded*100).toFixed(1)+'%':'—'}</span><span class="mono">${s.distance>=1000?(s.distance/1000).toFixed(2)+' km':Math.round(s.distance)+' m'}</span><span class="mono">${s.fixRate==null?'—':(s.fixRate*100).toFixed(1)+'%'}</span></div>`}).join('');
  els.utilisationView.innerHTML = `<div class="util-header"><h2>${esc(scope)} · ${esc(summaryTimeLabel())}</h2><span class="mono" style="font-size:10px;color:rgba(28,25,23,.45)">TELEMETRY-DERIVED</span></div>
    <div class="notice"><strong>Formal utilisation metrics are not implemented in Map.zip.</strong> The figures below are diagnostics derived only from position samples; they are not GMG Time Usage Model, uptime, availability or operating-efficiency metrics.</div>
    <div class="kpi-grid"><div class="kpi-card"><span>RECORDED SAMPLES</span><strong>${total.samples.toLocaleString()}</strong><small>position rows in selection</small></div><div class="kpi-card"><span>RECORDED INTERVAL</span><strong>${formatDuration(total.recorded)}</strong><small>valid sample-to-sample intervals</small></div><div class="kpi-card"><span>MOVING SHARE</span><strong>${recorded?(movingShare*100).toFixed(1)+'%':'—'}</strong><small>speed &gt; 0.5 m/s · not utilisation</small></div><div class="kpi-card"><span>TRACK DISTANCE</span><strong>${total.distance>=1000?(total.distance/1000).toFixed(2)+' km':Math.round(total.distance)+' m'}</strong><small>GPS point-to-point distance</small></div></div>
    <div class="util-card breakdown"><div class="donut" style="background:conic-gradient(${gradient})"><div class="donut-center"><strong>${recorded?(movingShare*100).toFixed(0)+'%':'—'}</strong><span>MOVING SHARE</span></div></div><div class="breakdown-list">${parts.map(([label,sec,col])=>`<div class="breakdown-row"><i style="background:${col}"></i><span>${label}</span><span class="mono">${formatDuration(sec)}</span><span class="mono">${recorded?(sec/recorded*100).toFixed(1)+'%':'—'}</span></div>`).join('')}</div></div>
    <div class="util-table"><div class="util-row header"><span>VEHICLE</span><span>SAMPLES</span><span>RECORDED</span><span>MOVING</span><span>DISTANCE</span><span>GPS FIX</span></div>${rows || '<div class="panel-section"><div class="empty-card">No telemetry is available.</div></div>'}</div>`;
}

function renderMapView({ fit = true } = {}) {
  const drawn=renderMap(state.data.vehicles, { selectedVehicle:state.selected, showTrails:state.layers.trails, showMarkers:state.layers.markers, showGaps:state.layers.gaps, fit });
  if (!drawn) setStatus(`No telemetry for ${summaryTimeLabel().toLowerCase()}.`);
}

function renderAll({ fit = true } = {}) {
  renderTabs();
  renderFilters();
  renderLegend();
  renderFleetPanel();
  renderOperatorPanel();
  renderRiderPanel();
  renderUtilisation();
  if (state.view !== 'utilisation') renderMapView({ fit });
}

function bindEvents() {
  document.addEventListener('click', event => {
    const tab=event.target.closest('[data-view]');
    if (tab) { state.view=tab.dataset.view; renderAll({fit:false}); return; }
    const mode=event.target.closest('[data-mode]');
    if (mode) {
      state.mode=mode.dataset.mode;
      if (state.mode==='today') state.date=perthDateString();
      if (state.mode==='calendar' && !state.date) state.date=state.latestRecordedDate || perthDateString();
      configureRefresh(); refreshData(); return;
    }
    const vehicle=event.target.closest('[data-vehicle]');
    if (vehicle) { state.vehicle=vehicle.dataset.vehicle; refreshData(); return; }
    const selected=event.target.closest('[data-select]');
    if (selected) { state.selected=selected.dataset.select; if (state.view==='fleet') state.view='operator'; renderAll({fit:false}); focusVehicle(state.selected); return; }
    const layer=event.target.closest('[data-layer]');
    if (layer) { const key=layer.dataset.layer; state.layers[key]=!state.layers[key]; renderAll({fit:false}); }
  });
  els.dateFilter.addEventListener('change', event => {
    if (!event.target.value) return;
    if (event.target.value > perthDateString()) { event.target.value = state.date || state.latestRecordedDate || perthDateString(); return; }
    state.date=event.target.value; state.mode='calendar'; configureRefresh(); refreshData();
  });
  window.addEventListener('nuway:vehicle-select', event => { state.selected=event.detail; state.view='operator'; renderAll({fit:false}); focusVehicle(state.selected); });
  window.addEventListener('resize', () => setTimeout(()=>map?.invalidateSize(),30));
}

async function load() {
  Object.assign(els, {
    status:document.getElementById('status'), clock:document.getElementById('clock'), liveDot:document.getElementById('liveDot'), liveLabel:document.getElementById('liveLabel'),
    vehicleChips:document.getElementById('vehicleChips'), dateFilter:document.getElementById('dateFilter'), filterSummary:document.getElementById('filterSummary'),
    mapWorkspace:document.getElementById('mapWorkspace'), utilisationView:document.getElementById('utilisationView'), fleetPanel:document.getElementById('fleetPanel'), operatorPanel:document.getElementById('operatorPanel'), riderPanel:document.getElementById('riderPanel'), mapLegend:document.getElementById('mapLegend'), dataBadge:document.getElementById('dataBadge')
  });
  initMap(); bindEvents();
  els.dateFilter.max = perthDateString();
  setInterval(()=>{ els.clock.textContent=new Date().toLocaleTimeString('en-AU',{timeZone:'Australia/Perth',hour:'2-digit',minute:'2-digit',second:'2-digit'}); },1000);
  try {
    state.fleetMeta=await getVehicles();
    const active=state.fleetMeta.vehicles.filter(v=>v.status==='active').length;
    els.liveLabel.textContent=active?`${active} active`:'Repository';
    els.liveDot.classList.toggle('inactive',active===0);
    configureRefresh();
    await refreshData();
  } catch (error) { setStatus(error.message); }
}

document.addEventListener('DOMContentLoaded', load);
