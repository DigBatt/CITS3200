
"""Daily snapshot scheduling and missed-day tracking (S17)."""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.files import write_json_atomic

PERTH_TZ = ZoneInfo("Australia/Perth")
# How long after midnight a failing snapshot is retried before the day is
# recorded as missing.
RETRY_MINUTES = 60
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

        today = now.astimezone(PERTH_TZ).date()

        state = self._load_state()

        if state is None:
            self._save_state({
                "last_checked": today.isoformat(),
                "missing": [],
            })
            return

        last_checked, missing = state
        self._mark_missing(missing, last_checked, today)

        self._save_state({
            "last_checked": today.isoformat(),
            "missing": missing,
        })


    def check(self, now: datetime) -> None:
        """Generate a snapshot when the running logger crosses midnight."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        today = now.astimezone(PERTH_TZ).date()

        state = self._load_state()

        # The state file was removed or damaged while running: start afresh.
        if state is None:
            self._save_state({
                "last_checked": today.isoformat(),
                "missing": [],
            })
            return

        last_checked, missing = state

        if today <= last_checked:
            return

        # Generate only if the logger has crossed into the next day. Reaching
        # here means it was running over midnight, however late this check is.
        if today == last_checked + timedelta(days=1):
            local_now = now.astimezone(PERTH_TZ)
            minutes_after_midnight = (
                local_now.hour * 60 + local_now.minute
            )

            if not self.snapshot_store.exists(last_checked):
                try:
                    self.generate(last_checked)
                except Exception:
                    log.exception(
                        "Failed to generate daily snapshot for %s",
                        last_checked,
                    )
                    # Leave the state alone so the next check retries.
                    if minutes_after_midnight <= RETRY_MINUTES:
                        return
                    self._mark_missing(missing, last_checked, today)
        else:
            self._mark_missing(missing, last_checked, today)

        self._save_state({
            "last_checked": today.isoformat(),
            "missing": missing,
        })

    def missing_dates(self) -> list[str]:
        """Return dates recorded as missing snapshots."""
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as file:
            state = json.load(file)

        missing = state.get("missing", [])

        if not isinstance(missing, list):
            raise ValueError("Invalid snapshot schedule state.")

        return sorted(missing, reverse=True)

    def _load_state(self) -> tuple[date, list[str]] | None:
        """Return (last_checked, missing), or None without a usable state file."""
        try:
            with self.path.open("r", encoding="utf-8") as file:
                state = json.load(file)

            last_checked = datetime.fromisoformat(
                state["last_checked"]
            ).date()
            missing = state.get("missing", [])

            if not isinstance(missing, list):
                raise ValueError("missing is not a list")
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning(
                "Ignoring unreadable snapshot schedule %s: %s",
                self.path,
                exc,
            )
            return None

        return last_checked, missing

    def _mark_missing(self, missing: list[str], first: date, today: date) -> None:
        """Add each day from `first` up to yesterday that has no snapshot."""
        day = first

        while day < today:
            if not self.snapshot_store.exists(day):
                value = day.isoformat()
                if value not in missing:
                    missing.append(value)
            day += timedelta(days=1)

    def _save_state(self, state: dict) -> None:
        write_json_atomic(self.path, state)
