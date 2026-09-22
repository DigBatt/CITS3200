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
`data_unavailable`, `bad_request` (malformed body), `invalid_record`
(a field the store refuses), `invalid_schedule`, `not_found`.

`not_found` is the one exception to "empty is not an error": it answers a
write aimed at a record id that does not exist, which is not a query that
matched nothing.

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

## `GET /api/downtime`

The downtime log for a selection and, optionally, a period. Serves S18-S20.

Operator reported out of service periods. Downtime is the one bucket of the
time usage model the telemetry cannot supply (see `docs/GMG Time Utilisation
Model.md`), so these are entered by hand on the admin page.

Unlike the other read endpoints, `from` and `to` are **not** defaulted to
today: the admin page lists the whole log. Omit them for everything. When
given, a record is returned if it *overlaps* the window, so one that began
before `from` and was still open at `from` is included.

```json
{
  "from": null,
  "to": null,
  "records": [
    {
      "id": "ffaf720d7ac7456fa369593ad7969b91",
      "vehicle_id": "1",
      "start": "2026-09-17T01:00:00.000000Z",
      "end": "2026-09-17T03:00:00.000000Z",
      "reason": "Brake fault",
      "created_at": "2026-09-17T04:12:09.114000Z",
      "updated_at": "2026-09-17T04:12:09.114000Z"
    }
  ]
}
```

Records are ascending by `start`. Times are stored and returned in UTC; the
admin page converts to and from local time at the form.

> **Not yet protected.** The three writes below are the first write endpoints
> in the app and admin auth (S13) does not exist, so anyone who can reach the
> server can edit the log. S13 must guard them before this is exposed beyond
> a local run.

---

## `POST /api/downtime`

Stores a new record. All four fields are required.

```json
{ "vehicle_id": "1", "start": "2026-09-17T01:00:00Z", "end": "2026-09-17T03:00:00Z", "reason": "Brake fault" }
```

`201` with the stored record and any periods it clashes with:

```json
{
  "record": {
    "id": "ffaf720d7ac7456fa369593ad7969b91",
    "vehicle_id": "1",
    "start": "2026-09-17T01:00:00.000000Z",
    "end": "2026-09-17T03:00:00.000000Z",
    "reason": "Brake fault",
    "created_at": "2026-09-17T04:12:09.114000Z",
    "updated_at": "2026-09-17T04:12:09.114000Z"
  },
  "overlaps": []
}
```

**Overlaps warn, they do not reject.** A non empty `overlaps` means the record
was stored *and* intersects the ones listed. A vehicle can genuinely have two
faults logged over one period, so the admin page shows a warning rather than
refusing the save. Periods are half open, so two that merely touch do not
overlap.

`400` for a missing field, an unparseable time, an `end` at or before `start`
(`bad_range`), an empty reason (`invalid_record`), or an unknown vehicle.

---

## `PATCH /api/downtime/<id>`

Changes a stored record. Send only the fields that change; the rest are left
as they are. Answers `200` in the same shape as `POST`, or `404` with
`not_found`.

---

## `DELETE /api/downtime/<id>`

Removes a record. `204` with no body, or `404` with `not_found`. Deleting
twice is a `404`, so the page can tell a stale row from a removed one.

---

## `GET /api/schedule`

The shuttle service schedule. Serves S21.

When the fleet is rostered to run, which is what lets the time usage model
tell scheduled service time apart from everything else. Source of truth is
`utilisation.service_hours` in `config/app.yaml`, so a schedule change is a
config change: the figures recalculate with no code change.

**Public, and staying public.** The dashboard shows scheduled time to anyone,
so anyone may read the roster behind it. Only the `PUT` below is privileged.

```json
{
  "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
  "timezone": "Australia/Perth",
  "configured": true,
  "vehicles": [{ "id": "1", "name": "nUWAy 1", "colour": "#d4741f" }],
  "schedule": {
    "monday": [
      { "start": "08:00", "end": "12:00", "vehicles": null },
      { "start": "13:00", "end": "17:00", "vehicles": ["1", "2"] }
    ],
    "saturday": [{ "start": "09:00", "end": "13:00", "vehicles": ["3"] }],
    "sunday": []
  }
}
```

Every day is present, so a client need not know which were omitted. A day with
an empty list is not in service. Times are local wall clock in `timezone`,
because a roster is written in local time.

**Rosters are per vehicle.** A period's `vehicles` names who it is for;
`null` means the whole fleet, now and any vehicle added later. `vehicles` at
the top level is the fleet a period may name, so an editor needs no second
request.

Two periods may overlap when they are for different vehicles, which is the
point: one bus can run a late shift while another runs mornings. Two periods
that could apply to the *same* vehicle may not overlap, since that would count
its scheduled time twice.

`/api/metrics` follows the same rule: `scheduled_seconds` is computed from the
periods that apply to that vehicle, so two buses over one window can have
different scheduled time.

`configured` is false when no day has any period. That is a valid state, not an
error: nothing rostered means no scheduled time, and `/api/metrics` reports the
whole window as unscheduled with a note saying why. See **Empty schedules**.

---

## `PUT /api/schedule`

Replaces the whole schedule. The roster is sent in one piece rather than a row
at a time, because it is written back into a config file: one read, one
validated write, no half applied edit.

```json
{
  "monday": [{ "start": "08:00", "end": "17:00" }],
  "saturday": [{ "start": "09:00", "end": "13:00", "vehicles": ["3"] }]
}
```

A day that is absent or empty has no service, and a period with no `vehicles`
(or an empty list) is for the whole fleet. `200` with the stored schedule, in
the same shape as `GET`.

The older `[["08:00", "17:00"]]` pair form is still accepted on read, and on
the `weekday`/`weekend` keys of the original config, so an app.yaml from
before this change keeps working. Everything from those forms is fleet wide.

Only the `service_hours` block of `app.yaml` is rewritten; the rest of the
file, its ordering and its comments, is left byte for byte as it was. The
result is parsed and compared against what was asked for before it replaces
anything, and the swap is atomic, so a failed write leaves the file intact.

`400` with `invalid_schedule` for an unknown day, a malformed time, a period
that does not end after it starts, or two periods for the same vehicle that
overlap. `400` with `unknown_vehicle` if a period names a vehicle the fleet
does not have.

A period crossing midnight cannot be expressed and is rejected; it needs a row
on each day.

> **Not yet protected.** Editing the roster is an operator and administrator
> action, but admin auth (S13) does not exist, so this `PUT` is open like the
> `/api/downtime` writes. The guard belongs on `replace_schedule` in
> `backend/api/schedule.py`, which is the only write in that module. `GET`
> stays open.

---

### Empty schedules

With no schedule in the system, `/api/metrics` answers with real figures and
explains them, rather than erroring or blocking the bucket:

```json
{
  "buckets": { "scheduled_seconds": 0, "unscheduled_seconds": 86400 },
  "notes": { "scheduled_seconds": "No service schedule is in the system, so all time counts as unscheduled." }
}
```

A vehicle nobody rostered gets the same treatment while the rest of the fleet
has a timetable, with a note naming it as the vehicle's own gap: *"No service
schedule is in the system for this vehicle, so all its time counts as
unscheduled."*

`notes` is new alongside `unavailable`: `unavailable` explains a figure that is
`null`, `notes` explains one that is real but needs saying. The dashboard shows
the note as the caption on the scheduled row.

A timezone is still required. Without `display.timezone` a local roster cannot
be placed on a clock, so `scheduled_seconds` is `null` with an `unavailable`
reason, which is a broken config rather than an empty schedule.

---

## Not in this sprint

`POST /api/stop-requests`.
