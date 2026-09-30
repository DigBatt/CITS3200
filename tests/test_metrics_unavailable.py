"""
/api/metrics: a figure the data cannot support is null with a reason, never a
bare null or a zero (#71). The Figures tab shows the reason in its place.
"""

from __future__ import annotations
import shutil

import pytest
import yaml

from backend.app import create_app
from backend.config import DEFAULT_CONFIG_DIR

THURSDAY = {"from": "2025-09-04", "to": "2025-09-04"}  # the sample data's day
SATURDAY = {"from": "2025-09-06", "to": "2025-09-06"}  # no service hours
EMPTY_DAY = {"from": "2020-01-06", "to": "2020-01-06"}  # a Monday with no data


def make_client(config_dir):
    app = create_app(config_dir=config_dir)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def client():
    with make_client(DEFAULT_CONFIG_DIR) as test_client:
        yield test_client


@pytest.fixture
def client_without_service_hours(tmp_path):
    config_dir = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config_dir)
    app_yaml = config_dir / "app.yaml"
    config = yaml.safe_load(app_yaml.read_text(encoding="utf-8"))
    del config["utilisation"]["service_hours"]
    app_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")
    with make_client(config_dir) as test_client:
        yield test_client


def vehicles(client, query):
    response = client.get("/api/metrics", query_string=query)
    assert response.status_code == 200
    return response.get_json()["vehicles"]


def unexplained(entry):
    """Every bucket or KPI that is null without a reason."""
    return [
        f"{group}.{key}"
        for group in ("buckets", "kpis")
        for key, value in entry[group].items()
        if value is None and not entry["unavailable"].get(key)
    ]


@pytest.mark.parametrize("query", [THURSDAY, SATURDAY, EMPTY_DAY], ids=["weekday", "weekend", "no-data"])
def test_every_missing_figure_has_a_reason(client, query):
    for entry in vehicles(client, query):
        assert unexplained(entry) == [], entry["vehicle_id"]


def test_every_missing_figure_has_a_reason_without_service_hours(client_without_service_hours):
    for entry in vehicles(client_without_service_hours, THURSDAY):
        assert unexplained(entry) == [], entry["vehicle_id"]
        assert entry["unavailable"]["unscheduled_seconds"]


def test_a_day_with_no_service_leaves_effective_utilisation_unavailable_not_zero(client):
    for entry in vehicles(client, SATURDAY):
        assert entry["buckets"]["scheduled_seconds"] == 0
        assert entry["kpis"]["effective_utilisation"] is None
        assert entry["unavailable"]["effective_utilisation"] == "no scheduled service time in this window"


def test_figures_the_telemetry_cannot_give_are_unavailable(client):
    blocked = [
        "uptime",
        "mechanical_availability",
        "physical_availability",
        "use_of_availability",
        "production_effectiveness",
        "downtime_seconds",
        "available_seconds",
        "productive_seconds",
    ]
    for entry in vehicles(client, THURSDAY):
        for key in blocked:
            assert entry["unavailable"].get(key), key


def test_supported_figures_are_given_on_a_day_with_data(client):
    # Vehicle 1 has sample positions on the Thursday, inside service hours.
    entry = next(e for e in vehicles(client, THURSDAY) if e["vehicle_id"] == "1")
    for key in ("asset_utilisation", "operating_efficiency", "effective_utilisation"):
        assert entry["kpis"][key] is not None, key
        assert key not in entry["unavailable"], key
