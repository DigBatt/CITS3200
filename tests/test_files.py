"""
Storage groundwork for S16-S20: `storage.directory` in config/app.yaml and
backend.files.write_json_atomic.
"""

from __future__ import annotations
import json
import shutil

import pytest
import yaml

from backend.config import DEFAULT_CONFIG_DIR, PROJECT_ROOT, load_config
from backend.files import write_json_atomic


@pytest.fixture
def config_dir(tmp_path):
    for name in ("app.yaml", "vehicles.yaml", "stops.yaml"):
        shutil.copy(DEFAULT_CONFIG_DIR / name, tmp_path / name)
    return tmp_path


def set_storage(config_dir, storage):
    app_config = yaml.safe_load((config_dir / "app.yaml").read_text(encoding="utf-8"))
    if storage is None:
        app_config.pop("storage", None)
    else:
        app_config["storage"] = storage
    (config_dir / "app.yaml").write_text(yaml.safe_dump(app_config, sort_keys=False), encoding="utf-8")


# ---- storage.directory ----


def test_committed_config_keeps_storage_under_data():
    assert load_config().storage_directory == PROJECT_ROOT / "data" / "admin"


def test_relative_storage_directory_resolves_against_project_root(config_dir):
    set_storage(config_dir, {"directory": "somewhere/else"})
    assert load_config(config_dir).storage_directory == PROJECT_ROOT / "somewhere" / "else"


def test_absolute_storage_directory_is_kept(config_dir, tmp_path):
    set_storage(config_dir, {"directory": str(tmp_path / "store")})
    assert load_config(config_dir).storage_directory == tmp_path / "store"


def test_missing_storage_block_is_none(config_dir):
    set_storage(config_dir, None)
    assert load_config(config_dir).storage_directory is None


# ---- write_json_atomic ----


def test_writes_json_that_reads_back(tmp_path):
    path = tmp_path / "records.json"
    write_json_atomic(path, {"version": 1, "records": [{"id": "a"}]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1, "records": [{"id": "a"}]}


def test_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "admin" / "snapshots" / "2026-10-01.json"
    write_json_atomic(path, {})
    assert path.exists()


def test_replaces_an_existing_file(tmp_path):
    path = tmp_path / "records.json"
    write_json_atomic(path, {"n": 1})
    write_json_atomic(path, {"n": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"n": 2}


def test_failed_write_leaves_the_old_file_and_no_temp_file(tmp_path):
    path = tmp_path / "records.json"
    write_json_atomic(path, {"n": 1})
    with pytest.raises(TypeError):
        write_json_atomic(path, {"n": object()})
    assert json.loads(path.read_text(encoding="utf-8")) == {"n": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["records.json"]
