"""Tests for the canonical-alias TOML registry (models.toml)."""
from pathlib import Path

import pytest

from model_switch import store


def _registry():
    return {
        "schema_version": 2,
        "models": [{
            "model_id": "glm-5.3",
            "provider": "yzr-dashscope",
            "canonical_provider": "alibaba-cn",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "SECRET",
        }],
    }


# --- load / save ---------------------------------------------------------------


def test_load_missing_file_returns_empty_registry(tmp_path):
    assert store.load_models(tmp_path / "models.toml") == {
        "schema_version": 2, "models": []}


def test_save_then_load_round_trips_unknown_fields(tmp_path):
    reg = _registry()
    reg["created_at"] = "2026-10-31T00:00:00Z"
    reg["models"][0]["note"] = "kept"
    path = tmp_path / "models.toml"
    store.save_models(path, reg)
    assert store.load_models(path) == reg


def test_save_writes_toml_atomically_with_owner_only_mode(tmp_path):
    path = tmp_path / "models.toml"
    store.save_models(path, _registry())
    assert 'canonical_provider = "alibaba-cn"' in path.read_text()
    assert not path.with_suffix(".toml.tmp").exists()
    assert (path.stat().st_mode & 0o777) == 0o600


def test_load_rejects_malformed_toml(tmp_path):
    path = tmp_path / "models.toml"
    path.write_text("not [valid toml")
    with pytest.raises(store.StoreError):
        store.load_models(path)


# --- validation ----------------------------------------------------------------


def test_validate_accepts_minimal_registry():
    store.validate_registry({"models": []})
    store.validate_registry(_registry())


@pytest.mark.parametrize("bad", [
    {"models": {}},
    {"models": [{"model_id": "m"}]},
    {"models": [{"model_id": "m", "provider": "dashscope",
                 "canonical_provider": "alibaba-cn",
                 "base_url": "u", "api_key": "k"}]},
    {"models": [{"model_id": "m", "provider": "yzr-dashscope",
                 "base_url": "u", "api_key": "k"}]},
    {"models": [{"model_id": "m", "provider": "yzr-dashscope",
                 "canonical_provider": "alibaba-cn",
                 "base_url": "", "api_key": "k"}]},
])
def test_validate_rejects_bad_shapes(bad):
    with pytest.raises(store.StoreError):
        store.validate_registry(bad)


def test_validate_rejects_duplicate_entry():
    reg = _registry()
    reg["models"].append(dict(reg["models"][0]))
    with pytest.raises(store.StoreError):
        store.validate_registry(reg)


@pytest.mark.parametrize("field", ["canonical_provider", "base_url", "api_key"])
def test_validate_rejects_conflicting_provider_group(field):
    reg = _registry()
    second = dict(reg["models"][0])
    second["model_id"] = "qwen3.8-flash"
    second[field] = "different"
    reg["models"].append(second)
    with pytest.raises(store.StoreError):
        store.validate_registry(reg)


def test_validate_accepts_siblings_sharing_provider_group():
    reg = _registry()
    second = dict(reg["models"][0])
    second["model_id"] = "qwen3.8-flash"
    reg["models"].append(second)
    store.validate_registry(reg)


@pytest.mark.parametrize("field", [
    "variants", "compatibility", "body", "package",
])
def test_validate_rejects_local_model_overrides(field):
    reg = _registry()
    reg["models"][0][field] = {"anything": True}
    with pytest.raises(store.StoreError):
        store.validate_registry(reg)


# --- active_model and references ------------------------------------------------


def test_active_model_round_trips(tmp_path):
    reg = _registry()
    reg["active_model"] = "yzr-dashscope/glm-5.3"
    path = tmp_path / "models.toml"
    store.save_models(path, reg)
    assert store.load_models(path)["active_model"] == (
        "yzr-dashscope/glm-5.3")


@pytest.mark.parametrize("bad", [
    "no-slash",
    "dashscope/glm-5.3",
    "yzr-dashscope/missing",
])
def test_validate_rejects_bad_active_model(bad):
    reg = _registry()
    reg["active_model"] = bad
    with pytest.raises(store.StoreError):
        store.validate_registry(reg)


def test_references_and_provider_helpers():
    reg = _registry()
    second = dict(reg["models"][0])
    second["model_id"] = "qwen3.8-flash"
    other = dict(reg["models"][0])
    other.update(provider="yzr-kimi", canonical_provider="kimi-code-plan-cn",
                 model_id="k3", base_url="https://api.kimi.com/coding/v1")
    reg["models"] += [second, other]
    assert list(store.iter_refs(reg)) == [
        "yzr-dashscope/glm-5.3", "yzr-dashscope/qwen3.8-flash",
        "yzr-kimi/k3"]
    assert store.get_model(reg, "yzr-dashscope/glm-5.3") == reg["models"][0]
    assert store.get_model(reg, "yzr-dashscope/missing") is None
    assert store.provider_labels(reg) == ["yzr-dashscope", "yzr-kimi"]
    assert [e["model_id"] for e in store.entries_for_provider(
            reg, "yzr-kimi")] == ["k3"]


def test_split_ref_rejects_bad_reference():
    with pytest.raises(store.StoreError):
        store.split_ref("no-slash")
