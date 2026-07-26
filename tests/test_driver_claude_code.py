"""Tests for Claude Code driver — reads/writes ~/.claude/settings.json."""
import json
from pathlib import Path

import pytest

from yzr_agent_tools.config import Model
from yzr_agent_tools.drivers.claude_code import ClaudeCodeDriver


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
        base_url="https://open.bigmodel.cn/api/anthropic",
        api_key_env="GLM_API_KEY",
        model_name="glm-4-plus",
        description="GLM-4 Plus",
    )


@pytest.fixture
def glm_small() -> Model:
    return Model(
        base_url="https://open.bigmodel.cn/api/anthropic",
        api_key_env="GLM_API_KEY",
        model_name="glm-4-flash",
        description="GLM-4 Flash",
    )


# --- read ---------------------------------------------------------------------

def test_read_returns_empty_dict_when_file_missing(driver):
    assert driver.read() == {}


def test_read_returns_empty_dict_when_file_is_empty_json(driver):
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text("{}")
    assert driver.read() == {}


def test_read_returns_parsed_settings(driver):
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text(json.dumps({"theme": "dark", "env": {"FOO": "bar"}}))
    assert driver.read() == {"theme": "dark", "env": {"FOO": "bar"}}


# --- apply --------------------------------------------------------------------

def test_apply_writes_all_five_env_vars(driver, glm_main, glm_small, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "test-key-123")
    driver.apply(main=glm_main, small=glm_small, api_key="test-key-123")

    written = json.loads(driver.settings_path.read_text())
    assert written["env"] == {
        "ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "test-key-123",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-4-plus",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-4-plus",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-4-flash",
    }


def test_apply_creates_parent_directories(driver, glm_main, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    assert not driver.settings_path.parent.exists()
    driver.apply(main=glm_main, small=glm_main, api_key="k")
    assert driver.settings_path.exists()


def test_apply_preserves_unrelated_top_level_keys(driver, glm_main, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text(json.dumps({
        "theme": "dark",
        "preferredNotifChannel": "iterm2",
    }))
    driver.apply(main=glm_main, small=glm_main, api_key="k")

    written = json.loads(driver.settings_path.read_text())
    assert written["theme"] == "dark"
    assert written["preferredNotifChannel"] == "iterm2"
    assert "env" in written


def test_apply_preserves_unrelated_env_keys(driver, glm_main, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text(json.dumps({
        "env": {"DISABLE_TELEMETRY": "1", "FOO": "bar"},
    }))
    driver.apply(main=glm_main, small=glm_main, api_key="k")

    written = json.loads(driver.settings_path.read_text())
    assert written["env"]["DISABLE_TELEMETRY"] == "1"
    assert written["env"]["FOO"] == "bar"
    assert written["env"]["ANTHROPIC_BASE_URL"] == "https://open.bigmodel.cn/api/anthropic"


def test_apply_overwrites_old_yzr_keys_but_keeps_others(driver, glm_main, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "k")
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text(json.dumps({
        "env": {
            "ANTHROPIC_BASE_URL": "https://old.example.com",
            "ANTHROPIC_AUTH_TOKEN": "old-key",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "old-model",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "old-small",
            "DISABLE_TELEMETRY": "1",
        }
    }))
    driver.apply(main=glm_main, small=glm_main, api_key="new-key")

    written = json.loads(driver.settings_path.read_text())
    assert written["env"]["ANTHROPIC_BASE_URL"] == "https://open.bigmodel.cn/api/anthropic"
    assert written["env"]["ANTHROPIC_AUTH_TOKEN"] == "new-key"
    assert written["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-4-plus"
    assert written["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "glm-4-plus"
    assert written["env"]["DISABLE_TELEMETRY"] == "1"


def test_apply_is_atomic_no_partial_file_on_failure(driver, glm_main, monkeypatch):
    """If write fails mid-way, the original file (if any) must remain intact."""
    monkeypatch.setenv("GLM_API_KEY", "k")
    driver.settings_path.parent.mkdir(parents=True)
    original = json.dumps({"env": {"FOO": "preserve-me"}})
    driver.settings_path.write_text(original)

    # Simulate failure during write of the temp file by patching json.dump
    # (the driver uses json.dump, not json.dumps).
    import yzr_agent_tools.drivers.claude_code as cc_module
    orig_dump = cc_module.json.dump
    def boom(*args, **kwargs):
        raise IOError("simulated disk full")
    cc_module.json.dump = boom
    try:
        with pytest.raises(IOError):
            driver.apply(main=glm_main, small=glm_main, api_key="k")
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