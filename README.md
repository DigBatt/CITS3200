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
