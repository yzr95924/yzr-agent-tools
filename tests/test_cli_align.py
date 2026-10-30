"""Tests for `model align` as a canonical-source drift check."""
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


def _catalog(route="chat-completions"):
    return {
        "alibaba-cn": {"models": {
            "glm-5.3": {
                "type": "chat",
                "api": {
                    route: {
                        "base_url": BASE,
                        "sdk": {
                            "opencodeai":
                                "@opencode/ai/providers/alibaba/chat",
                        },
                    },
                },
            },
        }},
    }


def _seed(yzr_paths, base=BASE, route="chat-completions"):
    reg = """\
schema_version = 2

[[models]]
model_id = "glm-5.3"
provider = "yzr-dashscope"
canonical_provider = "alibaba-cn"
base_url = "{base}"
api_key = "SECRET"
""".format(base=base)
    Path(yzr_paths["models"]).write_text(reg)
    Path(yzr_paths["opencode"]).parent.mkdir(parents=True, exist_ok=True)
    Path(yzr_paths["opencode"]).write_text(json.dumps({
        "providers": {
            "yzr-dashscope": {
                "canonical": "alibaba-cn",
                "settings": {"baseURL": base, "apiKey": "SECRET"},
                "models": {"glm-5.3": {}},
            },
        },
    }))
    write_catalog_db(Path(yzr_paths["catalog"]), _catalog(route))


def test_align_reports_a_matching_source(yzr_paths):
    _seed(yzr_paths)
    result = runner(["model", "align"])
    assert result.exit_code == 0, result.stdout
    assert "ok" in result.stdout
    assert "alibaba-cn" in result.stdout


def test_align_updates_a_drifted_base_url(yzr_paths):
    _seed(yzr_paths, base="https://old.example/v1")
    result = runner(["model", "align"])
    assert result.exit_code == 0, result.stdout
    reg = toml_loads(Path(yzr_paths["models"]).read_text())
    assert reg["models"][0]["base_url"] == BASE
    cfg = json.loads(Path(yzr_paths["opencode"]).read_text())
    assert cfg["providers"]["yzr-dashscope"]["settings"]["baseURL"] == BASE


def test_align_reports_missing_canonical_models(yzr_paths):
    _seed(yzr_paths)
    path = Path(yzr_paths["models"])
    path.write_text(path.read_text() + """
[[models]]
model_id = "unknown-model"
provider = "yzr-dashscope"
canonical_provider = "alibaba-cn"
base_url = "{}"
api_key = "SECRET"
""".format(BASE))
    result = runner(["model", "align"])
    assert result.exit_code == 1
    assert "unknown-model" in result.stdout
    assert "skip" in result.stdout


def test_align_rejects_a_non_chat_default_route(yzr_paths):
    _seed(yzr_paths, route="messages")
    result = runner(["model", "align"])
    assert result.exit_code == 1
    assert "chat-completions" in result.stdout
