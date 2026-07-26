"""Tests for paths module — pure path resolution functions.

Marked no_isolation because these tests intentionally exercise the real
XDG / HOME resolution; they don't touch any state on disk.
"""
import pytest

from yzr_agent_tools.paths import config_dir, models_file, state_file

pytestmark = pytest.mark.no_isolation


def test_config_dir_uses_xdg_config_home_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "yzr-agent-tools"


def test_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_dir() == tmp_path / ".config" / "yzr-agent-tools"


def test_models_file_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert models_file() == tmp_path / "yzr-agent-tools" / "models.yaml"


def test_state_file_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert state_file() == tmp_path / "yzr-agent-tools" / "state.yaml"