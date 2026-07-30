"""Tests for OpenCode driver — reads/writes ~/.opencode.json."""
import json
from pathlib import Path

import pytest

from model_switch.store import ModelEntry as Model
from model_switch.drivers.opencode import OpenCodeDriver, PROVIDER_ID


@pytest.fixture
def driver(tmp_path: Path, monkeypatch) -> OpenCodeDriver:
    """Driver that points at a tmp opencode.json, not the real one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    d = OpenCodeDriver()
    d.settings_path = tmp_path / ".opencode.json"
    return d


@pytest.fixture
def glm_main() -> Model:
    return Model(
        model_id="glm",
        base_url="https://open.bigmodel.cn/api/anthropic",
        api_key_env="GLM_API_KEY",
        name="glm-4-plus",
        description="GLM-4 Plus",
    )



# --- read ---------------------------------------------------------------------


def test_current_returns_empty_when_file_missing(driver):
    assert driver.current() == {}


# --- name property ------------------------------------------------------------

def test_driver_name_is_opencode(driver):
    assert driver.name == "opencode"