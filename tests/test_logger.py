"""
backend.logger: polling, against a scripted fetcher.
"""

from __future__ import annotations
import dataclasses
import logging
from datetime import datetime, timedelta, timezone
from math import degrees

import pytest

import backend.logger as logger_module
from backend.config import ConfigError, load_config
from backend.ingest import rev_php
from backend.ingest.fetch import FetchError
from backend.logger import Logger, LoggerSettings, main
from backend.metrics.tum import EARTH_RADIUS_M
from backend.models import Vehicle
from backend.repository import CsvRepository, RepositoryError

UA = "Mozilla/5.0 test"
SETTINGS = LoggerSettings(poll_interval_seconds=5, timeout_seconds=10, user_agent=UA)
PARSE = rev_php.Settings(latitude_bounds=(-36.0, -13.0), longitude_bounds=(112.0, 130.0), max_gap_seconds=30.0)
BUS1 = Vehicle(id="1", source_url="http://rev.test/gps_pos.php")
BUS2 = Vehicle(id="2", source_url="http://rev.test/gps_pos2.php")
NO_URL = Vehicle(id="9")
LAT, LON = -31.98, 115.82
BASE = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
NORTH = LAT + degrees(50 / EARTH_RADIUS_M)  # 50 m north of LAT


def snapshot(seconds: int, lat=LAT, lon=LON) -> dict:
    return {"lat": lat, "lon": lon, "heading": 90, "battery_percentage": 70, "timestamp": BASE + seconds}


class Fetcher:
    """Returns (or raises) the next scripted item per URL; repeats the last one."""

    def __init__(self, bus1=(), bus2=()):
        self.scripts = {BUS1.source_url: list(bus1), BUS2.source_url: list(bus2)}
        self.calls = []

    def __call__(self, url, user_agent, timeout):
        self.calls.append((url, user_agent, timeout))
        script = self.scripts[url]
        item = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(item, BaseException):
            raise item
        return item


def make_logger(tmp_path, fetcher, repository=None):
    repository = repository or CsvRepository(tmp_path, [BUS1, BUS2])
    return Logger(repository, [BUS1, BUS2, NO_URL], SETTINGS, PARSE, fetch=fetcher)


def stored(tmp_path, vehicle_id="1"):
    return CsvRepository(tmp_path, [Vehicle(id=vehicle_id)]).get_positions([vehicle_id])[vehicle_id]


def test_ignores_vehicles_without_a_source_url(tmp_path):
    assert [v.id for v in make_logger(tmp_path, Fetcher()).vehicles] == ["1", "2"]


def test_passes_user_agent_and_timeout(tmp_path):
    fetcher = Fetcher(bus1=[snapshot(0)], bus2=[snapshot(0)])
    make_logger(tmp_path, fetcher).poll_all()
    assert [call[1:] for call in fetcher.calls] == [(UA, 10), (UA, 10)]


def test_stores_new_skips_same_and_ignores_older(tmp_path):
    logger = make_logger(tmp_path, Fetcher(bus1=[snapshot(0), snapshot(0), snapshot(5), snapshot(3), snapshot(10)]))
    assert [logger.poll(BUS1) for _ in range(5)] == [True, False, True, False, True]
    assert [p.timestamp.timestamp() - BASE for p in stored(tmp_path)] == [0, 5, 10]


def test_derives_speed_across_polls(tmp_path):
    logger = make_logger(tmp_path, Fetcher(bus1=[snapshot(0), snapshot(5, lat=NORTH)]))
    logger.poll(BUS1)
    logger.poll(BUS1)
    speeds = [p.speed_mps for p in stored(tmp_path)]
    assert speeds[0] is None and speeds[1] == pytest.approx(10.0)


def test_restart_does_not_duplicate_and_keeps_the_speed_baseline(tmp_path):
    make_logger(tmp_path, Fetcher(bus1=[snapshot(0)])).poll(BUS1)

    restarted = make_logger(tmp_path, Fetcher(bus1=[snapshot(0), snapshot(5, lat=NORTH)]))
    assert restarted.last["1"].timestamp == stored(tmp_path)[0].timestamp
    assert restarted.poll(BUS1) is False
    assert restarted.poll(BUS1) is True

    rows = stored(tmp_path)
    assert len(rows) == 2
    assert rows[1].speed_mps == pytest.approx(10.0)


def test_one_failing_vehicle_does_not_block_the_others(tmp_path, caplog):
    make_logger(tmp_path, Fetcher(bus1=[FetchError("down")], bus2=[snapshot(0)])).poll_all()
    assert stored(tmp_path, "1") == []
    assert len(stored(tmp_path, "2")) == 1
    assert "1: down" in caplog.text


def test_unparseable_payload_writes_nothing(tmp_path, caplog):
    assert make_logger(tmp_path, Fetcher(bus1=[{"lat": LAT}])).poll(BUS1) is False
    assert stored(tmp_path) == []
    assert "no usable timestamp" in caplog.text


def test_future_timestamp_is_refused_and_does_not_block_later_rows(tmp_path):
    future = snapshot(0)
    future["timestamp"] = int((datetime.now(timezone.utc) + timedelta(days=365)).timestamp())
    logger = make_logger(tmp_path, Fetcher(bus1=[future, snapshot(5)]))
    assert logger.poll(BUS1) is False
    assert logger.poll(BUS1) is True


class FlakyRepository(CsvRepository):
    def __init__(self, *args, failures=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.failures = failures

    def add_positions(self, positions):
        if self.failures:
            self.failures -= 1
            raise RepositoryError("disk full")
        return super().add_positions(positions)


def test_failed_write_is_retried_on_the_next_poll(tmp_path, caplog):
    repository = FlakyRepository(tmp_path, [BUS1, BUS2])
    logger = make_logger(tmp_path, Fetcher(bus1=[snapshot(0)]), repository=repository)
    assert logger.poll(BUS1) is False
    assert "disk full" in caplog.text
    assert logger.last["1"] is None
    assert logger.poll(BUS1) is True
    assert len(stored(tmp_path)) == 1


def test_run_polls_until_interrupted(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(logger_module.time, "sleep", sleeps.append)
    fetcher = Fetcher(bus1=[snapshot(0), snapshot(5), KeyboardInterrupt()], bus2=[snapshot(0)])
    with pytest.raises(KeyboardInterrupt):
        make_logger(tmp_path, fetcher).run()
    assert sleeps == [5, 5]
    assert len(stored(tmp_path)) == 2


def test_settings_from_config():
    block = load_config().logger
    assert LoggerSettings.from_config(load_config()) == LoggerSettings(
        poll_interval_seconds=float(block["poll_interval_seconds"]),
        timeout_seconds=float(block["timeout_seconds"]),
        user_agent=block["user_agent"],
    )


def test_settings_require_the_user_agent():
    config = load_config()
    config = dataclasses.replace(config, logger={**config.logger, "user_agent": ""})
    with pytest.raises(ConfigError, match="user_agent"):
        LoggerSettings.from_config(config)


def run_main(monkeypatch, config, responses):
    """Run main() for one round of polls, then interrupt it as Ctrl+C would."""

    def fetch(url, user_agent, timeout):
        return responses[url.rsplit("/", 1)[-1]]

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(logger_module, "load_config", lambda: config)
    monkeypatch.setattr(logger_module, "fetch_json", fetch)
    monkeypatch.setattr(logger_module.time, "sleep", interrupt)
    main()


ALL = {name: snapshot(0) for name in ("gps_pos.php", "gps_pos2.php", "gps_pos3.php", "gps_pos4.php")}


def test_main_polls_every_configured_vehicle_and_stops_cleanly(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.INFO, logger="backend.logger"):
        run_main(monkeypatch, dataclasses.replace(load_config(), live_directory=tmp_path), ALL)
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"positions_{i}.csv" for i in "1234"]
    assert caplog.records[-1].getMessage() == "stopped"


def test_main_requires_a_live_directory(monkeypatch):
    with pytest.raises(ConfigError, match="live_directory"):
        run_main(monkeypatch, dataclasses.replace(load_config(), live_directory=None), ALL)


def test_main_refuses_to_append_to_files_in_another_format(tmp_path, monkeypatch, caplog):
    # A copy of the sample data, so a failure here cannot touch the real files.
    config = load_config()
    for source in config.data_directory.glob("*.csv"):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    run_main(monkeypatch, dataclasses.replace(config, live_directory=tmp_path), ALL)
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert {name: after[name] for name in before} == before
    assert "has a header other than" in caplog.text
