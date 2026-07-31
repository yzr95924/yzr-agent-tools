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
        "--api-key", "EXAMPLE_KEY",
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
        "K",         # api_key
        "m",         # model_name
        "",          # context_window default
        "",          # description skip
    ]) + "\n")
    assert runner_inv.exit_code == 0, runner_inv.stdout


def test_model_add_rejects_duplicate(yzr_paths):
    args = [
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key", "K",
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
        "--base-url", "https://x", "--api-key", "K", "--model-name", "m1",
    ])
    runner([
        "model", "add", "other",
        "--base-url", "https://y", "--api-key", "K2", "--model-name", "m2",
    ])
    result = runner(["model", "list"])
    assert result.exit_code == 0
    assert "glm-z1" in result.stdout
    assert "other" in result.stdout


def test_model_list_prints_header(yzr_paths):
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "m1",
    ])
    result = runner(["model", "list"])
    assert result.exit_code == 0
    # Header row should label the two columns ("name" alias and "model").
    first_line = result.stdout.splitlines()[0]
    assert "name" in first_line.lower()
    assert "model" in first_line.lower()


def test_model_list_marks_active_main(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake-key")
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "m1",
    ])
    runner(["model", "use", "glm-z1"])
    result = runner(["model", "list"])
    assert result.exit_code == 0
    assert "glm-z1" in result.stdout
    # Active main row should be prefixed with "→", no trailing "[active]".
    glm_row = [ln for ln in result.stdout.splitlines() if "glm-z1" in ln][0]
    assert glm_row.lstrip().startswith("→")
    assert "[active]" not in glm_row


def test_model_list_shows_context_and_base_url(yzr_paths):
    runner([
        "model", "add", "huge",
        "--base-url", "https://api.example.com/v1",
        "--api-key", "K", "--model-name", "m1",
        "--context-window", "200000",
    ])
    runner([
        "model", "add", "small",
        "--base-url", "https://y", "--api-key", "K2", "--model-name", "m2",
        "--context-window", "8000",
    ])
    result = runner(["model", "list"])
    assert result.exit_code == 0
    # Header should advertise the new columns.
    header = result.stdout.splitlines()[0].lower()
    assert "context" in header
    assert "base" in header or "url" in header
    # Context formatted as K/M units when present (200000 → 200K, 8000 → 8K).
    assert "200k" in result.stdout.lower()
    assert "8k" in result.stdout.lower().replace("8000", "") or " 8k " in result.stdout.lower()
    # Base URLs are both visible.
    assert "https://api.example.com/v1" in result.stdout
    assert "https://y" in result.stdout


def test_format_context_renders_none_as_sentinel():
    from model_switch.cli import _format_context
    assert _format_context(None) == "-(none)-"
    assert _format_context(1_000_000) == "1M"
    assert _format_context(200_000) == "200K"
    assert _format_context(8000) == "8K"
    assert _format_context(7) == "7"


def test_model_list_truncates_long_base_url(yzr_paths):
    long_url = "https://example.com/" + ("a" * 80)
    runner([
        "model", "add", "long",
        "--base-url", long_url,
        "--api-key", "K", "--model-name", "m1",
    ])
    result = runner(["model", "list"])
    assert result.exit_code == 0
    # The full URL must not appear verbatim; should be truncated with "…".
    assert long_url not in result.stdout
    assert "…" in result.stdout


# --- yzr model show -----------------------------------------------------------

def test_model_show_prints_details(yzr_paths):
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x",
        "--api-key", "EXAMPLE",
        "--model-name", "glm-4",
        "--description", "Main model",
    ])
    result = runner(["model", "show", "glm-z1"])
    assert result.exit_code == 0
    assert "https://x" in result.stdout
    assert "api_key" in result.stdout.lower()
    assert "<set>" in result.stdout
    assert "glm-4" in result.stdout
    assert "Main model" in result.stdout


def test_model_show_errors_for_unknown_model(yzr_paths):
    result = runner(["model", "show", "nope"])
    assert result.exit_code != 0


# --- yzr model remove ---------------------------------------------------------

def test_model_remove(yzr_paths):
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "m",
    ])
    result = runner(["model", "remove", "glm-z1"])
    assert result.exit_code == 0
    cfg = load_models(yzr_paths["models"])
    assert "glm-z1" not in cfg.models


def test_model_remove_errors_for_unknown(yzr_paths):
    result = runner(["model", "remove", "nope"])
    assert result.exit_code != 0


# --- yzr model use ------------------------------------------------------------

def test_model_use_writes_to_settings_and_state(yzr_paths):
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://api.example.com",
        "--api-key", "test-key",
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


def test_model_use_writes_stored_api_key_to_driver(yzr_paths):
    """`model use` reads the plaintext api_key from models.toml and writes it
    through to the driver — no environment variable involved."""
    from model_switch.store import ModelEntry, Registry, save_models

    reg = Registry()
    reg.models["stored"] = ModelEntry(
        model_id="stored",
        name="glm-5.2",
        base_url="https://api.z.ai/api/anthropic",
        api_key="sk-from-toml",
    )
    save_models(yzr_paths["models"], reg)

    result = runner(["model", "use", "stored", "--driver", "opencode"])
    assert result.exit_code == 0, result.stdout

    written = json.loads(yzr_paths["opencode"].read_text())
    assert written["provider"]["yzr"]["options"]["apiKey"] == "sk-from-toml"



# --- yzr status ---------------------------------------------------------------

def test_status_shows_active_and_effective_env(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake")
    runner([
        "model", "add", "big",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "big",
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