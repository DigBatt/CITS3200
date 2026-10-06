# Database schema


## What this document does not cover

How records get in, whatever the shuttles or the REV webserver eventually
push, in whatever format, reaches this database through a separate ingest
mapping that is not specified here and is not built this sprint. The writer is
modelled as external.

---

## 1. Entities

| Entity | Where it lives | Why |
|---|---|---|
| Vehicle | `config/vehicles.yaml` | Not a table. S02 requires the identity scheme to be held as configuration rather than in code, and FR-12 requires a new shuttle to need no code change. |
| Position | `positions` | One telemetry sample for one vehicle at one instant. |
| Stop, Route | `config/stops.json` | Not tables. Stops to be added or moved without a code change. Format: [stops-and-routes.md](stops-and-routes.md). |

---

## 2. `positions`

### 2.1 Fields

| Field | Type | Null | Meaning |
|---|---|---|---|
| `vehicle_id` | text | no | Matches an `id` in `config/vehicles.yaml`. |
| `timestamp` | ISO 8601, UTC, `Z` | no | When the sample was taken. |
| `latitude` | real, WGS84 | yes | Null when the receiver had no fix. |
| `longitude` | real, WGS84 | yes | Null when the receiver had no fix. |
| `altitude_m` | real, metres | yes | |
| `heading_deg` | real, degrees | yes | |
| `speed_mps` | real, m/s | yes | |
| `gps_status` | integer | yes | `-1` no fix, `0` fix, `1` SBAS, `2` GBAS (`sensor_msgs/NavSatStatus`). |
| `battery_percent` | real, 0–100 | yes | |

### 2.2 Key and ordering

Primary key: **(`vehicle_id`, `timestamp`)**.

Reads are always ordered ascending by `timestamp` within a vehicle.

### 2.3 Nullability

Everything but vehicle, time and status is nullable, and that is a deliberate
constraint, as we can model it on the dashboard as unknown.

---

## 3. Time

- Stored **UTC**, always, with an explicit `Z`. No local times in the database.
- Displayed in **Australia/Perth**. UTC+8 year round.
- A bare date in a query means that whole day in Perth time; a user
  picking a day from a calendar means their day. `2025-09-04` expands to
  `2025-09-03T16:00:00Z .. 2025-09-04T15:59:59.999999Z`.
- Sub-second precision is preserved. The recorded data has microseconds and
  truncating to whole seconds collides rows.

---
