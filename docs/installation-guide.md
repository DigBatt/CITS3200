# Installation guide

How to install the nUWAy Fleet Dashboard on a cloud web server and keep it
running. To use the dashboard once it is running, see the
[user guide](user-guide.md).

The commands assume an Ubuntu or Debian server. Other Linux distributions work
the same way with their own package manager.

## 1. What you are installing

Two programs, run from one folder:

| Program | What it does | How it is run |
|---|---|---|
| **Web app** | Serves the dashboard, the admin page and the API behind them. | Always on, behind a web server that provides HTTPS. |
| **Live logger** | Asks each shuttle's REV tracking address for its latest position and saves it. Just after midnight, Perth time, it also saves the daily snapshot for the day before. | Always on, alongside the web app. |

The logger gives the dashboard its history. The REV tracking addresses hold
only each shuttle's latest position, so the record starts when the logger
starts and has a gap for any time it is stopped.

The logger must also be running at midnight, Perth time, for the day that is
ending to get a daily snapshot. A day it misses is listed as "No snapshot" on
the admin page and is not made up later.

Everything is stored in files inside the install folder. There is no database
server to set up.

## 2. What you need

- A Linux server with 1 CPU and 1 GB of memory or more.
- Python 3.10 or newer, with `venv`.
- A domain name pointing at the server, for HTTPS.
- Outbound internet access from the server to `revproject.com` (the logger)
  and, if you use roster sync, to `api.calendar.online`.
- `git`, and `nginx` as the public web server.

```bash
sudo apt update
sudo apt install -y python3 python3-venv git nginx
```

People using the dashboard need a current browser with internet access. The
browser loads the map tiles (OpenStreetMap), the fonts and the map and 3D
libraries from public addresses.

## 3. Install

Create a user to run the service, and put the code in `/opt/nuway`:

```bash
sudo useradd --system --create-home --shell /bin/bash nuway
sudo mkdir /opt/nuway
sudo chown nuway:nuway /opt/nuway
sudo -iu nuway

git clone https://github.com/DigBatt/CITS3200.git /opt/nuway
cd /opt/nuway
git config user.name "nuway"
git config user.email "nuway@localhost"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt gunicorn
```

The two `git config` lines give this copy a name to work under. Nothing is
sent anywhere. Updating to a new version (section 10) needs them.

Stay signed in as `nuway` for sections 4 to 6.

## 4. Configure

All settings are in the `config/` folder.

| File | Holds |
|---|---|
| `config/secrets.yaml` | The admin account and keys. You create this file; it is never committed. |
| `config/app.yaml` | Application settings. |
| `config/vehicles.yaml` | The shuttles: id, name, colour and tracking address. |
| `config/stops.json` | Stops and routes. Normally edited from the admin page's Routes tab. |

### 4.1 Admin account (required)

```bash
cp config/secrets.example.yaml config/secrets.yaml
chmod 600 config/secrets.yaml

.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
.venv/bin/python -c "from werkzeug.security import generate_password_hash as h; print(h(input('Password: ')))"
```

Open `config/secrets.yaml` and paste the first value as `secret_key` and the
second as `admin.password_hash` (keep the quotes around the hash). Set
`admin.username` if you want something other than `admin`.

There is one admin account, shared by every operator and administrator.
Without this file the dashboard still runs, but nobody can sign in to the
admin page, which includes the operator view.

### 4.2 Switch to live data (required)

As supplied, the dashboard shows a small sample recording. To show what the
logger records, change one line in `config/app.yaml`:

```yaml
data:
  directory: data/live        # was data/sample
  live_directory: data/live
```

The daily snapshots are also worked out from `data.directory`, so that they
match the dashboard. If it is left at `data/sample`, each snapshot describes
the sample data, and the logger's log warns that it is not reading the live
data.

### 4.3 Check the shuttles

`config/vehicles.yaml` lists nUWAy 1 to 4 with their REV tracking addresses.
To add a shuttle, add an entry with a new `id`, a `name`, a `colour` and its
`source_url`. If the services are already running, restart both afterwards
(section 10).

### 4.4 Set the pickup hours

Riders can request a pickup only inside the hours under
`pickup_requests.operating_hours` in `config/app.yaml`. Outside them the
Rider tab shows "No pickups right now" instead of the stop list. The supplied
hours are Monday to Friday, 08:00 to 17:00. Change them to the hours the
shuttles run, for example:

```yaml
pickup_requests:
  operating_hours:
    monday: ["08:00", "17:00"]
    saturday: ["10:00", "14:00"]
```

- Each day has one opening and one closing time, in the time zone set by
  `display.timezone` (Perth as supplied). A day left out has no service.
- Put every time in quotes. An unquoted time such as `17:00` is misread, and
  the web app then refuses to start.
- The latest closing time is `"23:59"`, and a day cannot run past midnight.
- Removing the whole `operating_hours` block turns the check off, so
  requests are accepted at any time.
- A rider who is already waiting when the hours end keeps their request.

If the services are already running, restart `nuway-web` afterwards
(section 10).

### 4.5 Optional features

Both are set in `config/secrets.yaml`; the file's comments explain each.

| Setting | Turns on | Without it |
|---|---|---|
| `google_maps_api_key` | The Earth option in the 3D view (Google photorealistic 3D tiles). Needs a Google Maps Platform key with the Map Tiles API enabled. Restrict the key to your site's address, since browsers can see it. | The Earth switch stays off; the rest of the 3D view works. |
| `calendar_online_id` | Roster sync: drives booked on the REV driving calendar on calendar.online appear in the service schedule automatically. Which events count is set under `roster_sync` in `config/app.yaml`. | Only the schedule entered on the admin page applies. |

### 4.6 Other settings

The defaults suit the UWA fleet. The settings most likely to need changing
are listed in [section 9](#9-settings-reference).

## 5. Try it

Before setting up the services, check that the app starts:

```bash
.venv/bin/python -m backend.app
```

It should print that it is running on `http://127.0.0.1:5000`. From a second
terminal on the server, `curl -I http://127.0.0.1:5000/` should answer
`200 OK`. Stop it with Ctrl+C.

This command is for checking and development only. It runs Flask's debug
server, which must not be exposed to the internet. Section 6 sets up the
production service.

## 6. Run it as a service

### 6.1 The start-up file

Create `/opt/nuway/wsgi.py` with the lines below. The file builds the app
and starts roster sync, which the service must do itself:

```python
from backend.app import create_app, start_roster_sync

app = create_app()
start_roster_sync(app)
```

Type `exit` to return to your own account for the rest of this section.

### 6.2 The web app

Create `/etc/systemd/system/nuway-web.service`:

```ini
[Unit]
Description=nUWAy Fleet Dashboard (web app)
After=network-online.target
Wants=network-online.target

[Service]
User=nuway
WorkingDirectory=/opt/nuway
ExecStart=/opt/nuway/.venv/bin/gunicorn --workers 1 --threads 8 --bind 127.0.0.1:8000 wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Keep `--workers 1`.** Pickup requests are held in the app's memory and the
other records are plain files, so a second worker would give riders and
operators different answers. Raise `--threads` to handle more people at once.

### 6.3 The live logger

Create `/etc/systemd/system/nuway-logger.service`:

```ini
[Unit]
Description=nUWAy Fleet Dashboard (live logger)
After=network-online.target
Wants=network-online.target

[Service]
User=nuway
WorkingDirectory=/opt/nuway
ExecStart=/opt/nuway/.venv/bin/python -m backend.logger
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 6.4 Start both

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nuway-web nuway-logger
sudo systemctl status nuway-web nuway-logger
```

Both should show `active (running)`, and both now start on boot.

## 7. Put it on the internet with HTTPS

The web app listens only on the server itself (`127.0.0.1:8000`). nginx
receives public traffic and passes it on.

Create `/etc/nginx/sites-available/nuway`, with your own domain:

```nginx
server {
    listen 80;
    server_name dashboard.example.org;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and add a certificate:

```bash
sudo ln -s /etc/nginx/sites-available/nuway /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d dashboard.example.org
```

Certbot adds the HTTPS settings to the nginx file and renews the certificate
automatically.

**HTTPS is required.** The admin password and the sign-in cookie are only
safe in transit over HTTPS.

In your cloud provider's firewall, open ports 80 and 443 only. Port 8000
should not be reachable from outside.

## 8. Check it works

1. Open `https://dashboard.example.org/`. The dashboard loads with the map
   and the **Vehicles** panel.
2. Within a minute or two of the logger starting, shuttles that are reporting
   show as **ACTIVE** in the Vehicles panel. A shuttle that is switched off
   shows **INACTIVE**; that is correct.
3. Choose **Admin** at the top right and sign in with the account from
   section 4.1.
4. On the server, `ls /opt/nuway/data/live` lists a `positions_<id>.csv` file
   for each shuttle that has reported.

## 9. Settings reference

The settings in `config/app.yaml` most likely to need attention. Each is
commented in the file. Restart both services after changing any of them
(section 10).

| Setting | Default | Meaning |
|---|---|---|
| `data.directory` | `data/sample` | Where the dashboard reads positions from. Set to `data/live` (section 4.2). |
| `data.live_directory` | `data/live` | Where the logger writes. |
| `storage.directory` | `data/admin` | Where downtime records, rider reviews, snapshot settings, the daily snapshots and the synced roster are kept. |
| `logger.poll_interval_seconds` | `10` | How often the logger asks each shuttle's tracking address for its position. |
| `liveness.inactivity_threshold_seconds` | `300` | A shuttle silent for longer than this shows as INACTIVE, and its line on the map is broken at the gap. |
| `liveness.green_within_weekdays`, `liveness.red_after_days` | `1`, `10` | The green, yellow and red "last seen" dot in the Vehicles panel: green if seen today or within this many weekdays before; red if not seen for more than this many days. |
| `map.centre`, `map.zoom`, `map.refresh_interval_seconds` | UWA Crawley, `16`, `15` | Not read by this version. The map's opening position and the 15-second live refresh are fixed in the code (`frontend/js/map.js`, `frontend/js/timeline.js`). |
| `display.timezone` | `Australia/Perth` | The time zone the service schedule and the pickup hours are written in. |
| `utilisation.depot` | Placeholder | The depot's position and radius. A shuttle stopped inside it counts as on standby, not delayed. **Set this to the real depot.** |
| `utilisation.stationary_speed_mps`, `min_standby_seconds`, `max_gap_seconds` | `0.2`, `120`, `60` | Thresholds for the utilisation figures: the speed below which a shuttle counts as stopped, the shortest stop at the depot that counts as standby, and the longest gap between two positions that still counts as reporting. |
| `utilisation.service_hours` | Mon to Fri 08:00 to 17:00, nUWAy 1 to 3 | The service schedule. Edit it from the admin page's Schedule tab, not here. |
| `roster_sync.*` | nUWAy 4 | Which calendar.online events count as drives (section 4.5). |
| `admin.session_hours` | `12` | How long an admin sign-in lasts after it was last used. |
| `pickup_requests.expire_after_seconds` | `1800` | How long a pickup request stays open if the rider is not collected. |
| `pickup_requests.operating_hours` | Mon to Fri 08:00 to 17:00 | The days and hours riders may request a pickup (section 4.4). |
| `snapshots.default_metrics` | Asset utilisation, operating efficiency, effective utilisation | The metrics recorded in daily snapshots until an administrator saves a selection. |

## 10. Keeping it running

### Logs

```bash
sudo journalctl -u nuway-web -f
sudo journalctl -u nuway-logger -f
```

### What to back up

Everything that cannot be recreated is in these folders. Copy them off the
server on a schedule:

| Path | Contents |
|---|---|
| `/opt/nuway/data/live/` | Every position the logger has recorded. |
| `/opt/nuway/data/admin/` | Downtime records, rider reviews, snapshot settings, the synced roster, the daily snapshots (`snapshots/`, one file per day) and the list of days without one (`snapshot_schedule.json`). |
| `/opt/nuway/config/` | All settings, including `secrets.yaml` and the service schedule, stops and routes edited from the admin page. |

To restore, put the folders back and restart both services.

The position files grow without limit, by at most one row per shuttle per
poll.

### Restarting

```bash
sudo systemctl restart nuway-web nuway-logger
```

Restart both after editing any file in `config/` by hand. Changes made from
the admin page (schedule, routes, downtime, snapshot settings) apply
immediately and need no restart.

Restarting the web app clears all pickup requests. Riders who were waiting
must reload the page and request again.

Do not restart the logger around midnight, Perth time. If it is not running
when the day changes, that day gets no daily snapshot.

### Changing the admin password

Generate a new hash as in section 4.1, replace `admin.password_hash` in
`config/secrets.yaml`, and restart `nuway-web`. To sign everyone out at the
same time, replace `secret_key` as well.

### Updating to a new version

The admin page writes to two tracked files, `config/app.yaml` and
`config/stops.json`, so the commands below set your changes aside while
updating. Both services are stopped during the update, so do not update
across midnight, Perth time, or that day gets no daily snapshot:

```bash
sudo systemctl stop nuway-web nuway-logger
sudo -iu nuway
cd /opt/nuway
cp -r config config.backup-$(date +%F)

git stash
git pull
git stash pop
.venv/bin/pip install -r requirements.txt

exit
sudo systemctl start nuway-web nuway-logger
```

If `git stash` reports no local changes, skip `git stash pop`. If
`git stash pop` reports a conflict, the new version changed a settings file
you had also changed. Compare the file with your copy in
`config.backup-<date>` and keep your values.

## 11. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The web app will not start, and the log says "both stops.json and stops.yaml exist". | An old `config/stops.yaml` is present. Delete it; `stops.json` is the one used. |
| The log says "No /opt/nuway/config/secrets.yaml: admin sign-in is disabled", or the sign-in page says "Admin sign-in is not set up". | `config/secrets.yaml` is missing. Follow section 4.1. |
| The web app will not start after a settings file was edited. | There is a mistake in the file. The log names the file and the problem. |
| The web app will not start, and the log says a time "is not a time of day, expected "HH:MM" in quotes". | A time in `pickup_requests.operating_hours` is not in quotes. Write `"17:00"`, not `17:00`. |
| The dashboard loads but the utilisation figures and the Schedule tab show an error, and the log has the same "is not a time of day" message. | A time in `utilisation.service_hours` is not in quotes. Write `"17:00"`, not `17:00`, and restart both services. |
| Riders see "No pickups right now" when the shuttles are running. | The time is outside `pickup_requests.operating_hours`. Correct the hours (section 4.4) and restart `nuway-web`. |
| Every shuttle shows INACTIVE or "No telemetry received". | The logger is not running, cannot reach `revproject.com`, or `data.directory` still points at `data/sample`. Check `systemctl status nuway-logger` and its log. |
| The logger log shows HTTP 406 errors. | The REV server rejects requests that do not look like a browser. Leave `logger.user_agent` in `config/app.yaml` as supplied. |
| The Downtime tab or a rider's review reports an error about `storage.directory`. | `storage.directory` is unset in `config/app.yaml`, or the `nuway` user cannot write to it. |
| Saving the schedule or routes from the admin page fails. | The `nuway` user cannot write to `/opt/nuway/config`. Run `sudo chown -R nuway:nuway /opt/nuway`. |
| The Snapshots tab lists a day as "No snapshot". | The logger was not running when that day ended, or it could not work the snapshot out and stopped trying at 01:00. In the second case the logger log for that night has "Failed to generate daily snapshot" lines. The day is not made up later. |
| The logger log says "daily snapshots disabled". | The roster sync, snapshot or data settings are invalid; the rest of the line names the problem. Positions are still being recorded. Fix the setting and restart `nuway-logger`. |
| The logger log says "daily snapshots read ..., not the live data in ...". | `data.directory` still points at the sample. Follow section 4.2. |
| The Snapshots tab says "Unable to load snapshots". | With "(500)", `storage.directory` is unset in `config/app.yaml` or a file under it cannot be read. With "(401)", the sign-in has expired; reload the page and sign in again. |
| The browser shows "502 Bad Gateway". | nginx is running but the web app is not. Check `systemctl status nuway-web`. |
| Everyone is signed out of the admin page at once. | `secret_key` in `config/secrets.yaml` changed, which ends every sign-in. Sign in again. |
| The Earth switch in the 3D view cannot be turned on. | No `google_maps_api_key`, or the key is not enabled for the Map Tiles API or is restricted to a different address. |

## 12. Known limitations

- **The dashboard's opening period.** The dashboard opens showing everything
  from 08:00 on 4 September 2025, the date of the sample data, up to now. On
  a live install that should be today. It is set by `DEV_DEFAULT_START_DATE`
  near the top of `frontend/js/timeline.js` and needs a code change, not a
  setting.
- **One shared admin account**, with no lockout after repeated wrong
  passwords. Use a long password and HTTPS.
- **Pickup requests are not saved.** They are held in memory and cleared when
  the web app restarts.
- **A missed daily snapshot is not made up.** A day gets a snapshot only if
  the logger is running when it ends. Otherwise it is listed as "No snapshot",
  even though its positions are still on the dashboard.
- **A daily snapshot is fixed once saved.** Downtime recorded or changed for a
  day afterwards changes the dashboard's figures for it, not its snapshot.
- **Pickup hours and the service schedule are separate.** The hours riders
  may request a pickup (section 4.4) are set in `config/app.yaml`. The
  schedule behind the utilisation figures is set on the admin page's
  Schedule tab. Changing one does not change the other.
- **Times are shown in Perth time.** The dashboard's date and time controls
  and the daily snapshots are fixed to Perth (UTC+8). The Downtime and
  Reviews tabs and the full calendar use the time zone of the device they
  are opened on.
- **The `map` settings are not read.** The map's opening position and the
  live refresh interval need a code change, not a setting (section 9).
- **One server process.** The web app must run with a single worker
  (section 6.2), which is ample for a fleet of this size.
