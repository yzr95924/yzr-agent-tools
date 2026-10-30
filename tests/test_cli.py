"""CLI tests for the canonical-alias model registry."""
import json
from pathlib import Path

import pytest

from _cli_runner import invoke_cli as runner
from _catalog_db import write_catalog_db
from model_switch._compat import toml_loads


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    return _isolate_yzr_state


BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ZAI_BASE = "https://api.z.ai/api/coding/paas/v4"


def _catalog():
    return {
        "alibaba-cn": {"models": {
            "glm-5.3": {"type": "chat", "api": {"chat-completions": {
                "base_url": BASE,
                "sdk": {"opencodeai": "@opencode/ai/providers/alibaba/chat"},
            }}},
            "qwen3.8-flash": {"type": "chat", "api": {"chat-completions": {
                "base_url": BASE,
                "sdk": {"opencodeai": "@opencode/ai/providers/alibaba/chat"},
            }}},
        }},
        "zai": {"models": {"glm-5.3": {"type": "chat", "api": {
            "chat-completions": {
                "base_url": ZAI_BASE,
                "sdk": {"opencodeai": "@opencode/ai/providers/zai/chat"},
            }}}}},
        "zai-coding-plan": {"models": {"glm-5.3": {"type": "chat", "api": {
            "chat-completions": {
                "base_url": ZAI_BASE,
                "sdk": {
                    "opencodeai": "@opencode/ai/providers/zai-coding-plan/chat",
                },
            }}}}},
    }


@pytest.fixture(autouse=True)
def catalog_db(yzr_paths):
    write_catalog_db(Path(yzr_paths["catalog"]), _catalog())


def _add_model(yzr_paths, ref="yzr-dashscope/glm-5.3", extra=None):
    args = ["model", "add", ref, "--api-key", "SECRET",
            "--catalog-provider", "alibaba-cn", "--yes"]
    if extra:
        args.extend(extra)
    result = runner(args)
    assert result.exit_code == 0, result.stdout
    return result


def test_model_add_writes_registry_and_renders_canonical_alias(yzr_paths):
    _add_model(yzr_paths)
    reg = toml_loads(Path(yzr_paths["models"]).read_text())
    assert reg["models"] == [{
        "model_id": "glm-5.3",
        "provider": "yzr-dashscope",
        "canonical_provider": "alibaba-cn",
        "base_url": BASE,
        "api_key": "SECRET",
    }]

    data = json.loads(Path(yzr_paths["opencode"]).read_text())
    provider = data["providers"]["yzr-dashscope"]
    assert provider["canonical"] == "alibaba-cn"
    assert provider["models"] == {"glm-5.3": {}}
    assert "package" not in provider
    assert "model" not in data


def test_model_add_reuses_existing_provider_group(yzr_paths):
    _add_model(yzr_paths)
    result = runner(["model", "add", "yzr-dashscope/qwen3.8-flash", "--yes"])
    assert result.exit_code == 0, result.stdout
    reg = toml_loads(Path(yzr_paths["models"]).read_text())
    assert {m["model_id"] for m in reg["models"]} == {
        "glm-5.3", "qwen3.8-flash"}
    assert {m["api_key"] for m in reg["models"]} == {"SECRET"}


def test_model_add_requires_api_key_for_new_provider(yzr_paths):
    result = runner(["model", "add", "yzr-dashscope/glm-5.3", "--yes"])
    assert result.exit_code == 1
    assert "--api-key" in result.stdout


def test_model_add_ambiguous_canonical_requires_pin(yzr_paths):
    result = runner(["model", "add", "yzr-zai/glm-5.3",
                     "--api-key", "SECRET", "--yes"])
    assert result.exit_code == 1
    assert "--catalog-provider" in result.stdout

    result = runner(["model", "add", "yzr-zai/glm-5.3",
                     "--api-key", "SECRET",
                     "--catalog-provider", "zai-coding-plan", "--yes"])
    assert result.exit_code == 0, result.stdout
    reg = toml_loads(Path(yzr_paths["models"]).read_text())
    assert reg["models"][0]["canonical_provider"] == "zai-coding-plan"
    assert reg["models"][0]["base_url"] == ZAI_BASE


@pytest.mark.parametrize("ref", ["no-slash", "dashscope/glm-5.3"])
def test_model_add_rejects_bad_references(yzr_paths, ref):
    result = runner(["model", "add", ref, "--api-key", "K", "--yes"])
    assert result.exit_code == 1


def test_model_use_sets_active_model_and_pointer(yzr_paths):
    _add_model(yzr_paths)
    result = runner(["model", "use", "yzr-dashscope/glm-5.3"])
    assert result.exit_code == 0, result.stdout
    assert 'active_model = "yzr-dashscope/glm-5.3"' in Path(
        yzr_paths["models"]).read_text()
    cfg = json.loads(Path(yzr_paths["opencode"]).read_text())
    assert cfg["model"] == "yzr-dashscope/glm-5.3"


def test_model_use_unknown_model_fails_without_write(yzr_paths):
    result = runner(["model", "use", "yzr-dashscope/missing"])
    assert result.exit_code == 1
    assert not Path(yzr_paths["opencode"]).exists()


def test_model_list_marks_active_model(yzr_paths):
    _add_model(yzr_paths)
    runner(["model", "use", "yzr-dashscope/glm-5.3"])
    result = runner(["model", "list"])
    assert result.exit_code == 0, result.stdout
    assert "yzr-dashscope/glm-5.3" in result.stdout
    assert "alibaba-cn" in result.stdout
    assert "→" in result.stdout


def test_model_show_prints_alias_mapping(yzr_paths):
    _add_model(yzr_paths)
    result = runner(["model", "show", "yzr-dashscope/glm-5.3"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {
        "provider": {
            "canonical_provider": "alibaba-cn",
            "base_url": BASE,
            "api_key": "<set>",
        },
        "model": {"model_id": "glm-5.3"},
    }


def test_model_remove_deletes_model_and_reconciles(yzr_paths):
    _add_model(yzr_paths)
    runner(["model", "use", "yzr-dashscope/glm-5.3"])
    result = runner(["model", "remove", "yzr-dashscope/glm-5.3", "--yes"])
    assert result.exit_code == 0, result.stdout
    reg = toml_loads(Path(yzr_paths["models"]).read_text())
    assert reg["models"] == []
    assert "active_model" not in reg
    cfg = json.loads(Path(yzr_paths["opencode"]).read_text())
    assert "providers" not in cfg
    assert "model" not in cfg


def test_complete_models_prints_refs(yzr_paths):
    _add_model(yzr_paths)
    result = runner(["_complete", "models"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.split() == ["yzr-dashscope/glm-5.3"]
