"""
Database interface for the nUWAy GPS tracking dashboard.

Wraps storage/retrieval of GPS fixes (as published by nuway_gps_tracker.py)
behind a small repository API so dashboard/reporting code never touches SQL
directly. Backed by SQLite for now since we don't have access to the real
production DB yet -- once we do, only `_connect()` and the SQL dialect in
`_init_schema()` should need to change; the public methods are the contract
the rest of the dashboard should be built against.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class GPSRecord:
    """One GPS fix, matching the columns in the sample CSVs plus bus_id."""
    bus_id: int
    timestamp: str          # ISO 8601 UTC string, e.g. 2025-09-04T08:21:10.484987Z
    timestamp_unix: int
    latitude: float
    longitude: float
    altitude: float
    heading: float
    speed_mps: float
    gps_status: int
    position_covariance_type: int
    battery_percent: Optional[float] = None

    @classmethod
    def from_csv_row(cls, row: dict, bus_id: int) -> "GPSRecord":
        # battery_percent is blank in the sample data, so treat "" as missing
        return cls(
            bus_id=bus_id,
            timestamp=row["timestamp"],
            timestamp_unix=int(row["timestamp_unix"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            altitude=float(row["altitude"]),
            heading=float(row["heading"]),
            speed_mps=float(row["speed_mps"]),
            gps_status=int(row["gps_status"]),
            position_covariance_type=int(row["position_covariance_type"]),
            battery_percent=float(row["battery_percent"]) if row.get("battery_percent") else None,
        )


class GPSDatabase:
    """Repository for GPS readings. SQLite-backed placeholder for the eventual production DB."""

    def __init__(self, db_path: str = "nuway_gps.db"):
        self.db_path = db_path
        self._conn = self._connect()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS gps_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                timestamp_unix INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                altitude REAL,
                heading REAL,
                speed_mps REAL,
                gps_status INTEGER,
                position_covariance_type INTEGER,
                battery_percent REAL,
                UNIQUE(bus_id, timestamp)
            )
        """)
        # Supports the two access patterns the dashboard needs: latest fix per bus, and time-range scans
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_bus_time ON gps_readings(bus_id, timestamp_unix)")
        self._conn.commit()

    # -- Ingestion ---------------------------------------------------------

    def insert_record(self, record: GPSRecord) -> None:
        self.insert_many([record])

    def insert_many(self, records: list[GPSRecord]) -> None:
        if not records:
            return
        cols = [f.name for f in fields(records[0])]
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT OR IGNORE INTO gps_readings ({', '.join(cols)}) VALUES ({placeholders})"
        self._conn.executemany(sql, [[getattr(r, c) for c in cols] for r in records])
        self._conn.commit()

    def load_csv(self, csv_path: str, bus_id: int) -> int:
        """Bulk-load a sample CSV (full-rate or 5s-decimated, same schema either way). Returns row count."""
        with open(csv_path, newline="") as f:
            records = [GPSRecord.from_csv_row(row, bus_id) for row in csv.DictReader(f)]
        self.insert_many(records)
        return len(records)

    # -- Queries -------------------------------------------------------------

    def get_latest_position(self, bus_id: int) -> Optional[GPSRecord]:
        row = self._conn.execute(
            "SELECT * FROM gps_readings WHERE bus_id = ? ORDER BY timestamp_unix DESC LIMIT 1",
            (bus_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def get_track(self, bus_id: int, start_unix: Optional[int] = None, end_unix: Optional[int] = None) -> list[GPSRecord]:
        """Ordered fixes for a bus, optionally bounded by a unix timestamp range. Works for either sample rate."""
        sql = "SELECT * FROM gps_readings WHERE bus_id = ?"
        params: list = [bus_id]
        if start_unix is not None:
            sql += " AND timestamp_unix >= ?"
            params.append(start_unix)
        if end_unix is not None:
            sql += " AND timestamp_unix <= ?"
            params.append(end_unix)
        sql += " ORDER BY timestamp_unix ASC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_active_buses(self, since_unix: Optional[int] = None) -> list[int]:
        """Distinct bus_ids on record, optionally restricted to ones reporting since a given time."""
        sql = "SELECT DISTINCT bus_id FROM gps_readings"
        params: list = []
        if since_unix is not None:
            sql += " WHERE timestamp_unix >= ?"
            params.append(since_unix)
        return [r["bus_id"] for r in self._conn.execute(sql, params).fetchall()]

    def get_battery_history(self, bus_id: int, start_unix: Optional[int] = None, end_unix: Optional[int] = None) -> list[tuple[int, float]]:
        """(timestamp_unix, battery_percent) pairs, skipping fixes where battery wasn't reported."""
        return [
            (r.timestamp_unix, r.battery_percent)
            for r in self.get_track(bus_id, start_unix, end_unix)
            if r.battery_percent is not None
        ]

    # -- Helpers ---------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> GPSRecord:
        data = dict(row)
        data.pop("id", None)
        return GPSRecord(**data)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "GPSDatabase":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


if __name__ == "__main__":
    # Smoke test against the two sample CSVs. Different bus_ids used here purely to keep
    # the full-rate and 5s-decimated files distinguishable -- in production each bus_id
    # will have exactly one feed.
    with GPSDatabase("nuway_gps_dev.db") as db:
        n_full = db.load_csv("rtkfull-gps-track-full.csv", bus_id=1)
        n_5s = db.load_csv("rtkfull-gps-track-5s.csv", bus_id=2)
        print(f"Loaded {n_full} full-rate rows (bus 1), {n_5s} 5s-decimated rows (bus 2)")
        print("Latest fix, bus 1:", db.get_latest_position(bus_id=1))
        print("Active buses:", db.get_active_buses())
