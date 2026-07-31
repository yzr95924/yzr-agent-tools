"""Tests for paths module — pure path resolution functions.

Marked no_isolation because these tests intentionally exercise the real
XDG / HOME resolution; they don't touch any state on disk.
"""
import pytest

from model_switch.paths import config_dir, models_file, opencode_config_file, state_file

pytestmark = pytest.mark.no_isolation


def test_config_dir_uses_xdg_config_home_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "model-switch"


def test_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_dir() == tmp_path / ".config" / "model-switch"


def test_models_file_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert models_file() == tmp_path / "model-switch" / "models.toml"


def test_state_file_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert state_file() == tmp_path / "model-switch" / "state.toml"


# OpenCode reads its global config from $XDG_CONFIG_HOME/opencode/opencode.json
# (default ~/.config/opencode/opencode.json) — NOT ~/.opencode.json. Getting
# this path wrong means our written config is silently never loaded.


def test_opencode_config_file_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert opencode_config_file() == tmp_path / "opencode" / "opencode.json"


def test_opencode_config_file_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert opencode_config_file() == tmp_path / ".config" / "opencode" / "opencode.json"