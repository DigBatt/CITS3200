# nUWAy rider app

An Expo (React Native) app for riders of the nUWAy shuttle fleet. It talks to
the same Flask JSON API as the Leaflet dashboard ([../docs/api.md](../docs/api.md)).

Two screens:

- **Live map.** Every bus at its last reported position, coloured as in the
  dashboard and greyed once it stops reporting, with the configured stops and
  routes drawn over the campus. Filter by route, toggle stops and today's
  trails, tap a bus to centre on it, tap a stop's callout to request a pickup
  there.
- **Request pickup.** The fleet as a list with live status, speed and distance
  to the chosen stop, a route picker, the stops on that route in service
  order, and a button that opens a pickup request. Requests made in this
  session are listed underneath with their status.

## Run it

Requires Node 20+ and the Expo Go app on a phone on the same Wi-Fi as this
machine. `react-native-maps` is bundled in Expo Go, so no native build is needed.

1. Start the backend so the phone can reach it. `python -m backend.app` binds
   to localhost only, so bind to all interfaces instead. On macOS, port 5000
   is usually taken by AirPlay Receiver, so use another:

   ```bash
   cd ..                                   # repo root
   FLASK_APP=backend.app:create_app flask run --host 0.0.0.0 --port 5001
   ```

2. Check `lan.port` in `endpoints.yaml` matches that port (it is 5001 already).

3. Start Metro and scan the QR code with Expo Go:

   ```bash
   npm install
   npx expo start
   ```

By default the app takes the backend host from the Metro dev server, so a
phone that can load the bundle can also reach the API. Set
`EXPO_PUBLIC_API_URL` in `.env` to point somewhere else, such as a deployed
backend.

## Endpoints

`endpoints.yaml` is the one place the app learns where the backend is.
`app.config.js` reads it when Metro starts and hands it to the app through
`Constants.expoConfig.extra.endpoints`; `src/lib/endpoints.ts` turns that
into the API base URL.

| Key | Used by | Mirrors |
|---|---|---|
| `lan.port` | `npm start` | `listen.port` in `../backend/endpoints.yaml` |
| `tunnel.api` | `npm run start:tunnel` | `nuway-api` in `../ngrok/ngrok.yml` |
| `tunnel.metro` | `npm run start:tunnel`, advertised to Expo Go | `nuway-metro` |
| `tunnel.dashboard` | nothing yet | `nuway-dashboard` |

`npm run start:tunnel` sets `NUWAY_TUNNEL=1`, which makes the app call
`tunnel.api`, and `EXPO_PACKAGER_PROXY_URL` so Expo Go loads the bundle
through `tunnel.metro`. It expects `ngrok start --all` to be running, see
[../ngrok/README.md](../ngrok/README.md). Edit the YAML and restart Metro to
change any of it.

## Pickup requests

The app posts to `POST /api/pickup-requests` with `{"stop_id": "..."}`
([../docs/api.md](../docs/api.md)). Requests are held in memory by the
backend, so restarting it clears them. On a backend without the endpoint the
request button reports that pickups are not enabled on the server, and
everything else keeps working.

The backend identifies a rider by a cookie set on their first request. Native
fetch keeps that cookie between calls, so the no-duplicate rule works without
an account.

## Checks

```bash
npm run typecheck     # tsc --noEmit
npm run lint          # expo lint
npm run doctor        # expo-doctor
```

## Layout

```
src/app/            Expo Router screens. (tabs)/index.tsx is the map, (tabs)/request.tsx the pickup form.
src/api/            Fetch wrappers and the API's TypeScript shapes.
src/hooks/          Polling, fleet and stop network loaders, pickup request store.
src/components/     Map markers, route lines, cards, chips.
src/lib/            Geometry, formatting, theme.
```
