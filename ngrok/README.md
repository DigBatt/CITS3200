# Exposing the backend and the rider app with ngrok

`ngrok.yml` defines three endpoints. None of this runs on its own.

| Endpoint | Local port | Who uses it | Guard |
|---|---|---|---|
| `nuway-api` | 5001 | The mobile app | Only `/api/*` passes |
| `nuway-dashboard` | 5001 | A browser: dashboard, admin, API | Basic auth, user `operator`, password from the vault |
| `nuway-metro` | 8081 | Expo Go, to load the app bundle | None |

## One-time setup

1. Install the agent if missing: `brew install ngrok`.
2. Add your token to the agent's default config, outside the repo:

   ```bash
   ngrok config add-authtoken <token>
   ```

3. Reserve domains in the ngrok dashboard and put them in the `url` fields,
   or delete those lines for random hostnames. Random hostnames change every
   start.
4. The dashboard password is not in the repo. `ngrok.yml` reads it from the
   account's vault at start, through `secrets.get('nuway', 'dashboard-password')`.
   The vault and secret exist already. To rotate the password:

   ```bash
   ngrok api secrets list                              # find the secret id
   ngrok api secrets update <id> --value '<new password>'
   ```

   The change applies to the running tunnel without a restart. Managing the
   vault needs an API key on this machine, `ngrok config add-api-key <key>`,
   as well as the authtoken. Both must belong to the same account, on a paid
   plan, as the reserved domains.

## Running

Start the backend on localhost only. ngrok connects to it locally, so there
is no reason to bind to all interfaces any more:

```bash
FLASK_APP=backend.app:create_app flask run --port 5001
```

Start Metro in tunnel mode. This reads `mobile/endpoints.yaml`, makes the
app call the API tunnel, and advertises the Metro tunnel to Expo Go:

```bash
cd mobile
npm run start:tunnel
```

Start the tunnels, merging the token config with this one:

```bash
ngrok start --all \
  --config "$HOME/Library/Application Support/ngrok/ngrok.yml" \
  --config ngrok/ngrok.yml
```

## Keeping the three files in step

The hostnames live in three places on purpose, one per app, so each can be
started on its own:

| File | Holds |
|---|---|
| `ngrok/ngrok.yml` | The tunnels: public URL to local port |
| `backend/endpoints.yaml` | The port Flask listens on, and the public URLs it reports at `GET /api/endpoints` |
| `mobile/endpoints.yaml` | The LAN port and the tunnel URLs the app uses |

When you reserve real domains, change the `url` values here and the matching
entries in the other two files.

## Notes

- Expo has its own tunnel mode, `npx expo start --tunnel`, which runs ngrok
  for you through `@expo/ngrok`. It is the simpler path if the Metro tunnel
  is all you need. The config here keeps all three tunnels in one place.
- Free ngrok accounts show an interstitial page on the first browser visit.
  API calls from the app and bundle requests from Expo Go are not browsers,
  so they are not affected.
- Check your plan's limit on simultaneous endpoints and reserved domains.
- Do not start the backend with `python -m backend.app` while tunnelled. That
  entry point turns on Flask's debug mode, which exposes an interactive
  debugger on error pages.
- Pickup requests are held in memory and anyone with the API URL can create
  one. Stop the agent when you finish testing.
