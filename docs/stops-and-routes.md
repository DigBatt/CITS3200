# Stops and routes config

The format of `config/stops.yaml`.

Stops and routes are configuration. The backend loads it at startup and serves
it through the API ([api.md](api.md)).

---

## 1. Format

YAML, like `config/app.yaml` and `config/vehicles.yaml`. Two top level keys,
`stops` and `routes`, both lists.

```yaml
stops:
  - id: reid-library
    name: Reid Library
    latitude: -31.97901221771226
    longitude: 115.8183554056777

  - id: civ-mech
    name: Outside Civil and Mechanical Engineering
    latitude: -31.980743857374474
    longitude: 115.81720535774184

  - id: business-school
    name: Outside the Business School
    latitude: -31.985583444723204
    longitude: 115.82089500479223

routes:
  - id: campus-loop
    name: Campus loop
    colour: "#d4741f"
    loop: true
    stops: [reid-library, civ-mech, business-school]
```

---

## 2. Stop

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | text | yes | Permanent identifier. Unique among stops. See 4. |
| `name` | text | yes | What riders and operators read. Free to change. |
| `latitude` | real, WGS84 | yes | Decimal degrees, -90 to 90. |
| `longitude` | real, WGS84 | yes | Decimal degrees, -180 to 180. |

`latitude` and `longitude` are spelled out to match `positions`
([data-schema.md](data-schema.md)).

A stop need not be on any route. It is still served and drawn, so a stop can
be added before the route that uses it.

---

## 3. Route

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | text | yes | Permanent identifier. Unique among routes. See 4. |
| `name` | text | yes | Shown in the route selector and the operator view. |
| `stops` | list of stop ids | yes | The stops in the order the shuttle serves them. At least one. |
| `colour` | text, `#rrggbb` | no | Highlight colour on the map. The frontend picks one if absent. |
| `loop` | boolean | no, default `false` | `true` if the shuttle returns from the last stop to the first. |

- **Order matters.** `stops` is the service order, and the operator view (S09)
  shows it as given.
- **A stop may be on any number of routes.** List its id in each. Which routes
  a stop belongs to is worked out from the routes, and never written on the
  stop itself, so the two cannot disagree.
- **A stop appears at most once in a route.** A loop is marked with
  `loop: true`, not by repeating the first stop at the end.

---

## 4. Ids

Rider requests (S08) are stored against a stop id, and the operator view
(S09) matches requests to routes by id. Changing an id cuts a stop off from
its history.

- Rename a stop by changing `name`, never `id`.
- Never reuse the id of a removed stop.
- Ids are lowercase words joined by hyphens (`reid-library`). Always read as
  text, so `1` and `"1"` are the same id, as with vehicle ids.

---

## 5. Validation

The file is checked when the application starts. If anything is wrong the
application does not start, and the error lists every bad entry.

```
config/stops.yaml: stops[1] (id 'civ-mech'): latitude must be a number between -90 and 90, got 'abc'
config/stops.yaml: routes[0] (id 'campus-loop'): stop 'reid-libary' is not a configured stop
```

Rejected:

- A missing or empty required field.
- An id that is not lowercase words joined by hyphens.
- A duplicate stop id, or a duplicate route id.
- A coordinate that is not a number, or out of range. `true`/`false` are not
  numbers.
- A coordinate outside `logger.bounds` in `config/app.yaml`. This catches
  latitude and longitude written the wrong way round.
- A route with no stops, naming a stop that is not configured, or naming the
  same stop twice.
- A `colour` that is not `#rrggbb`.
- An unknown key, which is almost always a typo (`lat`, `stop`).

Allowed, with a warning in the log:

- A stop on no route.

---

## 6. Changing stops and routes

1. Edit `config/stops.yaml`.
2. Restart the application.

---
