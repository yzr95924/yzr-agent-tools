"""Tests for --driver selection across commands."""
import json
from pathlib import Path

import pytest


from model_switch.drivers.base import registry
from model_switch.drivers.claude_code import ClaudeCodeDriver
from model_switch.drivers.opencode import OpenCodeDriver

from _cli_runner import invoke_cli as runner





@pytest.fixture
def two_drivers(tmp_path: Path, monkeypatch):
    """Register both drivers, each pointing at its own tmp path."""
    import model_switch.paths as paths_mod
    monkeypatch.setattr(paths_mod, "config_dir", lambda: tmp_path / "cfg")
    (tmp_path / "cfg").mkdir()
    monkeypatch.setattr(paths_mod, "models_file",
                        lambda: tmp_path / "cfg" / "models.toml")
    monkeypatch.setattr(paths_mod, "state_file",
                        lambda: tmp_path / "cfg" / "state.toml")

    claude_path = tmp_path / ".claude" / "settings.json"
    opencode_path = tmp_path / ".opencode.json"

    # Pre-register so the lazy fallback never touches real paths.
    registry._drivers["claude-code"] = ClaudeCodeDriver(settings_path=claude_path)
    registry._drivers["opencode"] = OpenCodeDriver(settings_path=opencode_path)
    return {"claude": claude_path, "opencode": opencode_path}


def test_model_use_targets_opencode_driver(two_drivers, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    runner([
        "model", "add", "glm",
        "--base-url", "https://api.example.com",
        "--api-key-env", "GLM_API_KEY",
        "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm", "--driver", "opencode"])
    assert result.exit_code == 0, result.stdout

    cfg = json.loads(two_drivers["opencode"].read_text())
    assert cfg["model"] == "yzr/glm-4"
    # Claude Code config must NOT be touched.
    assert not two_drivers["claude"].exists()


def test_model_use_falls_back_to_default_driver_when_unspecified(two_drivers, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    runner([
        "model", "add", "glm",
        "--base-url", "https://api.example.com",
        "--api-key-env", "GLM_API_KEY",
        "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm"])
    assert result.exit_code == 0, result.stdout

    assert two_drivers["claude"].exists()
    assert not two_drivers["opencode"].exists()


def test_unknown_driver_name_errors(two_drivers, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    runner([
        "model", "add", "glm",
        "--base-url", "https://x", "--api-key-env", "GLM_API_KEY",
        "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm", "--driver", "no-such"])
    assert result.exit_code != 0
    assert "no-such" in result.stdout