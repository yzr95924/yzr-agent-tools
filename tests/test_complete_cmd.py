"""Tests for the hidden `_complete` plumbing command.

The shell completion scripts (completions/) call
`model-switch _complete models|drivers` and complete from its
one-candidate-per-line stdout. `_complete` is intentionally hidden from
`--help` output.
"""
import pytest

from _cli_runner import invoke_cli as runner  # mirrors CliRunner; see test_cli.py


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    """Convenience alias matching the autouse fixture's yielded dict."""
    return _isolate_yzr_state


def _add_model(name):
    result = runner([
        "model", "add", name,
        "--base-url", "https://api.example.com",
        "--api-key", "EXAMPLE_KEY",
        "--model-name", "some-model",
    ])
    assert result.exit_code == 0, result.stdout


def test_complete_models_empty_when_no_models(yzr_paths):
    result = runner(["_complete", "models"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.strip() == ""


def test_complete_models_prints_one_name_per_line(yzr_paths):
    _add_model("glm-z1")
    _add_model("kimi-k2")
    result = runner(["_complete", "models"])
    assert result.exit_code == 0, result.stdout
    names = result.stdout.split()
    assert "glm-z1" in names
    assert "kimi-k2" in names


def test_complete_drivers_lists_builtin_drivers(yzr_paths):
    result = runner(["_complete", "drivers"])
    assert result.exit_code == 0, result.stdout
    names = result.stdout.split()
    assert "claude-code" in names
    assert "opencode" in names


def test_complete_rejects_unknown_kind(yzr_paths):
    result = runner(["_complete", "bogus"])
    assert result.exit_code == 2  # argparse `choices` error


def test_complete_is_hidden_from_help(yzr_paths):
    result = runner(["--help"])
    assert result.exit_code == 0, result.stdout
    assert "_complete" not in result.stdout
