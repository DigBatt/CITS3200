# nUWAy Fleet Dashboard

A single dashboard for the UWA REV Project's nUWAy autonomous shuttle fleet.

Replaces the existing per vehicle page at `revproject.com/vehicles/nuway.php`,
which shows a live snapshot only and overwrites positions week by week.

CITS3200 Group 11.

## Local setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m backend.app              # http://127.0.0.1:5000
```

The dashboard runs on the committed sample data with no client access and no
further setup. None of it is a live feed, and only one of the two sample
files contains real measurements, see [data/README.md](data/README.md).

## Layout

```
config/      vehicle identity and app settings.
docs/        the API contract, the database schema, notes on the source data
data/        committed sample data.
backend/     Flask app, storage behind an interface, API blueprints.
frontend/    Leaflet dashboard.
drafts/      Sprint 1 prototypes, reference only so not part of the build.
GPS_Report/  client supplied telemetry and ROS 2 sample nodes.
```

## Combined dashboard UI

The `frontend/` in this package combines the real Map project telemetry with the
visual language of the nUWAy prototype. The Map project remains the application
base: Flask, the CSV repository, vehicle configuration, and the position API are
used directly.

Implemented in this combined build:

- Fleet / Operator / Rider / Utilisation navigation in the nUWAy prototype style.
- Existing recorded GPS tracks and last-position markers on Leaflet.
- Vehicle filtering backed by `?vehicles=` rather than visual-only filtering.
- Live repository / Today / Calendar filtering. Calendar dates are interpreted
  as Australia/Perth days by the API.
- `GET /api/vehicles` for configured fleet identity and latest telemetry state.
- Operator telemetry fields populated only when the position schema provides them.
- Telemetry-derived diagnostics in Utilisation (samples, recorded intervals,
  moving share, track distance and GPS fix rate).

Data deliberately not fabricated:

- engage/disengage events (`/api/events` is still not implemented),
- formal GMG Time Usage Model / availability / utilisation metrics
  (`/api/metrics` is still not implemented),
- operator identity, occupancy and passenger counts,
- stops, routes, ETAs and rider stop requests (`POST /api/stop-requests` is not
  implemented and the Map project contains no stop definition).

Those surfaces remain present so the future feeds can be wired into the UI
without another redesign.
