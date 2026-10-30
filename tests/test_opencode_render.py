"""Tests for rendering canonical aliases into OpenCode's global config."""
import json

import pytest

from model_switch import opencode
from model_switch.store import StoreError


def _registry(**extra):
    reg = {
        "schema_version": 2,
        "models": [{
            "model_id": "glm-5.3",
            "provider": "yzr-dashscope",
            "canonical_provider": "alibaba-cn",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "SECRET",
        }],
    }
    reg.update(extra)
    return reg


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "opencode.json"
    monkeypatch.setattr(opencode.paths, "opencode_config_file", lambda: path)
    return path


def test_sync_renders_canonical_alias_without_local_overrides(config_path):
    opencode.sync(_registry(active_model="yzr-dashscope/glm-5.3"), create=True)
    cfg = json.loads(config_path.read_text())
    provider = cfg["providers"]["yzr-dashscope"]
    assert set(provider) == {"canonical", "name", "settings", "models"}
    assert provider["canonical"] == "alibaba-cn"
    assert provider["settings"] == {
        "baseURL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "apiKey": "SECRET",
    }
    assert provider["models"] == {"glm-5.3": {}}
    assert cfg["model"] == "yzr-dashscope/glm-5.3"


def test_sync_renders_one_empty_model_entry_per_alias(config_path):
    reg = _registry()
    second = dict(reg["models"][0])
    second["model_id"] = "qwen3.8-flash"
    other = dict(reg["models"][0])
    other.update(provider="yzr-zai", canonical_provider="zai-coding-plan",
                 model_id="glm-5.3",
                 base_url="https://api.z.ai/api/coding/paas/v4",
                 api_key="ZAI_SECRET")
    reg["models"] += [second, other]
    opencode.sync(reg, create=True)
    cfg = json.loads(config_path.read_text())
    assert set(cfg["providers"]) == {"yzr-dashscope", "yzr-zai"}
    assert cfg["providers"]["yzr-dashscope"]["models"] == {
        "glm-5.3": {}, "qwen3.8-flash": {}}
    assert cfg["providers"]["yzr-zai"]["canonical"] == "zai-coding-plan"


def test_sync_preserves_foreign_providers_and_keys(config_path):
    config_path.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "providers": {
            "anthropic": {"settings": {"apiKey": "k"}},
            "pilot-dashscope": {
                "package": "@opencode/ai/providers/openai-compatible"},
        },
        "model": "anthropic/claude-sonnet-5",
        "mcp": {"servers": {"outline": {"type": "remote"}}},
    }))
    opencode.sync(_registry(), create=False)
    cfg = json.loads(config_path.read_text())
    assert cfg["providers"]["anthropic"] == {"settings": {"apiKey": "k"}}
    assert "pilot-dashscope" in cfg["providers"]
    assert cfg["mcp"] == {"servers": {"outline": {"type": "remote"}}}
    assert cfg["model"] == "anthropic/claude-sonnet-5"


def test_sync_reclaims_owned_providers_and_pointer(config_path):
    opencode.sync(_registry(active_model="yzr-dashscope/glm-5.3"), create=True)
    config_path.write_text(json.dumps({
        "providers": {
            "yzr-zai": {"settings": {"apiKey": "old"}},
            "yzr-dashscope": {"settings": {"apiKey": "old"}},
        },
        "model": "yzr-dashscope/glm-5.3",
    }))
    opencode.sync(_registry(), create=False)
    cfg = json.loads(config_path.read_text())
    assert set(cfg["providers"]) == {"yzr-dashscope"}
    assert "model" not in cfg


def test_sync_without_create_leaves_missing_file_alone(tmp_path, monkeypatch):
    path = tmp_path / "opencode.json"
    monkeypatch.setattr(opencode.paths, "opencode_config_file", lambda: path)
    opencode.sync(_registry(), create=False)
    assert not path.exists()


def test_validate_rejects_bad_registry_before_write(tmp_path, monkeypatch):
    path = tmp_path / "opencode.json"
    monkeypatch.setattr(opencode.paths, "opencode_config_file", lambda: path)
    reg = _registry()
    del reg["models"][0]["api_key"]
    with pytest.raises(StoreError):
        opencode.sync(reg, create=True)
    assert not path.exists()
