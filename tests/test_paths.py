"""Tests for paths module — pure path resolution functions.

Marked no_isolation because these tests intentionally exercise the real
XDG / HOME resolution; they don't touch any state on disk.
"""
import pytest

from model_switch.paths import (
    catalog_db_file,
    config_dir,
    models_file,
    opencode_config_file,
)

pytestmark = pytest.mark.no_isolation


def test_config_paths_honor_xdg_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "model-switch"
    assert models_file() == tmp_path / "model-switch" / "models.toml"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_dir() == tmp_path / ".config" / "model-switch"
    assert models_file() == tmp_path / ".config" / "model-switch" / (
        "models.toml")


# OpenCode reads its global config from $XDG_CONFIG_HOME/opencode/opencode.json
# (default ~/.config/opencode/opencode.json) — NOT ~/.opencode.json. Getting
# this path wrong means our written config is silently never loaded.


def test_opencode_config_file_honors_xdg_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert opencode_config_file() == tmp_path / "opencode" / "opencode.json"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert opencode_config_file() == (
        tmp_path / ".config" / "opencode" / "opencode.json")


# OpenCode 2.0's models.dev snapshot is a kv row in its SQLite database,
# $XDG_DATA_HOME/opencode/opencode.db (default ~/.local/share/opencode/...).


def test_catalog_db_file_honors_xdg_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert catalog_db_file() == tmp_path / "opencode" / "opencode.db"

    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert catalog_db_file() == (
        tmp_path / ".local" / "share" / "opencode" / "opencode.db")
