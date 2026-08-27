// Leaflet setup: map init, tile layer, and one layer group per overlay.
//
// Layer groups map one-to-one onto the overlays.
// 
// Owns: vehicle markers, position trails, event markers.
// Knows nothing about fetching it is handed data and draws it.
//
// Skip positions with a null latitude/longitude when building polyline
// geometry.
//
