# Stops and routes config

The format of `config/stops.json`.

JSON, written by the admin page's route editor and readable by any tool. An
older config with only `config/stops.yaml`, in the same shape, is still read;
the editor's first save replaces it with `stops.json`. With both files the
application refuses to start, so an edit to the old file (a merge from an
older branch, say) is never silently ignored: move it across and delete
`stops.yaml`.

Stops and routes are configuration. The backend loads it at startup and serves
it through the API ([api.md](api.md)).

---

## 1. Format

JSON. Two top level keys, `stops` and `routes`, both lists.

```json
{
  "stops": [
    { "id": "reid-library", "name": "Reid Library", "latitude": -31.97901221771226, "longitude": 115.8183554056777 },
    { "id": "civ-mech", "name": "Outside Civil and Mechanical Engineering", "latitude": -31.980743857374474, "longitude": 115.81720535774184 },
    { "id": "business-school", "name": "Outside the Business School", "latitude": -31.985583444723204, "longitude": 115.82089500479223 }
  ],
  "routes": [
    { "id": "campus-loop", "name": "Campus loop", "colour": "#d4741f", "loop": true,
      "stops": ["reid-library", "civ-mech", "business-school"] }
  ]
}
```

---

## 2. Stop

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | text | yes | Permanent identifier. Unique among stops. See 4. |
| `name` | text | yes | What riders and operators read. Free to change. |
| `latitude` | real, WGS84 | yes | Decimal degrees, -90 to 90. |
| `longitude` | real, WGS84 | yes | Decimal degrees, -180 to 180. |
| `snap` | boolean | no, default `true` | Route editor only: `false` when the stop was placed off the campus paths on purpose, so dragging it does not pull it back on. Changes no path. Written only when `false`. |

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
| `stops` | list of stop ids | yes, unless `points` is given | The stops in the order the shuttle serves them. At least one. With `points`, a summary of the stops in it, which must match. |
| `points` | list of points | no | The route in full: its stops and the guide points between them, in order. See 3.1. |
| `colour` | text, `#rrggbb` | no | Highlight colour on the map. The frontend picks one if absent. |
| `loop` | boolean | no, default `false` | `true` if the shuttle returns from the last stop to the first. |

- **Order matters.** `stops` is the service order, and the operator view (S09)
  shows it as given.
- **A stop may be on any number of routes.** List its id in each. Which routes
  a stop belongs to is worked out from the routes, and never written on the
  stop itself, so the two cannot disagree.
- **A stop appears at most once in a route.** A loop is marked with
  `loop: true`, not by repeating the first stop at the end.

### 3.1 Points: the path a route takes

Stops are the network's nodes. A route is a path through them: its
`points`, in order, each a stop or a **guide point** that only shapes the
path and is never a stop.

```json
{
  "id": "lawn-shuttle",
  "name": "Lawn shuttle",
  "loop": false,
  "stops": ["reid-library", "civ-mech"],
  "points": [
    { "stop": "reid-library" },
    { "guide": [-31.9805, 115.8183], "straight": true,
      "path": [[-31.979012, 115.818355], [-31.9805, 115.8183]] },
    { "stop": "civ-mech",
      "path": [[-31.9805, 115.8183], [-31.98051, 115.81721], [-31.980744, 115.817205]] }
  ]
}
```

| Field | Meaning |
|---|---|
| `stop` | A stop id. Its position is the stop's. |
| `guide` | `[latitude, longitude]` of a guide point. |
| `snap` | Guide points only, default `true`: `false` when placed off the paths on purpose, as for a stop's `snap`. A stop's point has none; whether a stop snaps is on the stop, shared by every route. |
| `straight` | The leg *arriving* at this point is a straight line, for a way the map does not have. Otherwise it follows the campus paths (section 8). On the first point of a loop, it is the closing leg's. |
| `path` | The leg arriving at this point, as `[latitude, longitude]` pairs to 6 decimals (about 0.1 m). Worked out on save; absent on the first point of a route that is not a loop. An older `stops.yaml` may hold it as an encoded polyline (`backend/polyline.py`), which is still read. |

- A route that is not a loop must start and end at a stop.
- `path` is derived. It is written so the dashboard draws exactly what the
  editor showed, and is worked out again on load if missing or if its ends no
  longer meet its points (a stop moved by hand).
- A route given only as `stops` is those stops with every leg along the
  paths, so a hand written route still draws.

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
config/stops.json: stops[1] (id 'civ-mech'): latitude must be a number between -90 and 90, got 'abc'
config/stops.json: routes[0] (id 'campus-loop'): stop 'reid-libary' is not a configured stop
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
- A route with `points` and `stops` that disagree, a route that is not a loop
  starting or ending at a guide point, a point that is neither or both of
  `stop` and `guide`, and a `path` that is not a list of coordinate pairs.
- A `colour` that is not `#rrggbb`.
- An unknown key, which is almost always a typo (`lat`, `stop`).

Allowed, with a warning in the log:

- A stop on no route.

---

## 6. Changing stops and routes

**From the admin page.** The **Routes** tab (`frontend/js/route-editor.js`)
places stops and guide points on a map. Saving rewrites this file and applies
at once, with no restart.

- The bar at the top lists every route and stop. Open a route there, or start
  a new one; rename or remove stops there.
- The sidebar lists the open route's points in order. Drag a row (or use the
  arrows) to reorder; switch a point between stop and guide point; switch the
  leg arriving at it between following the paths and drawn straight.
- On the map, a click adds a guide point or a stop (the toggle at the top
  right), snapped onto the nearest path within 25 m when **Snap new points**
  is on.
- Click a point, on the map or in the list, to select it; Escape clears it.
  The selected point has a **Snap to paths** switch. Off, the point can be
  dragged anywhere, such as across a lawn the map has no path over, and shows
  a dashed edge and a **Free** badge. On again, it is pulled onto the nearest
  path within 25 m. A stop's setting is on the stop, so it applies on every
  route; the stop list has the same switch (**Snaps** / **Free**). A free
  point's leg can still follow the paths: it runs straight to the nearest
  one, then along it. A click on a grey stop
  adds that stop. A click on the route's line puts a guide point in that leg.
  Drag any point to move it; moving a stop moves it on every route.
- With no route open, a click on the map adds a stop on no route.
- Double-click a guide point to remove it, or a stop to take it off the open
  route (with no route open, to delete the stop). Double-clicking empty map
  zooms as usual.
- Every edit can be undone until Save: **Ctrl+Z** undoes, **Ctrl+R** (or
  Ctrl+Shift+Z, Ctrl+Y) redoes, Cmd for Ctrl on a Mac, or the Undo and Redo
  buttons on the map. In a text field Ctrl+Z undoes the typing instead. On
  this tab Ctrl+R no longer reloads the page; F5 still does. Saving, Discard
  and reloading start a fresh history.
- A new stop or route gets its id from its name when first saved, and keeps
  it after (section 4).
- A stop riders are waiting at cannot be removed until they are collected.

Saving rewrites the whole file. JSON has no comments, so notes about a stop
belong in its `name` or in this document.

**By hand.** Edit `config/stops.json` and restart. A route may be written as
just `stops`; it gets its points and paths on load.

---

## 7. Planned dotted paths

Selecting a route on the dashboard draws its stored path in the route colour,
dotted, in a pane below stop markers and GPS trails (`frontend/js/map.js`). A
stretch the route passes twice, out along a spur and back, is drawn once.
Selecting another route replaces the path; All routes clears it. The Stops
toggle hides and restores both the path and its markers.

The five original routes were traced from the October 4 route sketches. They
are kept as guide points with straight legs, so they draw as they did; open
one in the editor and switch its legs to follow the paths to re-route it.

---

## 8. The campus path network

`config/campus_paths.json` is a snapshot of the roads and paths around the
stops from OpenStreetMap (`backend/path_network.py`). A leg that is not drawn
straight takes the shortest way along it. It is kept in the repository so
routing works offline and gives the same path every time.

Refresh it when campus paths change, then re-save any route that should pick
the change up:

```sh
python -m backend.path_network refresh
```

It takes footways, paths, cycleways and service and minor roads within 450 m
of the stops, and never steps. Without the file every leg is drawn straight.

Map data © OpenStreetMap contributors, under the Open Database Licence
(https://www.openstreetmap.org/copyright).
