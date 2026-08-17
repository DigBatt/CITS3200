# nUWAy Fleet Dashboard Prototype

Desktop-first front-end prototype for the UWA REV nUWAy autonomous shuttle fleet.

## Files
- `index.html` — page structure
- `styles.css` — dashboard styling
- `data.js` — dummy fleet, event, path and utilisation data
- `app.js` — interactions, map, filters, offline logic and charts

## Run
Open `index.html` in a browser. An internet connection is currently required for:
- Leaflet JS/CSS
- OpenStreetMap map tiles
- Chart.js
- Google Fonts

For more consistent browser behaviour, you can also serve the folder locally, for example:

```bash
python3 -m http.server 8000
```

Then visit `http://localhost:8000`.

## Prototype behaviour
- Vehicle filter: all vehicles or an individual nUWAy shuttle
- Modes: Live, Today, Calendar
- Calendar date filters paths/events to that day (dummy data included for 11–13 Aug 2026)
- Map toggles are ON by default for routes, disengagements, re-engagements
- Vehicle is classified as offline after 15 minutes without telemetry
- Offline vehicles are greyed out
- Technology status shows Network, GPS, LiDAR, Cameras and Autonomous Software
- Service, safety and time-utilisation metrics update with the selected vehicle/date
- Doughnut chart represents time usage categories; KPI cards show availability/utilisation

## Future integration points
Replace `data.js` with API/database responses. The map/history/event rendering is already separated from the sample data so live telemetry can be wired in later.

## Prototype behaviour updates
- Vehicle markers use the same per-vehicle colour as their route.
- Disengagement markers are red; re-engagement markers are green.
- The calendar cannot select a date after `NUWAY_DATA.today`.
- Dates with no history return an empty dashboard rather than falling back to today's data.
- Historical dates only list and draw vehicles with a path recorded on that date.
- The UWA crest is stored at `assets/uwa-crest.png` inside the existing warm-colour brand tile.
