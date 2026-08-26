//  Owns the current selection state and nothing else.
//
//   selection = { vehicleIds, from, to, showEvents, showTrails }
//
// On change: fetch through api.js, hand the result to map.js, update the
// status line. When every selected vehicle comes back with count 0.
// 
//
// Live refresh polls /api/vehicles on the interval from /api/config so markers
// move without a page reload.
// 
