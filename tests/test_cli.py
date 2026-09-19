"""Tests for the model-switch CLI — end-to-end via the `invoke_cli` helper.

Test isolation (path redirection + integrity checks on real configs) is
handled by the autouse fixture in conftest.py. Tests request the
`yzr_paths` fixture to get the tmp paths (alias for `_isolate_yzr_state`).
"""
import json

import pytest

from model_switch.store import load_models, load_state, save_models

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


def test_model_add_provider_flag_pins_group(yzr_paths):
    result = runner([
        "model", "add", "qwen-3_8-flash-1m",
        "--base-url", "https://dashscope.aliyuncs.com/apps/anthropic",
        "--api-key", "K",
        "--model-name", "qwen3.8-flash",
        "--provider", "dashscope",
    ])
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["qwen-3_8-flash-1m"].extra["provider"] == "dashscope"
    assert 'provider = "dashscope"' in yzr_paths["models"].read_text()

    shown = runner(["model", "show", "qwen-3_8-flash-1m"])
    assert "provider:       dashscope" in shown.stdout


def test_model_add_conflicting_provider_is_a_clean_error(yzr_paths):
    """Same declared name with a different upstream must fail with a one-line
    error, not a traceback (the agent config has to exist for sync to run)."""
    first = runner([
        "model", "add", "a",
        "--base-url", "https://a.example/anthropic",
        "--api-key", "K", "--model-name", "m1", "--provider", "gw",
    ])
    assert first.exit_code == 0, first.stdout
    use = runner(["model", "use", "a", "--driver", "opencode"])
    assert use.exit_code == 0, use.stdout

    second = runner([
        "model", "add", "b",
        "--base-url", "https://b.example/anthropic",
        "--api-key", "K", "--model-name", "m2", "--provider", "gw",
    ])
    assert second.exit_code == 1
    assert "Error:" in second.stderr
    assert "Traceback" not in second.stdout


def test_model_add_requires_all_required_options(yzr_paths):
    """Required options are now prompted. Providing only the prompted
    answers is sufficient to succeed (no flag-only failure)."""
    runner_inv = runner(["model", "add", "glm-z1"], input="\n".join([
        "https://x",  # base_url
        "K",         # api_key
        "m",         # model_name
        "",          # context_window default
        "",          # description skip
        "y",         # Proceed?
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
    assert "already exists" in result.stdout


# --- yzr model list -----------------------------------------------------------

def test_model_list_empty(yzr_paths):
    result = runner(["model", "list"])
    assert result.exit_code == 0
    assert "no models configured" in result.stdout


def test_model_list_shows_models_header_and_columns(yzr_paths, monkeypatch):
    monkeypatch.setenv("K", "fake-key")
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "m1",
    ])
    runner([
        "model", "add", "huge",
        "--base-url", "https://api.example.com/v1",
        "--api-key", "K2", "--model-name", "m2",
        "--context-window", "200000",
    ])
    runner([
        "model", "add", "small",
        "--base-url", "https://y", "--api-key", "K3", "--model-name", "m3",
        "--context-window", "8000",
    ])
    runner(["model", "use", "glm-z1"])
    result = runner(["model", "list"])
    assert result.exit_code == 0

    lines = result.stdout.splitlines()
    assert lines[0].split() == ["NAME", "MODEL", "CONTEXT", "BASE_URL"]

    # All rows visible; context rendered in K/M units (200000 → 200K, 8000 → 8K).
    for name in ("glm-z1", "huge", "small"):
        assert name in result.stdout
    assert "200K" in result.stdout
    assert "8K" in result.stdout
    assert "https://api.example.com/v1" in result.stdout
    assert "https://y" in result.stdout

    # The active main row is prefixed with "→", no trailing "[active]".
    glm_row = [ln for ln in lines if "glm-z1" in ln][0]
    assert glm_row.lstrip().startswith("→")
    assert "[active]" not in glm_row


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


def test_format_context_renders_none_as_sentinel():
    from model_switch.cli import _format_context
    assert _format_context(None) == "-(none)-"
    assert _format_context(1_000_000) == "1M"
    assert _format_context(200_000) == "200K"
    assert _format_context(8000) == "8K"
    assert _format_context(7) == "7"


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
    assert written["provider"]["yzr-zai"]["options"]["apiKey"] == "sk-from-toml"


def test_model_use_interactive_default_applies_all_drivers(yzr_paths):
    """Interactive `model use` (TTY) defaults to ALL drivers on Enter —
    switching a model should reach every agent you use."""
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://api.example.com",
        "--api-key", "K", "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm-z1"], input="\n")  # Enter = all
    assert result.exit_code == 0, result.stdout
    # Both agent configs were written.
    claude = json.loads(yzr_paths["settings"].read_text())
    assert claude["env"]["ANTHROPIC_AUTH_TOKEN"] == "K"
    opencode = json.loads(yzr_paths["opencode"].read_text())
    assert opencode["provider"]["yzr-example"]["options"]["apiKey"] == "K"


def test_model_use_interactive_all_keyword(yzr_paths):
    """Typing `all` at the interactive prompt also selects every driver."""
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm-z1"], input="all\n")
    assert result.exit_code == 0, result.stdout
    assert yzr_paths["opencode"].exists()


def test_model_use_interactive_single_driver_scopes(yzr_paths):
    """Naming one driver at the prompt scopes the write to that driver only."""
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm-z1"], input="claude-code\n")
    assert result.exit_code == 0, result.stdout
    assert yzr_paths["settings"].exists()
    # opencode was NOT written — user scoped to claude-code.
    assert not yzr_paths["opencode"].exists()


def test_model_use_all_drivers_flag_writes_both_and_lists_paths(yzr_paths):
    """`--all-drivers` writes every agent and lists each written path
    (regression: the loop variable used to print only the last one)."""
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm-z1", "--all-drivers"])
    assert result.exit_code == 0, result.stdout
    assert yzr_paths["settings"].exists()
    assert yzr_paths["opencode"].exists()
    # Output names every driver it wrote, not just the last one.
    assert "claude-code" in result.stdout
    assert "opencode" in result.stdout


def test_model_use_all_drivers_validates_before_any_write(yzr_paths):
    """A render the second driver would reject must stop the first driver
    from writing too — otherwise one agent ends up switched and the other
    untouched, with state.toml still naming the old model."""
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "glm-4",
    ])
    # Hand-write a modalities value the OpenCode driver rejects locally.
    reg = load_models(yzr_paths["models"])
    reg.models["glm-z1"].extra["modalities"] = {
        "input": ["text", "nonsense"], "output": ["text"]}
    save_models(yzr_paths["models"], reg)

    result = runner(["model", "use", "glm-z1", "--all-drivers"])

    assert result.exit_code == 1
    assert "modalities" in result.stderr
    assert not yzr_paths["settings"].exists()   # claude-code was not written
    assert not yzr_paths["opencode"].exists()
    assert load_state(yzr_paths["state"]).active_main is None


def test_model_use_non_tty_defaults_to_claude_code_only(yzr_paths):
    """Non-interactive (no TTY) `model use` stays scoped to the default
    driver (claude-code) — CI scripts keep their old single-agent behavior."""
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm-z1"])  # no input => non-TTY
    assert result.exit_code == 0, result.stdout
    assert yzr_paths["settings"].exists()
    assert not yzr_paths["opencode"].exists()


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
    assert "active main:  (none)" in result.stdout


def test_status_survives_an_active_model_deleted_by_hand(yzr_paths):
    """state.toml can outlive a hand-deleted entry; status is read-only and
    must answer instead of raising KeyError."""
    runner([
        "model", "add", "big",
        "--base-url", "https://x", "--api-key", "K", "--model-name", "big",
    ])
    runner(["model", "use", "big"])
    yzr_paths["models"].write_text("", encoding="utf-8")  # remove entry by hand

    result = runner(["status"])
    assert result.exit_code == 0, result.stdout
    assert "active main:  big (missing from models.toml)" in result.stdout


def test_corrupt_models_toml_fails_with_one_line(yzr_paths):
    """A malformed models.toml is a user error: exit 1 + message, not a
    traceback escaping past the store's StoreError."""
    yzr_paths["models"].write_text('[[models]]\nmodel_id = "m"\n# no name\n',
                                   encoding="utf-8")

    result = runner(["model", "list"])
    assert result.exit_code == 1
    assert "Error:" in result.stderr
    assert "name" in result.stderr
    assert "Traceback" not in result.stderr

# --- interactive pickers (name omitted) ---------------------------------------

def _seed_two(yzr_paths):
    runner(["model", "add", "first", "--base-url", "https://a",
            "--api-key", "K1", "--model-name", "m1"])
    runner(["model", "add", "second", "--base-url", "https://b",
            "--api-key", "K2", "--model-name", "m2"])


def test_use_without_name_picks_from_a_menu(yzr_paths):
    _seed_two(yzr_paths)
    result = runner(["model", "use"], input="2\n\n")  # pick #2, Enter = all drivers
    assert result.exit_code == 0, result.stdout
    assert "Configured models:" in result.stdout
    assert load_state(yzr_paths["state"]).active_main == "second"


def test_show_without_name_picks_from_a_menu(yzr_paths):
    _seed_two(yzr_paths)
    result = runner(["model", "show"], input="1\n")
    assert result.exit_code == 0, result.stdout
    assert "https://a" in result.stdout


def test_remove_without_name_confirmation_defaults_to_no(yzr_paths):
    _seed_two(yzr_paths)
    result = runner(["model", "remove"], input="1\n\n")  # pick #1, Enter = no
    assert result.exit_code != 0
    assert "Aborted — nothing removed." in result.stdout
    assert set(load_models(yzr_paths["models"]).models) == {"first", "second"}


def test_remove_without_name_confirmed_removes(yzr_paths):
    _seed_two(yzr_paths)
    result = runner(["model", "remove"], input="2\ny\n")
    assert result.exit_code == 0, result.stdout
    assert set(load_models(yzr_paths["models"]).models) == {"first"}


def test_remove_yes_skips_the_confirmation(yzr_paths):
    _seed_two(yzr_paths)
    result = runner(["model", "remove", "--yes"], input="1\n")
    assert result.exit_code == 0, result.stdout
    assert "Remove model" not in result.stdout
    assert set(load_models(yzr_paths["models"]).models) == {"second"}


@pytest.mark.parametrize("action", ["use", "remove", "show"])
def test_picker_without_a_tty_fails_cleanly(yzr_paths, action):
    result = runner(["model", action])  # no input => non-TTY
    assert result.exit_code != 0
    assert "no TTY" in result.stdout


def test_add_without_flags_non_tty_fails_cleanly(yzr_paths):
    result = runner(["model", "add"])
    assert result.exit_code != 0
    assert "no TTY" in result.stdout


def test_model_use_eof_at_driver_prompt_applies_all(yzr_paths):
    """A stream that ran out (or Ctrl-D) at the driver prompt behaves like
    Enter — every driver — instead of raising EOFError."""
    runner([
        "model", "add", "glm-z1",
        "--base-url", "https://api.example.com",
        "--api-key", "K", "--model-name", "glm-4",
    ])
    result = runner(["model", "use", "glm-z1"], input="")  # EOF at driver prompt
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout
    assert yzr_paths["settings"].exists()
    assert yzr_paths["opencode"].exists()
