# nUWAy Fleet Dashboard

A single dashboard for the UWA REV Project's nUWAy autonomous shuttle fleet.

It replaces the existing per-shuttle page at
`revproject.com/vehicles/nuway.php`, which shows a live snapshot only and
overwrites positions week by week.

CITS3200 Group 11.

- [User guide](docs/user-guide.md): using the dashboard, for riders,
  operators and administrators.
- [Installation guide](docs/installation-guide.md): installing it on a web
  server and keeping it running.

The rest of this page is the quick start for developers.

## Local setup

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m backend.app              # http://127.0.0.1:5000
```

Out of the box the dashboard shows the committed sample data, so it runs with
no client access and no further setup. The sample is a short recording, not a
live feed, and only one of its two files contains real measurements; see
[data/README.md](data/README.md). To run on live data, see
[Live data](#live-data) below.

## Admin sign-in

The admin page (`/admin`, which holds the operator view) requires signing in
with one shared account. Its credentials are in `config/secrets.yaml`, which
is git-ignored and must never be committed:

```bash
cp config/secrets.example.yaml config/secrets.yaml
python -c "import secrets; print(secrets.token_hex(32))"     # paste as secret_key
python -c "from werkzeug.security import generate_password_hash as h; print(h(input('Password: ')))"
                                                             # paste as admin.password_hash
```

Without the file the rest of the app still runs; only sign-in is refused.
Limits and details: [docs/api.md](docs/api.md#administrator-sign-in).

## Live data

The logger polls each shuttle's REV tracking endpoint (`source_url` in
`config/vehicles.yaml`) and appends new positions to `data/live/`. Just after
midnight, Perth time, it also saves the previous day's daily snapshot under
`storage.directory`, worked out from `data.directory`.

```bash
python -m backend.logger           # run until Ctrl+C
```

To view the live data, set `data.directory: data/live` in `config/app.yaml`
and run `python -m backend.app` in a second terminal. The endpoints hold only
each shuttle's latest position, so the history starts when the logger does.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The browser tests (the files that import Playwright, such as
`test_map_stops.py` and `test_operator_view.py`) use Google Chrome if it is
installed. All of them except `test_map_stops.py` also accept the Chromium
that Playwright downloads, which is the easy option under WSL or Linux:

```bash
playwright install --with-deps chromium   # once; asks for sudo on Linux
```

Without a browser those tests are skipped and the rest of the suite still
runs.

## Layout

```text
config/      shuttle identity, app settings, stops and routes
docs/        the guides, the API contract, the data schema, design notes
data/        committed sample data
backend/     Flask app, storage behind an interface, API blueprints, live logger
tests/       pytest suite
frontend/    Leaflet dashboard and admin page
ngrok/       ngrok tunnel settings, for a public URL to a local run
drafts/      Sprint 1 prototypes, for reference only; not part of the build
GPS_Report/  client-supplied telemetry and ROS 2 sample nodes
```
