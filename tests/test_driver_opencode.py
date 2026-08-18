"""Tests for OpenCode driver — reads/writes ~/.config/opencode/opencode.json.

OpenCode holds a multi-model catalog: model-switch mirrors every model into a
`yzr-<model_id>` provider and sets `config["model"]` as the default pointer.
"""
import json
from pathlib import Path

import pytest

from model_switch.store import ModelEntry as Model
from model_switch.drivers.opencode import OpenCodeDriver


def _provider_id(model_id: str) -> str:
    return "yzr-" + model_id


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


def test_driver_is_catalog_capable(driver):
    assert driver.supports_catalog is True


# --- apply: the fields opencode actually needs to resolve the model ---------
#
# These encode the bugs that made `model use --driver opencode` silently fail
# (opencode fell back to its default model):
#   1. wrong config path              — covered in test_paths.py
#   2. missing `npm` AI-SDK adapter   — test_apply_emits_anthropic_npm_adapter
#   3. limit block mishandled         — test_apply_emits_context_limit_when_known
#                                       + test_apply_omits_limit_when_context_unknown


def test_apply_writes_resolved_api_key_verbatim(driver, glm_ctx):
    """The resolved key is written verbatim into options.apiKey — matching the
    claude-code driver and OpenCode's own convention for custom providers.
    No `{env:VAR}` placeholder: the key lives in the config file (so the file
    holds a secret; keep its permissions tight)."""
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    pid = _provider_id(glm_ctx.model_id)
    assert cfg["model"] == "{}/{}".format(pid, glm_ctx.name)
    provider = cfg["provider"][pid]
    # baseURL is /v1-adapted for @ai-sdk/anthropic (see the baseURL test group
    # below); glm_ctx.base_url has no /v1, so the driver appends it here.
    assert provider["options"]["baseURL"] == glm_ctx.base_url + "/v1"
    assert provider["options"]["apiKey"] == "MS_API_KEY"
    assert "{env:" not in provider["options"]["apiKey"]


def test_apply_emits_anthropic_npm_adapter(driver, glm_ctx):
    """A non-built-in opencode provider needs `npm` to tell opencode which
    AI-SDK adapter to load. Without it opencode reports 'Provider not found'
    and falls back to its default model. Anthropic-compatible upstreams use
    @ai-sdk/anthropic."""
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][_provider_id("glm")]["npm"] == "@ai-sdk/anthropic"


def test_apply_emits_context_limit_when_known(driver, glm_ctx):
    """A custom provider isn't on models.dev, so OpenCode can't infer the
    context budget — surface context_window as limit.context. OpenCode's
    schema requires `context` and `output` together (limit.required ==
    [context, output]), so context is paired with the default output cap;
    never a bare {limit:{context}} that would fail validation."""
    from model_switch.drivers.opencode import _DEFAULT_MAX_OUTPUT
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    entry = cfg["provider"][_provider_id("glm")]["models"][glm_ctx.name]
    assert entry["limit"] == {
        "context": glm_ctx.context_window,
        "output": _DEFAULT_MAX_OUTPUT,
    }


def test_apply_omits_limit_when_context_unknown(driver, glm_main):
    """context_window unknown → omit `limit` entirely, never a partial block.
    OpenCode rejects a limit missing output, and without context_window we
    can't build a valid one, so an empty model entry is the only schema-valid
    option here."""
    assert glm_main.context_window is None
    driver.apply(models=[glm_main], active=glm_main)
    cfg = json.loads(driver.settings_path.read_text())
    entry = cfg["provider"][_provider_id("glm")]["models"][glm_main.name]
    assert entry == {}
    assert "limit" not in entry


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
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    assert _provider_id("glm") in cfg["provider"]  # our provider added
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
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][_provider_id("glm")]["options"]["baseURL"] == "https://api.z.ai/api/anthropic/v1"


def test_apply_does_not_double_append_v1(driver, glm_ctx):
    glm_ctx.base_url = "https://api.z.ai/api/anthropic/v1"
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][_provider_id("glm")]["options"]["baseURL"] == "https://api.z.ai/api/anthropic/v1"


def test_apply_keeps_arbitrary_version_segment(driver, glm_ctx):
    glm_ctx.base_url = "https://example.test/api/anthropic/v2"
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][_provider_id("glm")]["options"]["baseURL"] == "https://example.test/api/anthropic/v2"


def test_apply_normalizes_trailing_slash_before_appending_v1(driver, glm_ctx):
    glm_ctx.base_url = "https://api.z.ai/api/anthropic/"
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][_provider_id("glm")]["options"]["baseURL"] == "https://api.z.ai/api/anthropic/v1"


# --- catalog semantics -------------------------------------------------------


def _models():
    glm = Model(model_id="glm", base_url="https://a", api_key="K1", name="glm-4")
    kimi = Model(model_id="kimi", base_url="https://b", api_key="K2", name="kimi-k2")
    return [glm, kimi]


def test_apply_writes_one_provider_per_model(driver):
    models = _models()
    driver.apply(models=models, active=models[0])
    cfg = json.loads(driver.settings_path.read_text())
    assert _provider_id("glm") in cfg["provider"]
    assert _provider_id("kimi") in cfg["provider"]
    # Each provider is self-contained (baseURL/key differ per upstream).
    assert cfg["provider"][_provider_id("glm")]["options"]["apiKey"] == "K1"
    assert cfg["provider"][_provider_id("kimi")]["options"]["apiKey"] == "K2"
    # Default pointer names the active model.
    assert cfg["model"] == "{}/glm-4".format(_provider_id("glm"))


def test_apply_sets_default_to_active(driver):
    models = _models()
    driver.apply(models=models, active=models[1])
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["model"] == "{}/kimi-k2".format(_provider_id("kimi"))


def test_sync_catalog_preserves_valid_default(driver):
    """sync_catalog (add/remove path) keeps the existing default pointer when
    it still names a live model."""
    models = _models()
    driver.apply(models=models, active=models[0])  # default = yzr-glm/glm-4
    driver.sync_catalog(models)                     # no active change
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["model"] == "{}/glm-4".format(_provider_id("glm"))


def test_sync_catalog_falls_back_when_default_vanished(driver):
    """Removing the default model re-points the pointer to the first remaining."""
    models = _models()
    driver.apply(models=models, active=models[0])  # default = glm
    remaining = [models[1]]                         # glm removed
    driver.sync_catalog(remaining)
    cfg = json.loads(driver.settings_path.read_text())
    assert _provider_id("glm") not in cfg["provider"]  # provider + key reclaimed
    assert cfg["model"] == "{}/kimi-k2".format(_provider_id("kimi"))


def test_sync_catalog_drops_default_when_no_models(driver):
    models = _models()
    driver.apply(models=models, active=models[0])
    driver.sync_catalog([])
    cfg = json.loads(driver.settings_path.read_text())
    assert "model" not in cfg
    assert cfg["provider"] == {}


def test_sync_catalog_reclaims_legacy_single_slot_provider(driver):
    """An upgrade from the old single-slot `yzr` provider is reclaimed (with
    its key) and re-rendered as `yzr-<id>`."""
    legacy = {
        "provider": {"yzr": {"options": {"apiKey": "OLD_KEY"}}},
        "model": "yzr/glm-4",
    }
    driver.settings_path.write_text(json.dumps(legacy), encoding="utf-8")
    models = _models()
    driver.sync_catalog(models)
    cfg = json.loads(driver.settings_path.read_text())
    assert "yzr" not in cfg["provider"]
    assert _provider_id("glm") in cfg["provider"]
    assert cfg["provider"][_provider_id("glm")]["options"]["apiKey"] == "K1"


def test_sync_catalog_does_not_create_missing_file(driver):
    """The add/remove/import path must not conjure an opencode.json out of
    thin air — only a targeted `apply()` creates it."""
    driver.sync_catalog(_models())
    assert not driver.settings_path.exists()


def test_sync_catalog_preserves_foreign_default_pointer(driver):
    """A default pointer that isn't ours (user's own provider) must never be
    hijacked by a catalog sync — only a `model use` moves the default."""
    seed = {
        "provider": {
            "anthropic": {"options": {"apiKey": "k"}},
        },
        "model": "anthropic/claude-sonnet-4",
    }
    driver.settings_path.write_text(json.dumps(seed), encoding="utf-8")
    models = _models()
    driver.sync_catalog(models)
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["model"] == "anthropic/claude-sonnet-4"  # foreign default intact
    assert "anthropic" in cfg["provider"]                # foreign provider intact
    assert _provider_id("glm") in cfg["provider"]        # ours added alongside


def test_sync_catalog_does_not_conjure_default_when_absent(driver):
    """No `model` key in the file → sync_catalog leaves it absent (only
    `model use` sets a default)."""
    seed = {"provider": {"anthropic": {"options": {"apiKey": "k"}}}}
    driver.settings_path.write_text(json.dumps(seed), encoding="utf-8")
    driver.sync_catalog(_models())
    cfg = json.loads(driver.settings_path.read_text())
    assert "model" not in cfg


def test_sync_catalog_skips_models_without_key(driver, glm_ctx):
    """A model with no api_key renders no usable provider; it is skipped rather
    than failing the whole reconcile."""
    glm_ctx.api_key = None
    kimi = Model(model_id="kimi", base_url="https://b", api_key="K2", name="kimi")
    driver.apply(models=[glm_ctx, kimi], active=kimi)
    cfg = json.loads(driver.settings_path.read_text())
    assert _provider_id("kimi") in cfg["provider"]
    assert _provider_id("glm") not in cfg["provider"]


def test_apply_errors_when_active_missing_key(driver, glm_ctx):
    glm_ctx.api_key = None
    with pytest.raises(ValueError):
        driver.apply(models=[glm_ctx], active=glm_ctx)


# --- current ------------------------------------------------------------------


def test_current_reports_default_and_catalog(driver):
    models = _models()
    driver.apply(models=models, active=models[0])
    cur = driver.current()
    assert cur["model"] == "{}/glm-4".format(_provider_id("glm"))
    assert "catalog" in cur
    assert _provider_id("glm") in cur["catalog"]
    assert _provider_id("kimi") in cur["catalog"]
