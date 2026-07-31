"""Tests for Claude Code driver — reads/writes ~/.claude/settings.json."""
import json
from pathlib import Path

import pytest

from model_switch.store import ModelEntry as Model
from model_switch.drivers.claude_code import ClaudeCodeDriver


@pytest.fixture
def driver(tmp_path: Path, monkeypatch) -> ClaudeCodeDriver:
    """Driver that points at a tmp settings.json, not the real one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    d = ClaudeCodeDriver()
    # Override the actual settings.json path to live under tmp_path
    d.settings_path = tmp_path / ".claude" / "settings.json"
    return d


@pytest.fixture
def glm_main() -> Model:
    return Model(
        model_id="glm",
        base_url="https://open.bigmodel.cn/api/anthropic",
        api_key="GLM_API_KEY",
        name="glm-4-plus",
        description="GLM-4 Plus",
    )



# --- read ---------------------------------------------------------------------


def test_apply_is_atomic_no_partial_file_on_failure(driver, glm_main, monkeypatch):
    """If write fails mid-way, the original file (if any) must remain intact."""
    monkeypatch.setenv("GLM_API_KEY", "k")
    driver.settings_path.parent.mkdir(parents=True)
    original = json.dumps({"env": {"FOO": "preserve-me"}})
    driver.settings_path.write_text(original)

    # Simulate failure during write of the temp file by patching json.dump
    # (the driver uses json.dump, not json.dumps).
    import model_switch.drivers.claude_code as cc_module
    orig_dump = cc_module.json.dump
    def boom(*args, **kwargs):
        raise IOError("simulated disk full")
    cc_module.json.dump = boom
    try:
        with pytest.raises(IOError):
            driver.apply(model=glm_main, api_key="k")
    finally:
        cc_module.json.dump = orig_dump

    # Original file content must be unchanged.
    assert driver.settings_path.read_text() == original


# --- current ------------------------------------------------------------------

def test_current_returns_env_block_when_present(driver):
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text(json.dumps({
        "env": {"ANTHROPIC_BASE_URL": "x", "FOO": "bar"}
    }))
    assert driver.current() == {"ANTHROPIC_BASE_URL": "x", "FOO": "bar"}


def test_current_returns_empty_when_no_env_block(driver):
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text(json.dumps({"theme": "dark"}))
    assert driver.current() == {}


def test_current_returns_empty_when_file_missing(driver):
    assert driver.current() == {}


# --- name property ------------------------------------------------------------

def test_driver_name_is_claude_code(driver):
    assert driver.name == "claude-code"