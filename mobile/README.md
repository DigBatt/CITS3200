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

2. Tell the app which port the backend is on (only needed when it is not 5000):

   ```bash
   cd mobile
   cp .env.example .env                    # then set EXPO_PUBLIC_API_PORT=5001
   ```

3. Start Metro and scan the QR code with Expo Go:

   ```bash
   npm install
   npx expo start
   ```

By default the app takes the backend host from the Metro dev server, so a
phone that can load the bundle can also reach the API. Set
`EXPO_PUBLIC_API_URL` in `.env` to point somewhere else, such as a deployed
backend.

## Pickup requests

The app posts to `POST /api/pickup-requests` with `{"stop_id": "..."}`,
the contract on the `rider-requests` branch. On a backend without that
endpoint the request button reports that pickups are not enabled on the
server, and everything else keeps working.

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
