"""Tests for OpenCode driver — reads/writes ~/.config/opencode/opencode.json.

OpenCode holds a multi-model catalog: model-switch groups models by
(base_url, api_key) upstream and mirrors each group into a `yzr-<host-slug>`
provider, with `config["model"]` as the default pointer.
"""
import json
from pathlib import Path

import pytest

from model_switch.store import ModelEntry as Model
from model_switch.drivers.opencode import OpenCodeDriver, _upstream_slug


def _pid(model: Model) -> str:
    """Provider id for a model under the grouped scheme."""
    return "yzr-" + _upstream_slug(model.base_url)


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
#                                       + test_apply_omits_undeclared_optional_fields


def test_apply_writes_resolved_api_key_verbatim(driver, glm_ctx):
    """The resolved key is written verbatim into options.apiKey — matching the
    claude-code driver and OpenCode's own convention for custom providers.
    No `{env:VAR}` placeholder: the key lives in the config file (so the file
    holds a secret; keep its permissions tight)."""
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    pid = _pid(glm_ctx)
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
    assert cfg["provider"][_pid(glm_ctx)]["npm"] == "@ai-sdk/anthropic"


def test_apply_emits_context_limit_when_known(driver, glm_ctx):
    """A custom provider isn't on models.dev, so OpenCode can't infer the
    context budget — surface context_window as limit.context. OpenCode's
    schema requires `context` and `output` together (limit.required ==
    [context, output]), so context is paired with the default output cap;
    never a bare {limit:{context}} that would fail validation."""
    from model_switch.drivers.opencode import _DEFAULT_MAX_OUTPUT
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    entry = cfg["provider"][_pid(glm_ctx)]["models"][glm_ctx.name]
    assert entry["limit"] == {
        "context": glm_ctx.context_window,
        "output": _DEFAULT_MAX_OUTPUT,
    }


def test_apply_omits_undeclared_optional_fields(driver, glm_main):
    """No context_window and no modalities → neither `limit` nor `modalities`
    is emitted, and never a partial block: OpenCode rejects a limit missing
    its paired `output`, so an empty model entry is the only schema-valid
    rendering of undeclared optional fields."""
    assert glm_main.context_window is None
    driver.apply(models=[glm_main], active=glm_main)
    cfg = json.loads(driver.settings_path.read_text())
    entry = cfg["provider"][_pid(glm_main)]["models"][glm_main.name]
    assert entry == {}


# --- modalities: opt-in non-text input, validated locally --------------------


def _modalities_model(value):
    return Model(
        model_id="m",
        base_url="https://api.z.ai/api/anthropic",
        api_key="K",
        name="glm-5.2",
        extra={"modalities": value},
    )


def test_apply_emits_modalities_when_declared(driver):
    """OpenCode drops (replaces with an ERROR text prompt) any message part
    whose modality isn't declared, so a model that accepts images/PDFs must
    opt in explicitly."""
    model = _modalities_model({"input": ["text", "image"], "output": ["text"]})
    driver.apply(models=[model], active=model)
    cfg = json.loads(driver.settings_path.read_text())
    entry = cfg["provider"][_pid(model)]["models"][model.name]
    assert entry["modalities"] == {"input": ["text", "image"],
                                   "output": ["text"]}


@pytest.mark.parametrize("value", [
    ["text"],                      # not a table
    {"inputs": ["text"]},          # unknown key
    {"input": "text"},             # not a list
    {"input": []},                 # empty list
    {"input": ["text", "gif"]},    # unknown modality
    {},                            # empty table
])
def test_modalities_invalid_values_fail_locally(driver, value):
    """A schema violation would make OpenCode reject the *whole* config file,
    so bad values must fail here — and before the file is written."""
    model = _modalities_model(value)
    with pytest.raises(ValueError) as excinfo:
        driver.apply(models=[model], active=model)
    message = str(excinfo.value)
    assert "modalities" in message
    assert model.model_id in message
    assert not driver.settings_path.exists()


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
    assert _pid(glm_ctx) in cfg["provider"]   # our provider added
    assert "existing" in cfg["provider"]      # foreign provider preserved
    assert cfg["small_model"] == "existing/foo"  # foreign top-level key preserved


# --- apply: baseURL /v1 adaptation -----------------------------------------
#
# @ai-sdk/anthropic (opencode's adapter) appends ONLY `/messages` to baseURL —
# it treats it as a prefix that already includes the API version. So a
# base_url stored WITHOUT `/v1` (which is exactly what the claude-code driver
# wants: Claude Code appends /v1 itself) makes opencode request
# `.../anthropic/messages`. z.ai answers that with a 404 wrapped in HTTP 200,
# and ai-sdk's SSE parser drops the non-event body silently → zero-token
# empty reply, no error event. The opencode driver owns this adaptation:
# ensure baseURL ends in a version segment. The SAME base_url value then serves
# both agents — the protocol difference lives inside each driver.


@pytest.mark.parametrize("base_url, expected", [
    ("https://api.z.ai/api/anthropic", "https://api.z.ai/api/anthropic/v1"),
    ("https://api.z.ai/api/anthropic/v1", "https://api.z.ai/api/anthropic/v1"),
    ("https://example.test/api/anthropic/v2", "https://example.test/api/anthropic/v2"),
    ("https://api.z.ai/api/anthropic/", "https://api.z.ai/api/anthropic/v1"),
])
def test_apply_adapts_baseurl_to_a_version_segment(driver, glm_ctx, base_url, expected):
    """Missing → append /v1; already versioned (v1 or otherwise) → keep as-is;
    trailing slash → normalized before appending. The same stored base_url
    serves both agents; the protocol difference lives inside each driver."""
    glm_ctx.base_url = base_url
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["provider"][_pid(glm_ctx)]["options"]["baseURL"] == expected


# --- upstream slug derivation -------------------------------------------------


def test_upstream_slug_examples():
    assert _upstream_slug("https://api.z.ai/api/anthropic") == "zai"
    assert _upstream_slug("https://api.kimi.com/coding/") == "kimi"
    assert _upstream_slug("https://dashscope.aliyuncs.com/apps/anthropic") == "dashscope"
    assert _upstream_slug("https://open.bigmodel.cn/api/anthropic") == "open"
    assert _upstream_slug("https://a") == "a"
    assert _upstream_slug("not-a-url") == "notaurl"


# --- catalog semantics -------------------------------------------------------


def _models():
    glm = Model(model_id="glm", base_url="https://a", api_key="K1", name="glm-4")
    kimi = Model(model_id="kimi", base_url="https://b", api_key="K2", name="kimi-k2")
    return [glm, kimi]


def test_apply_writes_one_provider_per_upstream(driver):
    models = _models()
    driver.apply(models=models, active=models[0])
    cfg = json.loads(driver.settings_path.read_text())
    assert _pid(models[0]) in cfg["provider"]
    assert _pid(models[1]) in cfg["provider"]
    # Each provider is self-contained (baseURL/key differ per upstream).
    assert cfg["provider"][_pid(models[0])]["options"]["apiKey"] == "K1"
    assert cfg["provider"][_pid(models[1])]["options"]["apiKey"] == "K2"
    # Default pointer names the active model.
    assert cfg["model"] == "{}/glm-4".format(_pid(models[0]))


def test_apply_groups_same_upstream_models_into_one_provider(driver):
    """Models sharing (base_url, api_key) share one provider block; the
    default pointer still names the active model individually."""
    glm = Model(model_id="glm52", base_url="https://api.z.ai/api/anthropic",
                api_key="K", name="glm-5.2")
    glm53 = Model(model_id="glm53", base_url="https://api.z.ai/api/anthropic",
                  api_key="K", name="glm-5.3")
    driver.apply(models=[glm, glm53], active=glm53)
    cfg = json.loads(driver.settings_path.read_text())
    assert list(cfg["provider"]) == ["yzr-zai"]
    assert set(cfg["provider"]["yzr-zai"]["models"]) == {"glm-5.2", "glm-5.3"}
    assert cfg["model"] == "yzr-zai/glm-5.3"


def test_apply_splits_same_host_different_key(driver):
    """Same base_url but different keys cannot share a block (apiKey is
    provider-level); they get distinct providers via collision suffixes."""
    a = Model(model_id="a", base_url="https://api.z.ai/api/anthropic",
              api_key="K1", name="m1")
    b = Model(model_id="b", base_url="https://api.z.ai/api/anthropic",
              api_key="K2", name="m2")
    driver.apply(models=[a, b], active=a)
    cfg = json.loads(driver.settings_path.read_text())
    assert set(cfg["provider"]) == {"yzr-zai", "yzr-zai-2"}
    assert cfg["provider"]["yzr-zai"]["options"]["apiKey"] == "K1"
    assert cfg["provider"]["yzr-zai-2"]["options"]["apiKey"] == "K2"
    assert cfg["model"] == "yzr-zai/m1"


def test_apply_collision_suffix_is_stable_across_renders(driver):
    a = Model(model_id="a", base_url="https://api.z.ai/one",
              api_key="K1", name="m1")
    b = Model(model_id="b", base_url="https://api.z.ai/two",
              api_key="K2", name="m2")
    driver.apply(models=[a, b], active=a)
    first = json.loads(driver.settings_path.read_text())
    driver.apply(models=[a, b], active=a)
    second = json.loads(driver.settings_path.read_text())
    assert first == second


def test_apply_rejects_duplicate_name_within_group(driver):
    a = Model(model_id="a", base_url="https://api.z.ai/api/anthropic",
              api_key="K", name="glm-5.3")
    b = Model(model_id="b", base_url="https://api.z.ai/api/anthropic",
              api_key="K", name="glm-5.3")
    with pytest.raises(ValueError, match="unique within one upstream"):
        driver.apply(models=[a, b], active=a)


# --- declared provider names --------------------------------------------------

def test_apply_declared_provider_groups_and_names_ids(driver):
    """`provider = "<name>"` pins the id to yzr-<name>; members sharing it
    group into one block."""
    a = Model(model_id="a", base_url="https://dashscope.aliyuncs.com/apps/anthropic",
              api_key="K", name="qwen3.8-max", extra={"provider": "dashscope"})
    b = Model(model_id="b", base_url="https://dashscope.aliyuncs.com/apps/anthropic",
              api_key="K", name="qwen3.8-flash", extra={"provider": "dashscope"})
    driver.apply(models=[a, b], active=b)
    cfg = json.loads(driver.settings_path.read_text())
    assert list(cfg["provider"]) == ["yzr-dashscope"]
    assert set(cfg["provider"]["yzr-dashscope"]["models"]) == {
        "qwen3.8-max", "qwen3.8-flash"}
    assert cfg["model"] == "yzr-dashscope/qwen3.8-flash"


def test_apply_declared_provider_id_survives_base_url_change(driver):
    """The pinned name is the identity: changing base_url later must not
    rename the provider or leave the old block behind."""
    pinned = {"provider": "dashscope"}
    old = Model(model_id="m", base_url="https://dashscope.aliyuncs.com/apps/anthropic",
                api_key="K", name="qwen3.8-flash", extra=dict(pinned))
    driver.apply(models=[old], active=old)
    assert list(json.loads(driver.settings_path.read_text())["provider"]) == [
        "yzr-dashscope"]

    moved = Model(model_id="m", base_url="https://new-gateway.example.com/anthropic",
                  api_key="K", name="qwen3.8-flash", extra=dict(pinned))
    driver.apply(models=[moved], active=moved)
    cfg = json.loads(driver.settings_path.read_text())
    assert list(cfg["provider"]) == ["yzr-dashscope"]
    assert cfg["provider"]["yzr-dashscope"]["options"]["baseURL"] == (
        "https://new-gateway.example.com/anthropic/v1")
    assert cfg["model"] == "yzr-dashscope/qwen3.8-flash"


@pytest.mark.parametrize("a_key,b_key,b_url,field,secrets", [
    pytest.param("K", "K", "https://b.example/anthropic", "base_url", (),
                 id="base_url"),
    pytest.param("SECRET-ONE", "SECRET-TWO", "https://a.example/anthropic",
                 "api_key", ("SECRET-ONE", "SECRET-TWO"), id="api_key"),
])
def test_apply_rejects_conflicting_upstream_under_one_name(
        driver, a_key, b_key, b_url, field, secrets):
    """Models under one declared name must share base_url and api_key; a
    partial key rotation must fail loudly — and the error never prints the
    keys themselves."""
    a = Model(model_id="a", base_url="https://a.example/anthropic",
              api_key=a_key, name="m1", extra={"provider": "gw"})
    b = Model(model_id="b", base_url=b_url, api_key=b_key, name="m2",
              extra={"provider": "gw"})
    with pytest.raises(ValueError) as ei:
        driver.apply(models=[a, b], active=a)
    msg = str(ei.value)
    assert "conflicting upstreams" in msg
    assert field in msg
    assert "'a'" in msg and "'b'" in msg
    for secret in secrets:
        assert secret not in msg


def test_apply_declared_name_wins_collision_with_derived_slug(driver):
    """A declared name keeps the plain id; a derived slug that wants the
    same name takes the suffix."""
    declared = Model(model_id="d", base_url="https://one.example/anthropic",
                     api_key="K", name="m1", extra={"provider": "zai"})
    derived = Model(model_id="x", base_url="https://api.z.ai/api/anthropic",
                    api_key="K2", name="m2")
    driver.apply(models=[declared, derived], active=declared)
    cfg = json.loads(driver.settings_path.read_text())
    assert set(cfg["provider"]) == {"yzr-zai", "yzr-zai-2"}
    assert cfg["provider"]["yzr-zai"]["options"]["baseURL"] == (
        "https://one.example/anthropic/v1")
    assert cfg["provider"]["yzr-zai-2"]["options"]["baseURL"] == (
        "https://api.z.ai/api/anthropic/v1")


@pytest.mark.parametrize("name", ["Foo", "with space", "a/b", "yzr-zai",
                                  "", "-lead", "trail-", "a..b"])
def test_apply_rejects_invalid_provider_names(driver, name):
    m = Model(model_id="m", base_url="https://a.example/anthropic", api_key="K",
              name="m1", extra={"provider": name})
    with pytest.raises(ValueError):
        driver.apply(models=[m], active=m)


def test_apply_declared_name_equal_to_derived_slug_is_transparent(driver):
    """Declaring the slug the tool would derive anyway must not change the
    rendered config — the migration guarantee for existing files."""
    plain = Model(model_id="m", base_url="https://api.z.ai/api/anthropic",
                  api_key="K", name="glm-5.3")
    pinned = Model(model_id="m", base_url="https://api.z.ai/api/anthropic",
                   api_key="K", name="glm-5.3", extra={"provider": "zai"})
    driver.apply(models=[plain], active=plain)
    first = driver.settings_path.read_text()
    driver.apply(models=[pinned], active=pinned)
    assert driver.settings_path.read_text() == first


def test_apply_sets_default_to_active(driver):
    models = _models()
    driver.apply(models=models, active=models[1])
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["model"] == "{}/kimi-k2".format(_pid(models[1]))


def test_sync_catalog_preserves_valid_default(driver):
    """sync_catalog (add/remove path) keeps the existing default pointer when
    it still names a live model."""
    models = _models()
    driver.apply(models=models, active=models[0])
    driver.sync_catalog(models)                     # no active change
    cfg = json.loads(driver.settings_path.read_text())
    assert cfg["model"] == "{}/glm-4".format(_pid(models[0]))


def test_sync_catalog_falls_back_when_default_vanished(driver):
    """Removing the default model re-points the pointer to the first remaining."""
    models = _models()
    driver.apply(models=models, active=models[0])  # default = glm
    remaining = [models[1]]                         # glm removed
    driver.sync_catalog(remaining)
    cfg = json.loads(driver.settings_path.read_text())
    assert _pid(models[0]) not in cfg["provider"]   # provider + key reclaimed
    assert cfg["model"] == "{}/kimi-k2".format(_pid(models[1]))


def test_sync_catalog_drops_default_when_no_models(driver):
    models = _models()
    driver.apply(models=models, active=models[0])
    driver.sync_catalog([])
    cfg = json.loads(driver.settings_path.read_text())
    assert "model" not in cfg
    assert cfg["provider"] == {}


def test_sync_catalog_reclaims_legacy_single_slot_provider(driver):
    """An upgrade from the old single-slot `yzr` provider is reclaimed (with
    its key) and re-rendered under the grouped scheme."""
    legacy = {
        "provider": {"yzr": {"options": {"apiKey": "OLD_KEY"}}},
        "model": "yzr/glm-4",
    }
    driver.settings_path.write_text(json.dumps(legacy), encoding="utf-8")
    models = _models()
    driver.sync_catalog(models)
    cfg = json.loads(driver.settings_path.read_text())
    assert "yzr" not in cfg["provider"]
    assert _pid(models[0]) in cfg["provider"]
    assert cfg["provider"][_pid(models[0])]["options"]["apiKey"] == "K1"


def test_sync_catalog_reclaims_per_model_ids_from_pre_grouping_scheme(driver):
    """Old `yzr-<model_id>` blocks are owned ids too and must be reclaimed
    when the grouping scheme re-renders."""
    legacy = {
        "provider": {"yzr-glm": {"options": {"apiKey": "OLD_KEY"}}},
    }
    driver.settings_path.write_text(json.dumps(legacy), encoding="utf-8")
    models = _models()
    driver.sync_catalog(models)
    cfg = json.loads(driver.settings_path.read_text())
    assert "yzr-glm" not in cfg["provider"]
    assert _pid(models[0]) in cfg["provider"]


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
    assert _pid(models[0]) in cfg["provider"]            # ours added alongside


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
    assert _pid(kimi) in cfg["provider"]
    assert _pid(glm_ctx) not in cfg["provider"]


def test_apply_errors_when_active_missing_key(driver, glm_ctx):
    glm_ctx.api_key = None
    with pytest.raises(ValueError):
        driver.apply(models=[glm_ctx], active=glm_ctx)


# --- current ------------------------------------------------------------------


def test_current_reports_default_and_catalog(driver):
    models = _models()
    driver.apply(models=models, active=models[0])
    cur = driver.current()
    assert cur["model"] == "{}/glm-4".format(_pid(models[0]))
    assert "catalog" in cur
    assert _pid(models[0]) in cur["catalog"]
    assert _pid(models[1]) in cur["catalog"]


# --- reasoning / variants authority ------------------------------------------
#
# models.toml may carry `reasoning = true` (mark the model reasoning-capable)
# and a `variants` table (effort tiers for OpenCode's ctrl+t variant cycle).
# `reasoning` is rendered as-is. A declared `variants` table is rendered with
# every built-in tier OpenCode would otherwise merge in muted, so the cycle
# offers exactly what was declared; tier shapes stay user data.

def _rendered(driver, model):
    driver.apply(models=[model], active=model)
    cfg = json.loads(driver.settings_path.read_text())
    return cfg["provider"][_pid(model)]["models"][model.name]


def _model(extra, context_window=None):
    return Model(
        model_id="m", name="m", base_url="https://api.example.com",
        api_key="K", context_window=context_window, extra=extra,
    )


def test_apply_renders_declared_variants_as_the_full_set(driver):
    from model_switch.drivers.opencode import (_DEFAULT_MAX_OUTPUT,
                                               _INJECTABLE_TIER_NAMES)
    entry = _rendered(driver, _model(
        {"reasoning": True,
         "variants": {"high": {"effort": "high"}, "max": {"effort": "max"}}},
        context_window=1000000,
    ))
    assert entry["reasoning"] is True
    # Declared tiers keep their payload byte-for-byte; every other tier
    # OpenCode's built-ins could inject is muted instead of offered.
    for tier in _INJECTABLE_TIER_NAMES:
        expected = {"high": {"effort": "high"},
                    "max": {"effort": "max"}}.get(tier, {"disabled": True})
        assert entry["variants"][tier] == expected
    assert len(entry["variants"]) == len(_INJECTABLE_TIER_NAMES)
    assert entry["limit"] == {"context": 1000000, "output": _DEFAULT_MAX_OUTPUT}


def test_apply_keeps_tier_names_outside_the_injectable_set(driver):
    """The vocabulary is a mute list, not a whitelist: a tier name OpenCode
    cannot inject (`off`) is rendered untouched."""
    entry = _rendered(driver, _model(
        {"reasoning": True, "variants": {"off": {"thinking": {"type": "disabled"}}}},
    ))
    assert entry["variants"]["off"] == {"thinking": {"type": "disabled"}}
    assert "max" in entry["variants"]  # ...and the built-ins are still muted


def test_apply_preserves_a_hand_written_disabled_tier(driver):
    """A user-written `disabled` (alone or beside a payload) is not replaced
    by the generated one."""
    entry = _rendered(driver, _model(
        {"reasoning": True,
         "variants": {"medium": {"effort": "medium", "disabled": True},
                      "xhigh": {"disabled": True},
                      "high": {"effort": "high"}}},
    ))
    assert entry["variants"]["medium"] == {"effort": "medium", "disabled": True}
    assert entry["variants"]["xhigh"] == {"disabled": True}
    assert entry["variants"]["high"] == {"effort": "high"}


def test_apply_does_not_mutate_the_registry_variants(driver):
    """`variants.expand_model` hands back the registry's own dict when there
    is no preset reference — muting must copy, not edit in place, or the muted
    keys would leak into models.toml on the next save."""
    variants = {"high": {"effort": "high"}}
    m = _model({"reasoning": True, "variants": variants})
    _rendered(driver, m)
    assert m.extra["variants"] is variants
    assert variants == {"high": {"effort": "high"}}


def test_apply_without_reasoning_renders_variants_unmuted(driver):
    """OpenCode computes no built-ins without `reasoning = true`, so there is
    nothing to mute: the declared table passes through exactly as before."""
    variants = {"high": {"effort": "high"}}
    m = _model({"variants": variants})
    entry = _rendered(driver, m)
    assert "reasoning" not in entry
    assert entry["variants"] == {"high": {"effort": "high"}}
    assert variants == {"high": {"effort": "high"}}


def test_apply_renders_optional_fields_without_context_window(driver):
    """The optional fields must not be swallowed when context_window is
    unknown: only `limit` is conditional, never the whole entry."""
    from model_switch.drivers.opencode import _INJECTABLE_TIER_NAMES
    entry = _rendered(driver, _model(
        {"reasoning": True, "variants": {"high": {"effort": "high"}}},
    ))
    assert "limit" not in entry
    assert entry["reasoning"] is True
    assert entry["variants"]["high"] == {"effort": "high"}
    assert sorted(entry["variants"]) == sorted(_INJECTABLE_TIER_NAMES)


def test_apply_ignores_non_true_reasoning_and_empty_variants(driver, glm_ctx):
    """A string '"true"' or an empty variants table renders nothing, keeping
    entries without usable declarations byte-identical to the old output."""
    glm_ctx.extra = {"reasoning": "true", "variants": {}}
    driver.apply(models=[glm_ctx], active=glm_ctx)
    cfg = json.loads(driver.settings_path.read_text())
    entry = cfg["provider"][_pid(glm_ctx)]["models"][glm_ctx.name]
    assert entry == {"limit": {"context": 1000000, "output": 131072}}


def test_sync_catalog_keeps_reasoning_and_variants_on_reconcile(driver):
    """Reconcile is a mirror: a second run must reproduce the same model
    block (no drift, no loss)."""
    m = _model(
        {"reasoning": True, "variants": {"high": {"effort": "high"}}},
        context_window=1000,
    )
    driver.settings_path.write_text("{}", encoding="utf-8")  # sync never creates
    driver.sync_catalog([m])
    first = json.loads(driver.settings_path.read_text())["provider"][_pid(m)]
    driver.sync_catalog([m])
    second = json.loads(driver.settings_path.read_text())["provider"][_pid(m)]
    assert first == second
    assert second["models"]["m"]["variants"]["high"] == {"effort": "high"}
    assert second["models"]["m"]["variants"]["low"] == {"disabled": True}
