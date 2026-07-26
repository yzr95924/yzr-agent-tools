"""Tests for the yzr Typer CLI — end-to-end via CliRunner.

Test isolation (path redirection + integrity checks on real configs) is
handled by the autouse fixture in conftest.py. Tests request the
`isolate_yzr` fixture to get the tmp paths.
"""
import json

import pytest
from typer.testing import CliRunner

from yzr_agent_tools.cli import app
from yzr_agent_tools.config import load_models, load_state


runner = CliRunner()


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    """Convenience alias matching the autouse fixture's yielded dict."""
    return _isolate_yzr_state


# --- yzr init -----------------------------------------------------------------

def test_init_creates_config_dir(yzr_paths):
    import shutil
    shutil.rmtree(yzr_paths["config_dir"])

    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout
    assert yzr_paths["config_dir"].exists()


# --- yzr model add ------------------------------------------------------------

def test_model_add_creates_entry(yzr_paths):
    result = runner.invoke(app, [
        "model", "add", "glm-z1",
        "--base-url", "https://api.example.com",
        "--api-key-env", "EXAMPLE_KEY",
        "--model-name", "glm-4",
        "--description", "GLM Z1",
    ])
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert "glm-z1" in cfg.models
    assert cfg.models["glm-z1"].base_url == "https://api.example.com"


def test_model_add_requires_all_required_options(yzr_paths):
    result = runner.invoke(app, ["model", "add", "glm-z1"])
    assert result.exit_code != 0


def test_model_add_rejects_duplicate(yzr_paths):
    args = [
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key-env", "K",
        "--model-name", "m",
    ]
    runner.invoke(app, args)
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert "exists" in result.stdout.lower() or "already" in result.stdout.lower()


# --- yzr model list -----------------------------------------------------------

def test_model_list_empty(yzr_paths):
    result = runner.invoke(app, ["model", "list"])
    assert result.exit_code == 0
    assert "no models" in result.stdout.lower() or "(none)" in result.stdout.lower()


def test_model_list_shows_added_models(yzr_paths):
    runner.invoke(app, [
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "m1",
    ])
    runner.invoke(app, [
        "model", "add", "other",
        "--base-url", "https://y", "--api-key-env", "K2", "--model-name", "m2",
    ])
    result = runner.invoke(app, ["model", "list"])
    assert result.exit_code == 0
    assert "glm-z1" in result.stdout
    assert "other" in result.stdout


def test_model_list_marks_active_main(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake-key")
    runner.invoke(app, [
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "m1",
    ])
    runner.invoke(app, ["model", "use", "glm-z1"])
    result = runner.invoke(app, ["model", "list"])
    assert result.exit_code == 0
    assert "glm-z1" in result.stdout
    # Active main marker "[main]" should appear next to glm-z1
    assert "[main" in result.stdout


# --- yzr model show -----------------------------------------------------------

def test_model_show_prints_details(yzr_paths):
    runner.invoke(app, [
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key-env", "EXAMPLE",
        "--model-name", "glm-4",
        "--description", "Main model",
    ])
    result = runner.invoke(app, ["model", "show", "glm-z1"])
    assert result.exit_code == 0
    assert "https://x" in result.stdout
    assert "EXAMPLE" in result.stdout
    assert "glm-4" in result.stdout
    assert "Main model" in result.stdout


def test_model_show_errors_for_unknown_model(yzr_paths):
    result = runner.invoke(app, ["model", "show", "nope"])
    assert result.exit_code != 0


# --- yzr model remove ---------------------------------------------------------

def test_model_remove(yzr_paths):
    runner.invoke(app, [
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "m",
    ])
    result = runner.invoke(app, ["model", "remove", "glm-z1"])
    assert result.exit_code == 0
    cfg = load_models(yzr_paths["models"])
    assert "glm-z1" not in cfg.models


def test_model_remove_errors_for_unknown(yzr_paths):
    result = runner.invoke(app, ["model", "remove", "nope"])
    assert result.exit_code != 0


# --- yzr model use ------------------------------------------------------------

def test_model_use_writes_to_settings_and_state(yzr_paths, monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "test-key")
    runner.invoke(app, [
        "model", "add", "glm-z1",
        "--base-url", "https://api.example.com",
        "--api-key-env", "GLM_API_KEY",
        "--model-name", "glm-4",
    ])
    result = runner.invoke(app, ["model", "use", "glm-z1"])
    assert result.exit_code == 0, result.stdout

    settings = json.loads(yzr_paths["settings"].read_text())
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://api.example.com"
    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == "test-key"

    state = load_state(yzr_paths["state"])
    assert state.active_main == "glm-z1"


def test_model_use_with_small_sets_both(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake")
    runner.invoke(app, [
        "model", "add", "big",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "big",
    ])
    runner.invoke(app, [
        "model", "add", "small",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "small",
    ])
    result = runner.invoke(app, ["model", "use", "big", "--small", "small"])
    assert result.exit_code == 0, result.stdout

    settings = json.loads(yzr_paths["settings"].read_text())
    assert settings["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "big"
    assert settings["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "small"

    state = load_state(yzr_paths["state"])
    assert state.active_main == "big"
    assert state.active_small == "small"


def test_model_use_without_small_defaults_small_to_main(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake")
    runner.invoke(app, [
        "model", "add", "big",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "big",
    ])
    result = runner.invoke(app, ["model", "use", "big"])
    assert result.exit_code == 0, result.stdout

    settings = json.loads(yzr_paths["settings"].read_text())
    # Both Opus and Haiku alias slots receive the main model_name
    assert settings["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "big"
    assert settings["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "big"


def test_model_use_errors_when_unknown(yzr_paths):
    result = runner.invoke(app, ["model", "use", "nope"])
    assert result.exit_code != 0


def test_model_use_errors_when_api_key_env_unset(yzr_paths, monkeypatch):
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    runner.invoke(app, [
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key-env", "GLM_API_KEY",
        "--model-name", "m",
    ])
    result = runner.invoke(app, ["model", "use", "glm-z1"])
    assert result.exit_code != 0
    assert "GLM_API_KEY" in result.stdout or "env" in result.stdout.lower()


# --- yzr small-model ----------------------------------------------------------

def test_small_model_use_sets_only_small(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake")
    runner.invoke(app, [
        "model", "add", "big",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "big",
    ])
    runner.invoke(app, [
        "model", "add", "small",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "small",
    ])
    runner.invoke(app, ["model", "use", "big"])
    result = runner.invoke(app, ["small-model", "use", "small"])
    assert result.exit_code == 0, result.stdout

    state = load_state(yzr_paths["state"])
    assert state.active_main == "big"
    assert state.active_small == "small"

    settings = json.loads(yzr_paths["settings"].read_text())
    assert settings["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "big"
    assert settings["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "small"


def test_small_model_clear_resets_small_to_main(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake")
    runner.invoke(app, [
        "model", "add", "big",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "big",
    ])
    runner.invoke(app, [
        "model", "add", "small",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "small",
    ])
    runner.invoke(app, ["model", "use", "big", "--small", "small"])
    result = runner.invoke(app, ["small-model", "clear"])
    assert result.exit_code == 0, result.stdout

    state = load_state(yzr_paths["state"])
    assert state.active_main == "big"
    assert state.active_small == "big"   # small follows main


# --- yzr status ---------------------------------------------------------------

def test_status_shows_active_and_effective_env(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake")
    runner.invoke(app, [
        "model", "add", "big",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "big",
    ])
    runner.invoke(app, ["model", "use", "big"])

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.stdout
    assert "big" in result.stdout
    assert "ANTHROPIC_BASE_URL" in result.stdout


def test_status_when_no_active_model(yzr_paths):
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.stdout
    assert "no active" in result.stdout.lower() or "inactive" in result.stdout.lower() or "(none)" in result.stdout.lower()