"""Tests for OpenCode driver — reads/writes ~/.config/opencode/opencode.json."""
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
        api_key="GLM_API_KEY",
        name="glm-4-plus",
        description="GLM-4 Plus",
    )


@pytest.fixture
def glm_ctx() -> Model:
    """A model with a context_window — exercises the limit handling."""
    return Model(
        model_id="glm",
        base_url="https://api.z.ai/api/anthropic",
        api_key="MS_API_KEY",
        name="glm-5.2",
        context_window=1000000,
    )



# --- read ---------------------------------------------------------------------


def test_current_returns_empty_when_file_missing(driver):
    assert driver.current() == {}


# --- name property ------------------------------------------------------------

def test_driver_name_is_opencode(driver):
    assert driver.name == "opencode"


# --- apply: the fields opencode actually needs to resolve the model ---------
#
# These encode the three bugs that made `model use --driver opencode` silently
# fail (opencode fell back to its default model):
#   1. wrong config path              — covered in test_paths.py
#   2. missing `npm` AI-SDK adapter   — test_apply_emits_anthropic_npm_adapter
#   3. invalid partial `limit`        — test_apply_does_not_emit_partial_limit


def test_apply_writes_resolved_api_key_verbatim(driver, glm_ctx):
    """The resolved key is written verbatim into options.apiKey — matching the
    claude-code driver and OpenCode's own convention for custom providers.
    No `{env:VAR}` placeholder: the key lives in the config file (so the file
    holds a secret; keep its permissions tight)."""
    driver.apply(model=glm_ctx, api_key="sk-resolved-123")
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["model"] == "{}/{}".format(PROVIDER_ID, glm_ctx.name)
    provider = cfg["provider"][PROVIDER_ID]
    # baseURL is /v1-adapted for @ai-sdk/anthropic (see the baseURL test group
    # below); glm_ctx.base_url has no /v1, so the driver appends it here.
    assert provider["options"]["baseURL"] == glm_ctx.base_url + "/v1"
    assert provider["options"]["apiKey"] == "sk-resolved-123"
    assert "{env:" not in provider["options"]["apiKey"]


def test_apply_emits_anthropic_npm_adapter(driver, glm_ctx):
    """A non-built-in opencode provider needs `npm` to tell opencode which
    AI-SDK adapter to load. Without it opencode reports 'Provider not found'
    and falls back to its default model. Anthropic-compatible upstreams use
    @ai-sdk/anthropic."""
    driver.apply(model=glm_ctx, api_key="k")
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][PROVIDER_ID]["npm"] == "@ai-sdk/anthropic"


def test_apply_does_not_emit_partial_limit(driver, glm_ctx):
    """OpenCode's schema requires `limit.output` whenever `limit` is present.
    A partial `{limit:{context}}` — the only thing we could build from
    context_window alone — fails validation and makes the whole config (and
    the model) unavailable. So we must not emit a partial limit."""
    driver.apply(model=glm_ctx, api_key="k")
    cfg = json.loads(driver.settings_path.read_text())
    entry = cfg["provider"][PROVIDER_ID]["models"][glm_ctx.name]
    assert "limit" not in entry, (
        "partial limit (context without output) fails opencode schema validation"
    )


def test_apply_preserves_unrelated_providers_and_keys(driver, glm_ctx):
    """model-switch must not clobber providers/keys it doesn't own in the
    same opencode.json (e.g. the user's other custom providers)."""
    seed = {
        "provider": {
            "existing": {"npm": "@ai-sdk/openai-compatible", "options": {"apiKey": "k"}},
        },
        "small_model": "existing/foo",
    }
    driver.settings_path.write_text(json.dumps(seed), encoding="utf-8")
    driver.apply(model=glm_ctx, api_key="k")
    cfg = json.loads(driver.settings_path.read_text())
    assert PROVIDER_ID in cfg["provider"]          # our provider added
    assert "existing" in cfg["provider"]           # foreign provider preserved
    assert cfg["small_model"] == "existing/foo"    # foreign top-level key preserved


# --- apply: baseURL /v1 adaptation -----------------------------------------
#
# @ai-sdk/anthropic (opencode's adapter) appends ONLY `/messages` to baseURL —
# it treats baseURL as a prefix that already includes the API version. So a
# base_url stored WITHOUT `/v1` (which is exactly what the claude-code driver
# wants: Claude Code appends `/v1` itself) makes opencode request
# `.../anthropic/messages`. z.ai answers that with a 404 wrapped in HTTP 200,
# and ai-sdk's SSE parser drops the non-event body silently → zero-token
# empty reply, no error event. The opencode driver owns this adaptation:
# ensure baseURL ends in a version segment. The SAME base_url value then serves
# both agents — the protocol difference lives inside each driver.


def test_apply_appends_v1_when_missing(driver, glm_ctx):
    driver.apply(model=glm_ctx, api_key="k")
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][PROVIDER_ID]["options"]["baseURL"] == "https://api.z.ai/api/anthropic/v1"


def test_apply_does_not_double_append_v1(driver, glm_ctx):
    glm_ctx.base_url = "https://api.z.ai/api/anthropic/v1"
    driver.apply(model=glm_ctx, api_key="k")
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][PROVIDER_ID]["options"]["baseURL"] == "https://api.z.ai/api/anthropic/v1"


def test_apply_keeps_arbitrary_version_segment(driver, glm_ctx):
    glm_ctx.base_url = "https://example.test/api/anthropic/v2"
    driver.apply(model=glm_ctx, api_key="k")
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][PROVIDER_ID]["options"]["baseURL"] == "https://example.test/api/anthropic/v2"


def test_apply_normalizes_trailing_slash_before_appending_v1(driver, glm_ctx):
    glm_ctx.base_url = "https://api.z.ai/api/anthropic/"
    driver.apply(model=glm_ctx, api_key="k")
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][PROVIDER_ID]["options"]["baseURL"] == "https://api.z.ai/api/anthropic/v1"