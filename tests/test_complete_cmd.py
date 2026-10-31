"""Tests for the hidden `_complete models` plumbing command."""
import pytest

from _cli_runner import invoke_cli as runner


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    return _isolate_yzr_state


MODELS_TOML = """\
schema_version = 2

[[models]]
model_id = "glm-z1"
provider = "yzr-zai"
canonical_provider = "zai-coding-plan"
base_url = "https://api.example.com/v1"
api_key = "GLM_API_KEY"

[[models]]
model_id = "kimi-k2"
provider = "yzr-kimi"
canonical_provider = "kimi-code-plan-cn"
base_url = "https://api.kimi.example.com/v1"
api_key = "MOONSHOT_API_KEY"
"""


def _seed(yzr_paths):
    from pathlib import Path
    Path(yzr_paths["models"]).write_text(MODELS_TOML)


def test_complete_models_empty_when_no_models(yzr_paths):
    result = runner(["_complete", "models"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.strip() == ""


def test_complete_models_prints_one_ref_per_line(yzr_paths):
    _seed(yzr_paths)
    result = runner(["_complete", "models"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.split() == [
        "yzr-kimi/kimi-k2", "yzr-zai/glm-z1"]


def test_complete_drivers_is_rejected(yzr_paths):
    result = runner(["_complete", "drivers"])
    assert result.exit_code == 2


def test_complete_is_hidden_from_help(yzr_paths):
    result = runner(["--help"])
    assert result.exit_code == 0, result.stdout
    assert "_complete" not in result.stdout
