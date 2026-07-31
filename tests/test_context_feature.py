"""Tests for context_window + per-driver model-name strategy."""
import json
from pathlib import Path

import pytest

from model_switch.store import ModelEntry as Model
from model_switch.drivers.claude_code import ClaudeCodeDriver
from model_switch.drivers.opencode import OpenCodeDriver


# --- helpers -----------------------------------------------------------------

@pytest.fixture
def glm_main() -> Model:
    return Model(
        model_id="glm",
        base_url="https://api.example.com",
        api_key="KEY",
        name="MiniMax-M3",
        context_window=1000000,
    )


    return Model(
        model_id="glm",
        base_url="https://api.example.com",
        api_key="KEY",
        name="MiniMax-M3",
    )


def _make_claude_driver(tmp_path: Path, monkeypatch) -> ClaudeCodeDriver:
    monkeypatch.setenv("HOME", str(tmp_path))
    d = ClaudeCodeDriver()
    d.settings_path = tmp_path / ".claude" / "settings.json"
    return d


def _make_opencode_driver(tmp_path: Path, monkeypatch) -> OpenCodeDriver:
    monkeypatch.setenv("HOME", str(tmp_path))
    d = OpenCodeDriver()
    d.settings_path = tmp_path / ".opencode.json"
    return d


# --- ClaudeCodeDriver: [1m] suffix + ANTHROPIC_MODEL + top-level model -------




def test_opencode_does_not_append_1m_suffix(tmp_path, monkeypatch, glm_main):
    """OpenCode keeps the model id bare (no [1m] suffix); context_window is
    not surfaced to OpenCode (its limit schema requires output we don't track)."""
    monkeypatch.setenv("KEY", "k")
    d = _make_opencode_driver(tmp_path, monkeypatch)
    d.apply(model=glm_main, api_key="k")

    written = json.loads(d.settings_path.read_text())
    assert written["model"] == "yzr/MiniMax-M3"
    provider = written["provider"]["yzr"]
    assert "MiniMax-M3[1m]" not in json.dumps(provider)


# --- Model serialization ----------------------------------------------------

def test_model_context_window_roundtrip(tmp_path):
    from model_switch.store import save_models, load_models, Registry
    cfg_p = tmp_path / "models.toml"

    reg = Registry()
    reg.models["m1"] = Model(
        model_id="m1", base_url="x", api_key="K", name="m", context_window=200000,
    )
    reg.models["m2"] = Model(
        model_id="m2", base_url="y", api_key="K2", name="n",
    )
    save_models(cfg_p, reg)
    loaded = load_models(cfg_p)

    assert loaded.models["m1"].context_window == 200000
    assert loaded.models["m2"].context_window is None