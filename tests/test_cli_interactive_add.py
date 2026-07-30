"""Tests for interactive prompts in `model add`."""
import pytest


from model_switch.store import load_models

from _cli_runner import invoke_cli as runner





@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    return _isolate_yzr_state


def _add_with_input(extra_args, inputs):
    """Invoke `model add <name>` with extra CLI args and stdin input lines."""
    args = ["model", "add", "demo"] + extra_args
    return runner(args, input="\n".join(inputs) + "\n")


# --- non-interactive: full flags still works (back-compat) ------------------

def test_add_with_all_flags_does_not_prompt(yzr_paths):
    result = runner([
        "model", "add", "glm",
        "--base-url", "https://x",
        "--api-key-env", "KEY",
        "--model-name", "m",
        "--context-window", "1000000",
    ])
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["glm"].context_window == 1000000


# --- interactive prompts -----------------------------------------------------

def test_add_prompts_for_missing_base_url(yzr_paths):
    result = _add_with_input(
        ["--api-key-env", "KEY", "--model-name", "m"],
        ["https://api.example.com"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].base_url == "https://api.example.com"


def test_add_prompts_for_missing_api_key_env(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--model-name", "m"],
        ["API_KEY"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].api_key_env == "API_KEY"


def test_add_prompts_for_missing_model_name(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key-env", "KEY"],
        ["MiniMax-M3"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].name == "MiniMax-M3"


def test_add_prompts_for_context_window_with_default(yzr_paths):
    """context_window prompt shows a 200000 default; pressing Enter accepts it."""
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key-env", "KEY", "--model-name", "m"],
        [""],  # accept default
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].context_window == 200000


def test_add_prompts_for_context_window_with_explicit_value(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key-env", "KEY", "--model-name", "m"],
        ["1000000"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].context_window == 1000000


def test_add_prompts_for_description_optional(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key-env", "KEY", "--model-name", "m",
         "--context-window", "200000"],
        [""],  # accept empty default
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].description in (None, "")


def test_add_prompts_for_all_when_nothing_provided(yzr_paths):
    """Worst case: name only on CLI, everything else prompted in order."""
    result = _add_with_input(
        [],
        [
            "https://api.minimaxi.com/anthropic",  # base_url
            "MiniMax_API_KEY",                     # api_key_env
            "MiniMax-M3",                          # model_name
            "1000000",                             # context_window
            "",                                    # description (skip)
        ],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    m = cfg.models["demo"]
    assert m.base_url == "https://api.minimaxi.com/anthropic"
    assert m.api_key_env == "MiniMax_API_KEY"
    assert m.name == "MiniMax-M3"
    assert m.context_window == 1000000