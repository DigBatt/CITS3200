
"""Daily snapshot scheduling and missed-day tracking (S17)."""

from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.files import write_json_atomic
import logging

PERTH_TZ = ZoneInfo("Australia/Perth")
log = logging.getLogger(__name__)


class SnapshotScheduler:
    def __init__(self, storage_directory: Path, snapshot_store, generate):
        self.path = Path(storage_directory) / "snapshot_schedule.json"
        self.snapshot_store = snapshot_store
        self.generate = generate


    def start(self, now: datetime) -> None:
        """Record missed days when the logger starts."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        import json

        today = now.astimezone(PERTH_TZ).date()

        if not self.path.exists():
            self._save_state({
                "last_checked": today.isoformat(),
                "missing": [],
            })
            return

        with self.path.open("r", encoding="utf-8") as file:
            state = json.load(file)

        last_checked = datetime.fromisoformat(
            state["last_checked"]
        ).date()

        missing = state.get("missing", [])
        day = last_checked

        while day < today:
            if not self.snapshot_store.exists(day):
                value = day.isoformat()
                if value not in missing:
                    missing.append(value)
            day += timedelta(days=1)

        self._save_state({
            "last_checked": today.isoformat(),
            "missing": missing,
        })


    def check(self, now: datetime) -> None:
        """Generate a snapshot when the running logger crosses midnight."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        import json

        today = now.astimezone(PERTH_TZ).date()

        with self.path.open("r", encoding="utf-8") as file:
            state = json.load(file)

        last_checked = datetime.fromisoformat(
            state["last_checked"]
        ).date()

        if today <= last_checked:
            return

        missing = state.get("missing", [])

        # Generate only if the logger has crossed into the next day.
        if today == last_checked + timedelta(days=1):
            local_now = now.astimezone(PERTH_TZ)
            minutes_after_midnight = (
                local_now.hour * 60 + local_now.minute
            )

            if not self.snapshot_store.exists(last_checked):
                if minutes_after_midnight <= 5:
                    try:
                        self.generate(last_checked)
                    except Exception:
                        log.exception(
                            "Failed to generate daily snapshot for %s",
                            last_checked,
                        )
                        return
                else:
                    value = last_checked.isoformat()
                    if value not in missing:
                        missing.append(value)
        else:
            day = last_checked
            while day < today:
                if not self.snapshot_store.exists(day):
                    value = day.isoformat()
                    if value not in missing:
                        missing.append(value)
                day += timedelta(days=1)

        self._save_state({
            "last_checked": today.isoformat(),
            "missing": missing,
        })

    def missing_dates(self) -> list[str]:
        """Return dates recorded as missing snapshots."""
        import json

        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as file:
            state = json.load(file)

        missing = state.get("missing", [])

        if not isinstance(missing, list):
            raise ValueError("Invalid snapshot schedule state.")

        return sorted(missing, reverse=True)

    def _save_state(self, state: dict) -> None:
        write_json_atomic(self.path, state)
