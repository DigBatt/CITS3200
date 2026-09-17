# Data

## What is committed here

`sample/` holds a small replay set, committed so the dashboard and its demo run.

| File | Rows | Provenance |
|---|---|---|
| `sample/positions_1.csv` | 439 | Real. `GPS_Report/data/rtkfull-gps-track-5s.csv`, 5 second polling. |
| `sample/positions_2.csv` | 220 | Synthetic. Vehicle 1's real track offset ~200 m and decimated a bit to give a second vehicle for S04 and S05. |

## Adding a vehicle

Drop `positions_<id>.csv` into the data directory and add an entry to
`config/vehicles.yaml`. That is the whole procedure. Give the entry a
`source_url` if the live logger should poll it.

## Live data

The live logger appends to `data.live_directory` (`data/live/`), which is not
committed. Point `data.directory` at it in `config/app.yaml` to view live data.

