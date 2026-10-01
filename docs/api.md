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
`unknown_stop`, `unknown_route`, `unknown_request`, `not_your_request`,
`request_not_open`, `data_unavailable`, `not_signed_in`, `bad_credentials`,
`admin_not_configured`, `missing_field`, `overlap`, `unknown_downtime`.

**Signing in.** Endpoints marked *Admin only* answer `401` `not_signed_in`
until the browser has signed in through `POST /api/admin/login` (see
[Administrator sign-in](#administrator-sign-in)). Everything else, including
everything the rider view uses, needs no sign-in.

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

## `GET /api/metrics`

Utilisation figures from the GMG time utilisation model
([GMG Time Utilisation Model.md](GMG%20Time%20Utilisation%20Model.md)), per
vehicle over a window. Backs the Utilisation view.

| Parameter | Required | Notes |
|---|---|---|
| `vehicles` | no | As for `/api/positions`. Default: all. |
| `from` | no | As for `/api/positions`. Default: start of today, Perth time. |
| `to` | no | As for `/api/positions`. Default: now. |

One entry per selected vehicle, in config order. Every `buckets` value is in
seconds, every `kpis` value a fraction from 0 to 1.

```json
{
  "from": "2025-09-03T16:00:00.000000Z",
  "to": "2025-09-04T15:59:59.999999Z",
  "vehicles": [
    {
      "vehicle_id": "1",
      "from": "2025-09-03T16:00:00.000000Z",
      "to": "2025-09-04T15:59:59.999999Z",
      "buckets": {
        "calendar_seconds": 86399.999999,
        "working_seconds": 2164.54,
        "operating_delay_seconds": 82.47,
        "standby_seconds": 0.0,
        "not_reporting_seconds": 84152.99,
        "operating_seconds": 2247.01,
        "scheduled_seconds": 32400.0,
        "scheduled_working_seconds": 2164.54,
        "unscheduled_seconds": 54000.0,
        "downtime_seconds": null,
        "available_seconds": null,
        "productive_seconds": null
      },
      "kpis": {
        "asset_utilisation": 0.026,
        "operating_efficiency": 0.963,
        "effective_utilisation": 0.067,
        "uptime": null,
        "mechanical_availability": null,
        "physical_availability": null,
        "use_of_availability": null,
        "production_effectiveness": null
      },
      "unavailable": {
        "uptime": "needs downtime; no fault or maintenance log in the data",
        "...": "one entry per null above, saying why"
      }
    }
  ]
}
```

A bucket or KPI the data cannot support is `null`, and `unavailable` names it
with the reason. `operating_efficiency` is `null` for a window with no
operating time. `effective_utilisation` and the `scheduled_*` buckets need
`utilisation.service_hours`, and `standby_seconds` needs `utilisation.depot`,
both in `config/app.yaml`; without a depot, stopped time counts as operating
delay.

`400` as for `/api/positions`. `500` `data_unavailable` if a required
`utilisation` threshold is unset in `config/app.yaml`.

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

*Admin only.*

Every pickup request, ascending by `created_at`. For the operator view to
poll so a bus doesn't skip a stop with a rider waiting.

| Parameter | Required | Notes |
|---|---|---|
| `status` | no | One of `open`, `collected`, `expired`. Default: all. |

```json
{ "requests": [ { "...": "as in POST above" } ] }
```

A request leaves `open` once: `collected` when the operator clears its
stop, `expired` when it has been open longer than
`pickup_requests.expire_after_seconds` in `config/app.yaml`, or `cancelled`
when the rider withdraws it themselves (`POST /api/pickup-requests/<id>/cancel`
below). Either way the record is kept with `cleared_at` set, so
`?status=collected` and `?status=expired` are the admin's record of the day.
Expiry is applied when requests are read or opened, not by a background job.

The store is in memory, so a restart clears every request, open or closed.

### `GET /api/pickup-requests/mine`

S15. The calling rider's own most recent request, any status, identified by
the `rider_token` cookie — not admin-only, since it only ever answers with
the caller's own request. Backs the rider view polling to notice its own
request going `collected` (to show a "leave a review" prompt) or `expired`.

```json
{ "request": { "...": "as in POST above" } }
```

`{"request": null}` if this rider has no `rider_token` cookie yet, or has
never made a request — not an error, since that is the normal state before a
rider's first request.

### `POST /api/pickup-requests/<id>/cancel`

S15. The rider withdraws their own request. No body. Ownership is the same
`rider_token` cookie POST /api/pickup-requests uses, so no sign-in is needed,
but a rider cannot cancel someone else's request.

`404` `unknown_request` if the id is not on record. `403` `not_your_request`
if the caller's cookie does not match the request's rider. `409`
`request_not_open` if it has already been collected, expired, or cancelled.
Otherwise `200`:

```json
{ "request": { "...": "as in POST above, with status cancelled and cleared_at set" } }
```

A rider who asks again at the same stop afterwards opens a new request, the
same as after being collected.

### `GET /api/routes/<id>/waiting`

*Admin only.*

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

*Admin only.*

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

## Downtime

S18-S20. *Admin only.* When a shuttle was out of service.

Records are kept in `downtime.json` under `storage.directory` in
`config/app.yaml` (`data/admin` by default). The
file is read on every request and replaced in one step on every change. Run a
single server process: two saves at the same instant from two processes
could lose one of them. If `storage.directory` is unset, or the file cannot
be read, every endpoint answers `500` `data_unavailable`.

A record:

```json
{
  "id": "07ab4afdd1f84414b3616752b1d936e7",
  "vehicle_id": "1",
  "start": "2026-10-01T01:00:00.000000Z",
  "end": "2026-10-01T03:00:00.000000Z",
  "reason": "Scheduled maintenance",
  "created_at": "2026-10-01T04:12:09.512330Z",
  "updated_at": "2026-10-01T04:12:09.512330Z"
}
```

### `GET /api/downtime`

Records ascending by `start`.

| Parameter | Required | Notes |
|---|---|---|
| `vehicles` | no | As for `/api/positions`. Default: every record, including any for a vehicle no longer configured. |
| `from`, `to` | no | As for `/api/positions`. Only records overlapping the window. Default: unbounded. |

```json
{ "records": [ { "...": "a record" } ] }
```

### `POST /api/downtime`

```json
{
  "vehicle_id": "1",
  "start": "2026-10-01T09:00:00+08:00",
  "end": "2026-10-01T11:00:00+08:00",
  "reason": "Scheduled maintenance",
  "confirm": false
}
```

`start` and `end` must carry a timezone (`Z` or an offset), and are stored
in UTC. `201` `{ "record": { ... } }`.

`400`: `missing_field` (vehicle, start, end or a non-blank reason),
`unknown_vehicle`, `bad_timestamp`, or `bad_range` if `end` is not after
`start` (S18.3).

`409` `overlap` if the period overlaps one of this vehicle's existing records.
 Nothing is stored. The clashing records
come back beside the error; resend with `"confirm": true` to store it anyway.
Periods that only touch, one ending as the next starts, do not overlap.

```json
{
  "error": { "code": "overlap", "message": "This period overlaps 1 existing downtime record for vehicle 1. ..." },
  "overlaps": [ { "...": "a record" } ]
}
```

### `PATCH /api/downtime/<id>`

S20. Body as for `POST`; fields left out keep their current values. `200`
`{ "record": { ... } }`, `404` `unknown_downtime`, and the same `400` and
`409` as `POST`. The record does not clash with itself, and an edit that
leaves the vehicle and times unchanged is not checked for overlap again.

### `DELETE /api/downtime/<id>`

S20. `204`, or `404` `unknown_downtime`.

---

## Administrator sign-in

S13. One shared account, set in a `config/secrets.yaml` (copy
`config/secrets.example.yaml`). Signing in sets a flag in Flask's signed
session cookie (`HttpOnly`, `SameSite=Lax`), which lasts
`admin.session_hours` in `config/app.yaml`.

Admin only: the `/admin` page, `GET /api/pickup-requests`,
`GET /api/routes/<id>/waiting`, `POST /api/stops/<id>/collect` and every
`/api/downtime` endpoint. A
signed-out request for `/admin` is redirected to
`/admin-login?next=<the page asked for>`, which returns there after signing in.

**Limits.** One account shared by every operator and administrator, so anyone
who can use the operator view can also change downtime and snapshot settings.
There is no lockout after repeated wrong passwords, and the site must be
served over HTTPS for the cookie and password to be safe in transit.

### `POST /api/admin/login`

```json
{ "username": "admin", "password": "..." }
```

`200` `{ "signed_in": true }` and the session cookie. `401` `bad_credentials`
for a wrong or missing username or password. `503` `admin_not_configured` if
there is no `config/secrets.yaml`.

### `POST /api/admin/logout`

Ends the session. Always `200` `{ "signed_in": false }`.

### `GET /api/admin/me`

`200` `{ "signed_in": true | false }`. Never `401`, so the admin page can check
without tripping its own signed-out handling.
