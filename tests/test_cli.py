"""Tests for the model-switch CLI — end-to-end via the `invoke_cli` helper.

Test isolation (path redirection + integrity checks on real configs) is
handled by the autouse fixture in conftest.py. Tests request the
`yzr_paths` fixture to get the tmp paths (alias for `_isolate_yzr_state`).
"""
import json

import pytest

from model_switch.store import load_models, load_state

from _cli_runner import invoke_cli as runner  # `runner(args, input=...)` mirrors CliRunner


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    """Convenience alias matching the autouse fixture's yielded dict."""
    return _isolate_yzr_state


# --- yzr init -----------------------------------------------------------------

def test_init_creates_config_dir(yzr_paths):
    import shutil
    shutil.rmtree(yzr_paths["config_dir"])

    result = runner(["init"])
    assert result.exit_code == 0, result.stdout
    assert yzr_paths["config_dir"].exists()


# --- yzr model add ------------------------------------------------------------

def test_model_add_creates_entry(yzr_paths):
    result = runner([
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
    """Required options are now prompted. Providing only the prompted
    answers is sufficient to succeed (no flag-only failure)."""
    runner_inv = runner(["model", "add", "glm-z1"], input="\n".join([
        "https://x",  # base_url
        "K",         # api_key_env
        "m",         # model_name
        "",          # context_window default
        "",          # description skip
    ]) + "\n")
    assert runner_inv.exit_code == 0, runner_inv.stdout


def test_model_add_rejects_duplicate(yzr_paths):
    args = [
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key-env", "K",
        "--model-name", "m",
    ]
    runner(args)
    result = runner(args)
    assert result.exit_code != 0
    assert "exists" in result.stdout.lower() or "already" in result.stdout.lower()


# --- yzr model list -----------------------------------------------------------

def test_model_list_empty(yzr_paths):
    result = runner(["model", "list"])
    assert result.exit_code == 0
    assert "no models" in result.stdout.lower() or "(none)" in result.stdout.lower()


def test_model_list_shows_added_models(yzr_paths):
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "m1",
    ])
    runner([
        "model", "add", "other",
        "--base-url", "https://y", "--api-key-env", "K2", "--model-name", "m2",
    ])
    result = runner(["model", "list"])
    assert result.exit_code == 0
    assert "glm-z1" in result.stdout
    assert "other" in result.stdout


def test_model_list_marks_active_main(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake-key")
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "m1",
    ])
    runner(["model", "use", "glm-z1"])
    result = runner(["model", "list"])
    assert result.exit_code == 0
    assert "glm-z1" in result.stdout
    # Active main marker "[active]" should appear next to glm-z1
    assert "[active]" in result.stdout


# --- yzr model show -----------------------------------------------------------

def test_model_show_prints_details(yzr_paths):
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key-env", "EXAMPLE",
        "--model-name", "glm-4",
        "--description", "Main model",
    ])
    result = runner(["model", "show", "glm-z1"])
    assert result.exit_code == 0
    assert "https://x" in result.stdout
    assert "EXAMPLE" in result.stdout
    assert "glm-4" in result.stdout
    assert "Main model" in result.stdout


def test_model_show_errors_for_unknown_model(yzr_paths):
    result = runner(["model", "show", "nope"])
    assert result.exit_code != 0


# --- yzr model remove ---------------------------------------------------------

def test_model_remove(yzr_paths):
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "m",
    ])
    result = runner(["model", "remove", "glm-z1"])
    assert result.exit_code == 0
    cfg = load_models(yzr_paths["models"])
    assert "glm-z1" not in cfg.models


def test_model_remove_errors_for_unknown(yzr_paths):
    result = runner(["model", "remove", "nope"])
    assert result.exit_code != 0


# --- yzr model use ------------------------------------------------------------

def test_model_use_writes_to_settings_and_state(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "test-key")
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://api.example.com",
        "--api-key-env", "K",
        "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm-z1"])
    assert result.exit_code == 0, result.stdout

    settings = json.loads(yzr_paths["settings"].read_text())
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://api.example.com"
    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == "test-key"

    state = load_state(yzr_paths["state"])
    assert state.active_main == "glm-z1"




def test_model_use_errors_when_unknown(yzr_paths):
    result = runner(["model", "use", "nope"])
    assert result.exit_code != 0


def test_model_use_errors_when_api_key_env_unset(yzr_paths, monkeypatch):
    monkeypatch.delenv("K", raising=False)
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key-env", "K",
        "--model-name", "m",
    ])
    result = runner(["model", "use", "glm-z1"])
    assert result.exit_code != 0
    assert "K" in result.stdout or "env" in result.stdout.lower()



# --- yzr status ---------------------------------------------------------------

def test_status_shows_active_and_effective_env(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake")
    runner([
        "model", "add", "big",
        "--base-url", "https://x", "--api-key-env", "K", "--model-name", "big",
    ])
    runner(["model", "use", "big"])

    result = runner(["status"])
    assert result.exit_code == 0, result.stdout
    assert "big" in result.stdout
    assert "ANTHROPIC_BASE_URL" in result.stdout


def test_status_when_no_active_model(yzr_paths):
    result = runner(["status"])
    assert result.exit_code == 0, result.stdout
    assert "no active" in result.stdout.lower() or "inactive" in result.stdout.lower() or "(none)" in result.stdout.lower()