"""
python -m backend.logger
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from backend.config import ConfigError, load_config
from backend.ingest import rev_php
from backend.ingest.fetch import FetchError, fetch_json
from backend.models import Vehicle
from backend.repository import CsvRepository, Repository, RepositoryError

log = logging.getLogger("backend.logger")


@dataclass(frozen=True)
class LoggerSettings:
    """
    The `logger` block of config/app.yaml.
    """

    poll_interval_seconds: float
    timeout_seconds: float
    user_agent: str

    @classmethod
    def from_config(cls, config) -> "LoggerSettings":
        """
        Read the block from a backend.config.Config.

        Raises
        ------
        ConfigError
            If a setting is missing. Without a user agent every request is refused.
        """
        block = config.logger or {}
        missing = [key for key in ("poll_interval_seconds", "timeout_seconds", "user_agent") if not block.get(key)]
        if missing:
            raise ConfigError(f"config/app.yaml does not set logger.{', logger.'.join(missing)}")
        return cls(
            poll_interval_seconds=float(block["poll_interval_seconds"]),
            timeout_seconds=float(block["timeout_seconds"]),
            user_agent=str(block["user_agent"]),
        )


class Logger:
    """
    Polls vehicles and appends new snapshots to a repository.

    Parameters
    ----------
    repository : Repository
        Where rows go. Must implement `add_positions`.
    vehicles : sequence of Vehicle
        Those without a `source_url` are ignored.
    settings : LoggerSettings
    parse_settings : rev_php.Settings
    fetch : callable, optional
        `(url, user_agent, timeout) -> decoded JSON`, raising FetchError.
    """

    def __init__(
        self,
        repository: Repository,
        vehicles: Sequence[Vehicle],
        settings: LoggerSettings,
        parse_settings: rev_php.Settings,
        fetch: Callable[[str, str, float], Any] = fetch_json,
    ):
        self._repository = repository
        self._settings = settings
        self._parse_settings = parse_settings
        self._fetch = fetch
        self.vehicles = [v for v in vehicles if v.source_url]
        # Last stored row per vehicle: the dedup key and the speed baseline.
        self.last = repository.get_latest_positions([v.id for v in self.vehicles]) if self.vehicles else {}

    def poll(self, vehicle: Vehicle) -> bool:
        """
        Fetch, parse and store one vehicle's snapshot if it is new.

        Returns
        -------
        bool
            True if a row was stored. Failures are logged, not raised, and a
            failed write leaves `last` alone so the next poll retries it.
        """
        previous = self.last.get(vehicle.id)
        try:
            body = self._fetch(vehicle.source_url, self._settings.user_agent, self._settings.timeout_seconds)
            position = rev_php.parse(vehicle.id, body, previous, self._parse_settings, datetime.now(timezone.utc))
        except (FetchError, rev_php.PayloadError) as exc:
            log.warning("%s: %s", vehicle.id, exc)
            return False

        if previous is not None and position.timestamp <= previous.timestamp:
            return False

        try:
            self._repository.add_positions([position])
        except RepositoryError as exc:
            log.error("%s: %s", vehicle.id, exc)
            return False

        self.last[vehicle.id] = position
        where = "no fix" if position.latitude is None else f"{position.latitude:.6f},{position.longitude:.6f}"
        log.info("%s: stored %s %s", vehicle.id, position.timestamp.isoformat(), where)
        return True

    def poll_all(self) -> None:
        """
        Poll every vehicle once.
        """
        for vehicle in self.vehicles:
            self.poll(vehicle)

    def run(self) -> None:
        """
        Poll every `poll_interval_seconds` until interrupted.
        """
        while True:
            self.poll_all()
            time.sleep(self._settings.poll_interval_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    config = load_config()
    if config.live_directory is None:
        raise ConfigError("config/app.yaml does not set data.live_directory")
    settings = LoggerSettings.from_config(config)
    vehicles = [v for v in config.vehicles if v.source_url]
    logger = Logger(
        CsvRepository(config.live_directory, vehicles),
        vehicles,
        settings,
        rev_php.Settings.from_config(config),
        fetch=fetch_json,
    )

    log.info("polling %s every %gs into %s", ", ".join(v.id for v in vehicles),
             settings.poll_interval_seconds, config.live_directory)
    try:
        logger.run()
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
