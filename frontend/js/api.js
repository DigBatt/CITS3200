// knows endpoint URLs.
//
//   getConfig()                        GET /api/config
//   getVehicles()                      GET /api/vehicles
//   getPositions(ids, from, to)        GET /api/positions
//   getEvents(ids, from, to)           GET /api/events
//   getMetrics(ids, from, to)          GET /api/metrics
//
// Contract in docs/api.md.
//   - an empty result is 200 with empty arrays, not an error; callers must be
//     able to tell an empty req from a malformed req.
//   - an error body is {error: {code, message}}; surface the message.
//

