// Leaflet setup: map init, tile layer, and one layer group per overlay.
//
// Layer groups map one-to-one onto the overlays.
//
// Owns: vehicle markers, position trails, event markers, stop markers.

let map = null;
const layers = { trails: null, stops: null };

let pendingFit = null;

// Rider tab: always frame the campus stops, never the fleet's full extent.
// One configured bus runs off campus, and fitting to every vehicle's position
// (fitTo() below, called from drawTracks()) would zoom out to include it --
// fine for Fleet, not what a rider picking a campus stop needs to see. Set
// from the configured stops (js/stops.js:init(), the campus the shuttles
// actually serve) rather than hardcoded, so it tracks config/stops.yaml.
let focusOnCampus = false;
let campusBounds = null;

// Every stop label drawn at once is unreadable when zoomed out past the
// campus, so below this the names are hidden and the markers stay.
const STOP_LABEL_MIN_ZOOM = 15;

// Bus markers: a numbered circle, in px. Kept in step with .bus-marker in
// css/dashboard.css.
const BUS_MARKER_SIZE = 28;
const BUS_MARKER_FALLBACK_COLOUR = 'rgba(28, 25, 23, 0.8)';

// Stops are drawn in their own pane, under the trails and vehicle markers.
let stopRenderer = null;

// Kept so selecting a route restyles the markers in place. Redrawing the
// layer instead would rebuild every tooltip on each click.
const stopMarkers = new Map(); // stop id -> circleMarker

// No route selected: every stop reads the same.
const STOP_NEUTRAL = {
  radius: 5,
  weight: 2,
  color: 'rgba(28, 25, 23, 0.55)',
  fillColor: '#ffffff',
  fillOpacity: 1,
};

// On the selected route: the route's own colour, filled and larger.
const STOP_ON_ROUTE = { radius: 7, weight: 2, color: '#ffffff', fillOpacity: 1 };
const STOP_ON_ROUTE_FALLBACK_COLOUR = 'rgba(28, 25, 23, 0.8)';

// Off it: present, but plainly secondary.
const STOP_OFF_ROUTE = {
  radius: 4,
  weight: 1.5,
  color: 'rgba(28, 25, 23, 0.3)',
  fillColor: '#ffffff',
  fillOpacity: 0.65,
};

// The Leaflet style for one stop under the current selection. Kept free of
// Leaflet and of the DOM so it can be tested on its own.
function styleForStop(stop, selectedRouteId, routeColour) {
  if (!selectedRouteId) return { ...STOP_NEUTRAL };
  if (!stop.routes.includes(selectedRouteId)) return { ...STOP_OFF_ROUTE };
  return { ...STOP_ON_ROUTE, fillColor: routeColour ?? STOP_ON_ROUTE_FALLBACK_COLOUR };
}

function initMap() {
  map = L.map('map').setView([-31.98133, 115.81597], 16); // sets the initial to UWA campus
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  map.createPane('stops').style.zIndex = 350; // below overlayPane (400)
  stopRenderer = L.svg({ pane: 'stops' });

  // The bus markers sit above the stop labels (tooltipPane, 650), so a bus
  // waiting at a stop is not hidden under its name. Popups (700) stay on top.
  map.createPane('buses').style.zIndex = 660;

  layers.stops = L.layerGroup().addTo(map);
  layers.trails = L.layerGroup().addTo(map);

  map.on('zoomend', applyStopLabelZoom);
  applyStopLabelZoom();
}

// Draw the configured stops. They come from config and change only on a
// restart, so this is called once rather than on every live poll.
function drawStops(stops, { popupHtml = null } = {}) {
  layers.stops.clearLayers();
  stopMarkers.clear();

  for (const stop of stops) {
    const marker = L.circleMarker([stop.latitude, stop.longitude], {
      renderer: stopRenderer,
      pane: 'stops',
      ...STOP_NEUTRAL,
    })
      .bindTooltip(stop.id, {
        permanent: true,
        direction: 'top',
        offset: [0, -7],
        className: 'stop-label',
      })
      .addTo(layers.stops);

    if (popupHtml) marker.bindPopup(popupHtml(stop), { className: 'stop-popup', closeButton: false });

    stopMarkers.set(stop.id, marker);
  }

  return stops.length;
}

// Restyle the drawn stops for the selected route, or for none. The stops a
// route serves stay full strength; the rest fade, labels included.
function highlightRoute(stops, selectedRouteId, routeColour) {
  for (const stop of stops) {
    const marker = stopMarkers.get(stop.id);
    if (!marker) continue;

    marker.setStyle(styleForStop(stop, selectedRouteId, routeColour));

    // Null while the layer is hidden by the Stops toggle, since a tooltip has
    // no element until it is on the map.
    const label = marker.getTooltip()?.getElement();
    label?.classList.toggle('is-dimmed', Boolean(selectedRouteId) && !stop.routes.includes(selectedRouteId));
  }
}

// Rider stop picker (S15): fully hide every stop marker and label but one, to
// cut clutter while choosing. Pass null to show them all again — done
// whenever the rider leaves the picker (map.js is shared with Fleet, so this
// must not leak into its view of the map; js/rider.js and js/panels.js are
// what keep it scoped to the Rider tab).
function isolateStop(stopId) {
  for (const [id, marker] of stopMarkers) {
    const hide = stopId !== null && id !== stopId;
    marker.getElement()?.classList.toggle('is-hidden-stop', hide);
    marker.getTooltip()?.getElement()?.classList.toggle('is-hidden-stop', hide);
  }
}

// Open a stop's existing popup (bound in Stops.init(), stops.js) so the rider
// picker confirms which stop was chosen (S15) — the same popup every other
// view already gets by clicking the marker directly. Leaflet auto-pans it
// into view, and closes whatever popup was open before.
function openStopPopup(stopId) {
  stopMarkers.get(stopId)?.openPopup();
}

// Show or hide the whole stop layer. The markers are kept, so turning it back
// on needs no refetch.
function setStopsVisible(visible) {
  if (visible) {
    layers.stops.addTo(map);
  } else {
    map.removeLayer(layers.stops);
  }
}

function applyStopLabelZoom() {
  map.getContainer().classList.toggle('hide-stop-labels', map.getZoom() < STOP_LABEL_MIN_ZOOM);
}

// The bus's latest position in the period: its number in a circle of its
// colour, so each bus on the map can be told apart without the legend.
function busIcon(vehicle) {
  return L.divIcon({
    className: 'bus-marker',
    html: `<span style="background: ${escapeHtml(vehicle.colour ?? BUS_MARKER_FALLBACK_COLOUR)}">${escapeHtml(vehicle.vehicle_id)}</span>`,
    iconSize: [BUS_MARKER_SIZE, BUS_MARKER_SIZE],
    iconAnchor: [BUS_MARKER_SIZE / 2, BUS_MARKER_SIZE / 2], // centred on the position
  });
}

function drawTracks(vehicles, { fit = true } = {}) {
  layers.trails.clearLayers();
  if (fit) pendingFit = null;
  const bounds = L.latLngBounds([]);
  let drawn = 0;

  for (const vehicle of vehicles) {
    // A row with no fix carries no coordinates, so it cannot be plotted.
    const points = vehicle.positions
      .filter((p) => p.latitude !== null && p.longitude !== null)
      .map((p) => [p.latitude, p.longitude]);

    if (points.length === 0) continue;
    drawn += 1;

    const style = vehicle.colour ? { color: vehicle.colour } : {};
    // Not interactive: the trail carries no popup of its own, and it is drawn
    // over the stops, so a clickable trail would swallow clicks on a stop
    // underneath it.
    L.polyline(points, { weight: 3, interactive: false, ...style }).addTo(layers.trails);
    L.marker(points[points.length - 1], { icon: busIcon(vehicle), pane: 'buses', keyboard: false })
      .bindPopup(`${vehicle.name ?? vehicle.vehicle_id} — ${vehicle.count} positions`)
      .addTo(layers.trails);

    bounds.extend(points);
  }

  if (drawn > 0 && fit) fitTo(bounds);
  return drawn;
}

// A hidden map measures 0x0, and fitting to that zooms all the way in, so a
// fit made while the map is hidden waits for showMap().
//
// While focusOnCampus is set, this ignores whatever bounds the caller passed
// (the fleet's actual positions) and frames the campus instead -- the single
// choke point every fit (live poll, selection change, tab switch) goes
// through, so the override can't be missed from some other call site.
function fitTo(bounds) {
  const target = focusOnCampus && campusBounds ? campusBounds : bounds;
  if (map.getContainer().clientWidth === 0) {
    pendingFit = target;
    return;
  }
  pendingFit = null;
  map.fitBounds(target, { padding: [24, 24] });
}

// The configured stops' extent (js/stops.js:init()). Recomputed whenever the
// stop list loads; if focusOnCampus was already switched on by then (a slow
// network, a fast tab click), frames it immediately rather than waiting for
// the next unrelated fit.
function setCampusBounds(stops) {
  campusBounds = stops.length ? L.latLngBounds(stops.map((stop) => [stop.latitude, stop.longitude])) : null;
  if (focusOnCampus && campusBounds) fitTo(campusBounds);
}

// Enter/leave the Rider tab's campus-only framing (js/panels.js). Fits
// immediately on enabling, rather than waiting for the next position poll to
// happen to trigger one -- which, if the rider's selection hadn't actually
// changed, might not come at all.
function setCampusFocus(enabled) {
  focusOnCampus = enabled;
  if (enabled && campusBounds) fitTo(campusBounds);
}

// Call when the map becomes visible again: it re-measures the container,
// which may have been resized while hidden, then applies any waiting fit.
function showMap() {
  map.invalidateSize();
  if (pendingFit) fitTo(pendingFit);
}
