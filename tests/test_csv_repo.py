"""
CsvRepository: appending, and reading only what was appended.
"""

from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.config import load_config
from backend.models import Position, Vehicle
from backend.repository.base import Repository, RepositoryError
from backend.repository.csv_repo import FIELDNAMES, CsvRepository

T0 = datetime(2026, 9, 17, 1, 0, 0, 123456, tzinfo=timezone.utc)
HEADER = ",".join(FIELDNAMES) + "\n"


def make_repo(directory: Path, ids=("1", "2")) -> CsvRepository:
    return CsvRepository(directory, [Vehicle(id=i, positions_file=f"positions_{i}.csv") for i in ids])


def pos(vehicle_id="1", seconds=0.0, **fields) -> Position:
    defaults = dict(latitude=-31.98, longitude=115.82, gps_status=0)
    return Position(vehicle_id=vehicle_id, timestamp=T0 + timedelta(seconds=seconds), **{**defaults, **fields})


def test_round_trip_keeps_values_nulls_and_microseconds(tmp_path):
    rows = [
        pos(seconds=0, altitude_m=-20.552, heading_deg=54.39, speed_mps=0.12, battery_percent=76.0),
        pos(seconds=5.5, heading_deg=None, speed_mps=None, battery_percent=None),
        pos(seconds=10, latitude=None, longitude=None, gps_status=-1),
    ]
    assert make_repo(tmp_path).add_positions(rows) == 3
    assert make_repo(tmp_path).get_positions(["1"])["1"] == rows


def test_header_written_once_across_batches(tmp_path):
    repo = make_repo(tmp_path)
    repo.add_positions([pos(seconds=0)])
    repo.add_positions([pos(seconds=5)])
    lines = (tmp_path / "positions_1.csv").read_text().splitlines()
    assert lines[0] == HEADER.strip()
    assert len(lines) == 3


def test_creates_missing_directory(tmp_path):
    repo = make_repo(tmp_path / "live")
    repo.add_positions([pos()])
    assert (tmp_path / "live" / "positions_1.csv").exists()


def test_batch_split_per_vehicle(tmp_path):
    repo = make_repo(tmp_path)
    repo.add_positions([pos("1", 0), pos("2", 0), pos("1", 5)])
    counts = {k: len(v) for k, v in repo.get_positions().items()}
    assert counts == {"1": 2, "2": 1}


def test_empty_batch_writes_nothing(tmp_path):
    assert make_repo(tmp_path).add_positions([]) == 0
    assert not (tmp_path / "positions_1.csv").exists()


def test_unknown_vehicle_rejected_before_any_write(tmp_path):
    with pytest.raises(RepositoryError):
        make_repo(tmp_path).add_positions([pos("1"), pos("9")])
    assert not (tmp_path / "positions_1.csv").exists()


def test_refuses_to_append_to_a_foreign_header(tmp_path):
    path = tmp_path / "positions_1.csv"
    path.write_text("timestamp,latitude,longitude,heading,speed_mps,battery_percent\n")
    with pytest.raises(RepositoryError):
        make_repo(tmp_path).add_positions([pos()])
    assert path.read_text().count("\n") == 1


def test_existing_reader_sees_appended_rows(tmp_path):
    # Separate instances stand in for the logger and dashboard processes.
    writer, reader = make_repo(tmp_path), make_repo(tmp_path)
    writer.add_positions([pos(seconds=0)])
    assert len(reader.get_positions(["1"])["1"]) == 1
    writer.add_positions([pos(seconds=5), pos(seconds=10)])
    assert [p.timestamp for p in reader.get_positions(["1"])["1"]] == [
        T0, T0 + timedelta(seconds=5), T0 + timedelta(seconds=10)
    ]
    assert reader.get_latest_positions(["1"])["1"].timestamp == T0 + timedelta(seconds=10)


def test_incremental_reads_match_a_fresh_read(tmp_path):
    writer, reader = make_repo(tmp_path), make_repo(tmp_path)
    for batch in range(20):
        writer.add_positions([pos(seconds=batch * 5 + i, battery_percent=float(batch)) for i in range(3)])
        reader.get_positions()
    assert reader.get_positions() == make_repo(tmp_path).get_positions()
    assert len(reader.get_positions(["1"])["1"]) == 60


def test_out_of_order_append_comes_back_sorted(tmp_path):
    writer, reader = make_repo(tmp_path), make_repo(tmp_path)
    writer.add_positions([pos(seconds=10)])
    reader.get_positions()
    writer.add_positions([pos(seconds=5), pos(seconds=20)])
    stamps = [p.timestamp for p in reader.get_positions(["1"])["1"]]
    assert stamps == sorted(stamps) and len(stamps) == 3


def test_duplicate_timestamp_keeps_last_row(tmp_path):
    writer, reader = make_repo(tmp_path), make_repo(tmp_path)
    writer.add_positions([pos(seconds=0, battery_percent=50.0)])
    reader.get_positions()
    writer.add_positions([pos(seconds=0, battery_percent=60.0)])
    rows = reader.get_positions(["1"])["1"]
    assert len(rows) == 1 and rows[0].battery_percent == 60.0


def test_unterminated_last_line_is_held_back_until_complete(tmp_path):
    path = tmp_path / "positions_1.csv"
    full = "2026-09-17T01:00:05.000000Z,-31.98133,115.82,,,,0,\n"
    path.write_text(HEADER + "2026-09-17T01:00:00.000000Z,-31.98,115.82,,,,0,\n" + full[:30])
    repo = make_repo(tmp_path)
    assert len(repo.get_positions(["1"])["1"]) == 1
    with open(path, "a") as handle:
        handle.write(full[30:])
    rows = repo.get_positions(["1"])["1"]
    assert len(rows) == 2 and rows[1].latitude == -31.98133


def test_append_after_a_crashed_write_skips_the_fragment(tmp_path):
    path = tmp_path / "positions_1.csv"
    path.write_text(HEADER + "2026-09-17T01:00:00.000000Z,-31.98,115.82,,,,0,\n" + "2026-09-17T01:00:05.0000")
    make_repo(tmp_path).add_positions([pos(seconds=10)])
    rows = make_repo(tmp_path).get_positions(["1"])["1"]
    assert [p.timestamp.second for p in rows] == [0, 10]


def test_replaced_file_is_read_from_the_start(tmp_path):
    repo = make_repo(tmp_path)
    repo.add_positions([pos(seconds=i) for i in range(5)])
    assert len(repo.get_positions(["1"])["1"]) == 5

    other = make_repo(tmp_path / "other")
    other.add_positions([pos(seconds=100 + i) for i in range(8)])
    os.replace(tmp_path / "other" / "positions_1.csv", tmp_path / "positions_1.csv")

    rows = repo.get_positions(["1"])["1"]
    assert [p.timestamp for p in rows] == [T0 + timedelta(seconds=100 + i) for i in range(8)]


def test_truncated_file_is_read_from_the_start(tmp_path):
    repo = make_repo(tmp_path)
    repo.add_positions([pos(seconds=i) for i in range(5)])
    repo.get_positions()
    path = tmp_path / "positions_1.csv"
    path.write_text(HEADER + "2026-09-17T02:00:00.000000Z,-31.5,115.5,,,,0,\n")
    rows = repo.get_positions(["1"])["1"]
    assert len(rows) == 1 and rows[0].latitude == -31.5


def test_deleted_file_reads_empty(tmp_path):
    repo = make_repo(tmp_path)
    repo.add_positions([pos()])
    repo.get_positions()
    (tmp_path / "positions_1.csv").unlink()
    assert repo.get_positions(["1"]) == {"1": []}


def test_header_only_and_missing_files_read_empty(tmp_path):
    (tmp_path / "positions_1.csv").write_text(HEADER)
    (tmp_path / "positions_2.csv").write_text("timestamp,lat")  # header still being written
    assert make_repo(tmp_path).get_positions() == {"1": [], "2": []}


def test_sample_data_reads_as_before():
    config = load_config()
    tracks = CsvRepository(config.data_directory, config.vehicles).get_positions()
    assert len(tracks["1"]) == 439
    assert len(tracks["2"]) == 220
    assert sum(p.gps_status == -1 for p in tracks["1"]) == 2
    assert all(p.latitude is None for p in tracks["1"] if p.gps_status == -1)
    assert tracks["1"][0].timestamp == datetime(2025, 9, 4, 8, 21, 10, 484987, tzinfo=timezone.utc)


def test_stores_are_read_only_by_default():
    class ReadOnly(Repository):
        def vehicle_ids(self):
            return []

        def get_positions(self, vehicle_ids=None, start=None, end=None):
            return {}

        def get_latest_positions(self, vehicle_ids=None):
            return {}

    with pytest.raises(NotImplementedError):
        ReadOnly().add_positions([pos()])
