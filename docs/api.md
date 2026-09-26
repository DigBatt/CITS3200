# JSON API

## Conventions

**Vehicle selection.** `?vehicles=1,2` selects a subset; omitting the parameter
means the whole fleet. Ids are strings.

**Empty is not an error.** A valid query that matches no data returns `200` with
empty arrays. It never returns `404`. S06 requires the dashboard to say that there is no data for this day rather than show an empty map.

**Errors.** `400` for a malformed or unsatisfiable parameter, `500` for a fault.
Always shaped:

```json
{ "error": { "code": "unknown_vehicle", "message": "No vehicle with id '9'. Known ids: 1, 2." } }
```

Codes: `bad_timestamp`, `bad_range` (from > to), `unknown_vehicle`,
`unknown_stop`, `unknown_route`, `data_unavailable`.

---

## `GET /api/vehicles`

The fleet, its identity and its current state. Serves S02, S04 and S08.

Liveness is computed server side from `config/app.yaml`. 

```json
{
  "generated_at": "2025-09-04T08:59:00Z",
  "inactivity_threshold_seconds": 300,
  "vehicles": [
    {
      "id": "1",
      "name": "nUWAy 1",
      "colour": "#d4741f",
      "status": "active",
      "last_seen": "2025-09-04T08:58:37.495682Z",
      "seconds_since_last_seen": 22.5,
      "last_position": {
        "vehicle_id": "1",
        "timestamp": "2025-09-04T08:58:37.495682Z",
        "latitude": -31.9813310950,
        "longitude": 115.8159720100,
        "altitude_m": -20.552,
        "heading_deg": 54.39,
        "speed_mps": 0.0,
        "gps_status": 0,
        "battery_percent": null
      }
    },
    {
      "id": "3",
      "name": "nUWAy 3",
      "colour": "#7a5ea8",
      "status": "inactive",
      "last_seen": null,
      "seconds_since_last_seen": null,
      "last_position": null
    }
  ]
}
```

`status` is `active` | `inactive`. A vehicle configured but with no telemetry at
all is `inactive` with a `null` position.

`inactivity_threshold_seconds` is echoed.

---

## `GET /api/positions`

Stored positions for a selection and a period. Serves S01, S05, S06 and S07.

| Parameter | Required | Notes |
|---|---|---|
| `vehicles` | no | Comma-separated ids. Default: all. |
| `from` | no | Default: start of today, Perth time. |
| `to` | no | Default: now. |

Grouped by vehicle.

```json
{
  "from": "2025-09-03T16:00:00Z",
  "to": "2025-09-04T15:59:59.999999Z",
  "vehicles": [
    {
      "vehicle_id": "1",
      "name": "nUWAy 1",
      "colour": "#d4741f",
      "count": 439,
      "positions": [ { "timestamp": "...", "latitude": -31.98, "longitude": 115.81, "…": null } ]
    }
  ]
}
```

Positions are ascending by timestamp. Rows with `gps_status: -1` are included,
with `latitude` and `longitude` `null`.

A selected vehicle with nothing in range appears with `"count": 0` and an empty
array.

---

## `GET /api/events`

Engage/disengage events, not implemented yet.
I dont know the format of the data we get here yet, so this is mostly a placeholder/idea for now.

---

## `GET /api/metrics`

This will be for utilisation figures. Not implemented yet.

---

## Stops and routes

From `config/stops.yaml` ([stops-and-routes.md](stops-and-routes.md)).

A stop or route id in the path that is not configured is `404`, codes
`unknown_stop` and `unknown_route`. The no-`404` rule above is about queries
that match no data, not about naming something that does not exist.

### `GET /api/stops`

Every stop, in file order, each with the ids of the routes it is on.

```json
{
  "stops": [
    {
      "id": "reid-library",
      "name": "Reid Library",
      "latitude": -31.97901221771226,
      "longitude": 115.8183554056777,
      "routes": ["campus-loop"]
    }
  ]
}
```

`routes` is in file order and is `[]` for a stop on no route.

### `GET /api/stops/<id>`

One stop, the same shape as an entry above.

### `GET /api/routes`

Every route, in file order, with its stop ids in service order.

```json
{
  "routes": [
    {
      "id": "campus-loop",
      "name": "Campus loop",
      "colour": "#d4741f",
      "loop": true,
      "stop_ids": ["reid-library", "civ-mech", "business-school"]
    }
  ]
}
```

`colour` is `null` when the config does not set one.

### `GET /api/routes/<id>`

One route, with its stops in full and in service order.

```json
{
  "id": "campus-loop",
  "name": "Campus loop",
  "colour": "#d4741f",
  "loop": true,
  "stops": [
    { "id": "reid-library", "name": "Reid Library", "latitude": -31.97901221771226, "longitude": 115.8183554056777, "routes": ["campus-loop"] }
  ]
}
```

---

## Pickup requests

S08. A rider asks to be collected at a stop, no account needed.

**Identifying a rider (S08.2).** No login exists, the server
generates a random `rider_token` and sets it as an http only cookie
(`SameSite=Lax`, ~1 year) the first time a browser posts a request; every
later request from that browser carries it automatically. It never appears in
a JSON body, and the operator view never sees another rider's token.

### `POST /api/pickup-requests`

```json
{ "stop_id": "reid-library" }
```

`400` `unknown_stop` if the stop is not configured — this is a bad request
body, not a path lookup, so it does not follow the `404` convention `/api/stops/<id>`
uses.

If the rider (by cookie) already has an open request at that stop, that same
request is returned unchanged with `200` instead of opening a second one. A
genuinely new request is `201`.

```json
{
  "request": {
    "id": "3f1c2b7a9e4d4f0b8c6a1d2e3f4a5b6c",
    "stop_id": "reid-library",
    "status": "open",
    "created_at": "2025-09-04T08:58:37.495682Z",
    "cleared_at": null
  }
}
```

### `GET /api/pickup-requests`

Every pickup request, ascending by `created_at`. For the operator view to
poll so a bus doesn't skip a stop with a rider waiting.

| Parameter | Required | Notes |
|---|---|---|
| `status` | no | One of `open`, `collected`, `expired`. Default: all. |

```json
{ "requests": [ { "...": "as in POST above" } ] }
```

A request leaves `open` once: `collected` when the operator clears its
stop, or `expired` when it has been open longer than
`pickup_requests.expire_after_seconds` in `config/app.yaml`. Either way the
record is kept with `cleared_at` set, so `?status=collected` and
`?status=expired` are the admin's record of the day. Expiry is applied when
requests are read or opened, not by a background job.

The store is in memory, so a restart clears every request, open or closed.

### `GET /api/routes/<id>/waiting`

S09.2. The riders waiting along one route, for the operator view to poll
(`/admin`, Operator view tab, every 10 s). `404` `unknown_route` if the route
is not configured.

The route's stops in service order, each with the number of `open` requests
and the age of the oldest. Stops with nobody waiting have `waiting: 0` and
nulls. Requests at stops not on the route are left out, and do not count
toward `total_waiting`.

```json
{
  "generated_at": "2025-09-04T09:00:00.000000Z",
  "route": { "id": "campus-loop", "name": "Campus loop", "colour": "#d4741f", "loop": true },
  "total_waiting": 2,
  "stops": [
    {
      "id": "reid-library", "name": "Reid Library", "latitude": -31.979, "longitude": 115.818,
      "waiting": 2,
      "oldest_requested_at": "2025-09-04T08:53:12.000000Z",
      "oldest_wait_seconds": 408.0
    },
    {
      "id": "civ-mech", "name": "Outside Civil and Mechanical Engineering", "latitude": -31.981, "longitude": 115.817,
      "waiting": 0, "oldest_requested_at": null, "oldest_wait_seconds": null
    }
  ]
}
```

**Which route a vehicle is on (S09.1).** The operator picks their vehicle and
route when the page loads. The choice lives in the page URL
(`/admin?vehicle=1&route=campus-loop`) and the browser's local storage; the
server holds no assignment. The vehicle's position comes from
`GET /api/vehicles`: live when the logger is feeding it, otherwise the latest
recorded position, labelled with its age.

### `POST /api/stops/<id>/collect`

The operator has picked up the riders at a stop. Every `open` request at
the stop becomes `collected`, whichever route the rider was waiting for, since
requests belong to a stop and not a route. No body. `404` `unknown_stop` if the
stop is not configured.

Returns the requests closed, empty if nobody was waiting:

```json
{ "collected": [ { "...": "as in POST /api/pickup-requests, with status collected and cleared_at set" } ] }
```

A rider who asks again at the same stop afterwards opens a new request.

---

## Not implemented yet

The rider-facing stop picker page (S08.4). Pickup requests that survive a
restart.
