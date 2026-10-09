
"""Generate daily metric snapshots (S17)."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.downtime import intervals_by_vehicle
from backend.metrics.tum import Settings, summarise
from backend.repository.csv_repo import CsvRepository
from backend.roster_sync import with_synced_roster

PERTH_TZ = ZoneInfo("Australia/Perth")


def generate_daily_snapshot(
    day,
    config,
    settings_store,
    snapshot_store,
    downtime_store=None,
    roster_sync_store=None,
):
    """Generate and save metrics for one complete Perth calendar day."""

    if snapshot_store.exists(day):
        raise FileExistsError(f"Snapshot already exists for {day}")

    start_local = datetime.combine(day, time.min, tzinfo=PERTH_TZ)
    end_local = start_local + timedelta(days=1)

    start = start_local.astimezone(timezone.utc)
    end = end_local.astimezone(timezone.utc)

    repository = CsvRepository(config.live_directory, config.vehicles)
    vehicle_ids = repository.vehicle_ids()
    tracks = repository.get_positions(vehicle_ids, start, end)

    selected_metrics = settings_store.load()

    downtime = intervals_by_vehicle(
        downtime_store, vehicle_ids, start, end
    )

    metric_settings = with_synced_roster(
        Settings.from_config(config),
        roster_sync_store,
    )

    vehicles = []

    for vehicle_id in vehicle_ids:
        result = summarise(
            vehicle_id,
            tracks.get(vehicle_id, []),
            start,
            end,
            metric_settings,
            downtime=None if downtime is None else downtime[vehicle_id],
        ).to_dict()

        vehicles.append({
            "vehicle_id": vehicle_id,
            "kpis": {
                metric: result["kpis"].get(metric)
                for metric in selected_metrics
            },
            "unavailable": {
                metric: reason
                for metric, reason in result["unavailable"].items()
                if metric in selected_metrics
            },
        })

    snapshot = {
        "date": day.isoformat(),
        "timezone": "Australia/Perth",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "metrics": selected_metrics,
        "vehicles": vehicles,
    }

    snapshot_store.save(day, snapshot)

    return snapshot
