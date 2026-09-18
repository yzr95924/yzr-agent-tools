"""Tests for context_window + per-driver model-name strategy."""
import json
from pathlib import Path

import pytest

from model_switch.store import ModelEntry as Model
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


def _make_opencode_driver(tmp_path: Path, monkeypatch) -> OpenCodeDriver:
    monkeypatch.setenv("HOME", str(tmp_path))
    d = OpenCodeDriver()
    d.settings_path = tmp_path / ".opencode.json"
    return d


# --- OpenCodeDriver: bare model id, no [1m] suffix ---------------------------

def test_opencode_does_not_append_1m_suffix(tmp_path, monkeypatch, glm_main):
    """OpenCode keeps the model id bare — the `[1m]` suffix is a Claude Code
    display convention, not part of the upstream model id."""
    monkeypatch.setenv("KEY", "k")
    d = _make_opencode_driver(tmp_path, monkeypatch)
    d.apply(models=[glm_main], active=glm_main)

    written = json.loads(d.settings_path.read_text())
    assert written["model"] == "yzr-example/MiniMax-M3"
    provider = written["provider"]["yzr-example"]
    assert "MiniMax-M3[1m]" not in json.dumps(provider)