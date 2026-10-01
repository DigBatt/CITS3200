# nUWAy Fleet Dashboard

A single dashboard for the UWA REV Project's nUWAy autonomous shuttle bus fleet.

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

## Admin sign-in

The admin page (`/admin`, which holds the operator view) needs signing in with
one shared account. Its credentials live in `config/secrets.yaml`, which is
git-ignored and must never be committed:

```bash
cp config/secrets.example.yaml config/secrets.yaml
python -c "import secrets; print(secrets.token_hex(32))"     # paste as secret_key
python -c "from werkzeug.security import generate_password_hash as h; print(h(input('Password: ')))"
                                                             # paste as admin.password_hash
```

Without the file the rest of the app still runs; only sign-in is refused.
Limits and details: [docs/api.md](docs/api.md#administrator-sign-in).

## Live data

The logger polls each vehicle's REV tracking endpoint (`source_url` in
`config/vehicles.yaml`) and appends new snapshots to `data/live/`.

```bash
python -m backend.logger           # run until Ctrl+C
```

To view it, set `data.directory: data/live` in `config/app.yaml` and run
`python -m backend.app` in a second terminal. The endpoints only hold each
bus's latest position, so history starts when the logger does.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The browser tests (`test_map_stops.py`, `test_operator_view.py`) use Google
Chrome if it is installed. The operator view tests also accept the Chromium
that Playwright downloads, the easy option under WSL or Linux:

```bash
playwright install --with-deps chromium   # once; asks for sudo on Linux
```

Without a browser those tests are skipped and the rest of the suite still runs.

## Layout

```
config/      vehicle identity and app settings.
docs/        the API contract, the database schema, notes on the source data
data/        committed sample data.
backend/     Flask app, storage behind an interface, API blueprints, live logger.
tests/       pytest suite.
frontend/    Leaflet dashboard.
mobile/      Expo rider app for phones, see mobile/README.md.
drafts/      Sprint 1 prototypes, reference only so not part of the build.
GPS_Report/  client supplied telemetry and ROS 2 sample nodes.
```
