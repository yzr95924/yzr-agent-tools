"""Tests for paths module — pure path resolution functions.

Marked no_isolation because these tests intentionally exercise the real
XDG / HOME resolution; they don't touch any state on disk.
"""
import pytest

from mcp_plugin_mgr.paths import (
    claude_json_file,
    config_dir,
    opencode_config_file,
    servers_file,
)

pytestmark = pytest.mark.no_isolation


def test_config_dir_uses_xdg_config_home_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "mcp-plugin-mgr"


def test_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_dir() == tmp_path / ".config" / "mcp-plugin-mgr"


def test_servers_file_lives_under_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert servers_file() == tmp_path / "mcp-plugin-mgr" / "servers.toml"


def test_claude_json_file_is_home_rooted(monkeypatch, tmp_path):
    # ~/.claude.json lives in HOME, NOT under XDG config (it is not
    # ~/.config/...). Getting this wrong means writes are silently ignored.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert claude_json_file() == tmp_path / ".claude.json"


def test_claude_json_file_ignores_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert claude_json_file() == tmp_path / ".claude.json"


def test_opencode_config_file_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert opencode_config_file() == tmp_path / "opencode" / "opencode.json"
