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
            driver.apply(models=[glm_main], active=glm_main)
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


# --- tier overrides -----------------------------------------------------------

# Claude Code resolves auxiliary calls (Bash safety classifier, title/summary
# generation, ...) through these tier slots. The driver pins every one to our
# model id so they don't leak to a hardcoded Claude id the upstream can't serve.
_TIER_KEYS = (
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
)


def test_apply_pins_all_tiers_to_model_id(driver, glm_main):
    driver.settings_path.parent.mkdir(parents=True)
    driver.apply(models=[glm_main], active=glm_main)

    env = json.loads(driver.settings_path.read_text())["env"]
    for k in _TIER_KEYS:
        assert env[k] == glm_main.name  # glm_main has no context_window -> bare id


def test_apply_tier_keys_get_1m_suffix(driver):
    """Tier keys mirror ANTHROPIC_MODEL's [1m] suffix for 1M-context models."""
    driver.settings_path.parent.mkdir(parents=True)
    big = Model(
        model_id="glm",
        base_url="https://api.example.com",
        api_key="KEY",
        name="glm-4-plus",
        context_window=1_000_000,
    )
    driver.apply(models=[big], active=big)

    env = json.loads(driver.settings_path.read_text())["env"]
    assert env["ANTHROPIC_MODEL"] == "glm-4-plus[1m]"
    for k in _TIER_KEYS:
        assert env[k] == "glm-4-plus[1m]"


def test_apply_clears_old_tier_refs_on_switch(driver, glm_main):
    """Switching models must not leave the previous model's tier values."""
    driver.settings_path.parent.mkdir(parents=True)
    other = Model(
        model_id="other",
        base_url="https://api.example.com",
        api_key="KEY",
        name="other-model",
    )
    driver.apply(models=[other], active=other)
    assert json.loads(driver.settings_path.read_text())["env"][
        "ANTHROPIC_DEFAULT_SONNET_MODEL"
    ] == "other-model"

    driver.apply(models=[glm_main], active=glm_main)
    env = json.loads(driver.settings_path.read_text())["env"]
    for k in _TIER_KEYS:
        assert env[k] == glm_main.name  # no stale "other-model"


def test_apply_preserves_unrelated_keys_with_tiers(driver, glm_main):
    driver.settings_path.parent.mkdir(parents=True)
    driver.settings_path.write_text(
        json.dumps({"env": {"FOO": "keep"}, "userID": "u"})
    )
    driver.apply(models=[glm_main], active=glm_main)

    data = json.loads(driver.settings_path.read_text())
    assert data["env"]["FOO"] == "keep"
    assert data["userID"] == "u"
    assert data["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == glm_main.name


def test_apply_ignores_non_active_models(driver, glm_main):
    """Single-slot: only the active model is rendered; the others are ignored."""
    driver.settings_path.parent.mkdir(parents=True)
    other = Model(
        model_id="other", base_url="https://x", api_key="OTHER", name="other-model"
    )
    driver.apply(models=[other, glm_main], active=glm_main)
    data = json.loads(driver.settings_path.read_text())
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == glm_main.api_key
    assert data["env"]["ANTHROPIC_MODEL"] == glm_main.name


# --- clear --------------------------------------------------------------------


def test_clear_removes_only_owned_keys(driver, glm_main):
    driver.settings_path.parent.mkdir(parents=True)
    driver.apply(models=[glm_main], active=glm_main)
    # Add a user-owned key + top-level field to confirm they survive.
    data = json.loads(driver.settings_path.read_text())
    data["env"]["FOO"] = "keep"
    data["userID"] = "u"
    driver.settings_path.write_text(json.dumps(data))

    driver.clear()
    data = json.loads(driver.settings_path.read_text())
    assert "ANTHROPIC_AUTH_TOKEN" not in data["env"]
    assert "ANTHROPIC_BASE_URL" not in data["env"]
    assert "ANTHROPIC_MODEL" not in data["env"]
    for k in _TIER_KEYS:
        assert k not in data["env"]
    assert "model" not in data
    assert data["env"]["FOO"] == "keep"
    assert data["userID"] == "u"


def test_clear_is_noop_when_file_missing(driver):
    driver.clear()
    assert not driver.settings_path.exists()