"""Tests for the TOML-backed store."""
import pytest

from model_switch.store import (
    DuplicateModelId,
    InvalidContextWindow,
    MissingRequiredField,
    ModelEntry,
    Registry,
    State,
    load_models,
    load_state,
    save_models,
    save_state,
)


# --- load_models --------------------------------------------------------------

def test_load_models_returns_empty_registry_when_file_missing(tmp_path):
    assert load_models(tmp_path / "models.toml") == Registry()


def test_load_models_round_trip(tmp_path):
    p = tmp_path / "models.toml"
    reg = Registry(models={
        "glm": ModelEntry(
            model_id="glm",
            name="glm-4-plus",
            base_url="https://api.example.com",
            api_key="GLM_API_KEY",
            description="GLM-4 Plus",
        ),
    })
    save_models(p, reg)
    loaded = load_models(p)
    assert loaded.models["glm"].name == "glm-4-plus"
    assert loaded.models["glm"].api_key == "GLM_API_KEY"


def test_load_models_preserves_unknown_top_level_keys(tmp_path):
    """If a TOML contains top-level keys model-switch doesn't own
    (e.g. `schema_version` from llmw), they survive round-trip in extra_top."""
    p = tmp_path / "models.toml"
    p.write_text('schema_version = 2\ncreated_at = "2026-01-01T00:00:00Z"\n\n'
                 '[[models]]\nmodel_id = "glm"\nname = "glm-4"\n'
                 'base_url = "u"\napi_key = "K"\n')

    reg = load_models(p)
    assert reg.extra_top == {
        "schema_version": 2,
        "created_at": "2026-01-01T00:00:00Z",
    }


def test_load_models_preserves_unknown_per_model_keys(tmp_path):
    """Per-model keys we don't own (e.g. `is_default`) survive in
    ModelEntry.extra. `api_key` is now an owned field, so it lives on
    ModelEntry directly (not in extra)."""
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "glm"\n'
                 'name = "glm-4"\n'
                 'base_url = "u"\n'
                 'api_key = "sk-secret-from-llmw"\n'
                 'is_default = true\n')

    reg = load_models(p)
    assert reg.models["glm"].api_key == "sk-secret-from-llmw"
    assert reg.models["glm"].extra == {"is_default": True}


def test_load_models_preserves_unknown_keys_after_save(tmp_path):
    """Round-trip: unknown top-level + per-model keys survive a save/load."""
    p = tmp_path / "models.toml"
    p.write_text('schema_version = 2\n\n'
                 '[[models]]\n'
                 'model_id = "glm"\n'
                 'name = "glm-4"\n'
                 'base_url = "u"\n'
                 'api_key = "sk-x"\n')

    reg = load_models(p)
    # Now mutate model-switch-owned fields and save back.
    reg.models["glm"].context_window = 1000000
    save_models(p, reg)

    reloaded = load_models(p)
    # Unknown keys still there.
    assert reloaded.extra_top.get("schema_version") == 2
    assert reloaded.models["glm"].api_key == "sk-x"
    # Owned field updated.
    assert reloaded.models["glm"].context_window == 1000000


def test_load_models_rejects_missing_required_field(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\nmodel_id = "glm"\nname = "glm-4"\n'
                 'base_url = "u"\n# missing api_key\n')
    with pytest.raises(MissingRequiredField):
        load_models(p)


def test_load_models_rejects_duplicate_model_id(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\nmodel_id = "glm"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
                 '[[models]]\nmodel_id = "glm"\nname = "n2"\nbase_url = "u2"\napi_key = "K2"\n')
    with pytest.raises(DuplicateModelId):
        load_models(p)


def test_load_models_rejects_non_int_context_window(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\nmodel_id = "glm"\nname = "n"\n'
                 'base_url = "u"\napi_key = "K"\n'
                 'context_window = "1m"\n')
    with pytest.raises(InvalidContextWindow):
        load_models(p)


# --- save_models --------------------------------------------------------------

def test_save_models_creates_parent_directory(tmp_path):
    p = tmp_path / "nested" / "models.toml"
    save_models(p, Registry(models={
        "m": ModelEntry(model_id="m", name="n", base_url="u", api_key="K"),
    }))
    assert p.exists()


# --- nested tables inside [[models]] entries ---------------------------------
#
# Regression guards for the dumper's array-of-tables prefix handling: a nested
# dict inside an array item must render as `[models.<key>]`, not a top-level
# `[<key>]`. The old behavior silently dropped `variants` from the entry (one
# entry) or made the file unparseable ("Cannot declare ('variants',) twice",
# two or more entries).

def test_variants_round_trip_single_entry(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "glm-5_3-1m"\n'
                 'name = "glm-5.3"\n'
                 'base_url = "u"\n'
                 'api_key = "K"\n'
                 'reasoning = true\n'
                 '\n[models.variants]\n'
                 'high = { effort = "high" }\n'
                 'max = { effort = "max" }\n')

    reg = load_models(p)
    assert reg.models["glm-5_3-1m"].extra["variants"] == {
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    }
    assert reg.extra_top.get("variants") is None

    save_models(p, reg)
    text = p.read_text()
    assert "[models.variants.max]" in text
    assert "\n[variants]" not in text

    reloaded = load_models(p)
    assert reloaded.models["glm-5_3-1m"].extra["variants"] == {
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    }
    assert reloaded.extra_top.get("variants") is None


def test_variants_round_trip_two_entries(tmp_path):
    """Two entries carrying variants: the old dumper emitted a duplicate
    top-level `[variants]` table and tomllib refused the whole file."""
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "a"\nname = "a"\nbase_url = "u"\napi_key = "K"\n'
                 'variants = { high = { effort = "high" } }\n'
                 '[[models]]\n'
                 'model_id = "b"\nname = "b"\nbase_url = "u"\napi_key = "K"\n'
                 'variants = { max = { effort = "max" } }\n')

    save_models(p, load_models(p))
    reloaded = load_models(p)

    assert reloaded.models["a"].extra["variants"] == {"high": {"effort": "high"}}
    assert reloaded.models["b"].extra["variants"] == {"max": {"effort": "max"}}


def test_variants_float_values_round_trip(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
                 'variants = { high = { temperature = 0.7 } }\n')

    save_models(p, load_models(p))
    assert "temperature = 0.7" in p.read_text()
    reloaded = load_models(p)
    # Still a float, not truncated to an int.
    assert reloaded.models["m"].extra["variants"]["high"]["temperature"] == 0.7


def test_variants_presets_table_round_trip(tmp_path):
    """The top-level [variants_presets.<name>] table survives a save/load."""
    p = tmp_path / "models.toml"
    p.write_text('[variants_presets.z-effort]\n'
                 'high = { effort = "high" }\n'
                 'max = { effort = "max" }\n\n'
                 '[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
                 'variants_preset = "z-effort"\n')

    save_models(p, load_models(p))
    reloaded = load_models(p)

    assert reloaded.extra_top["variants_presets"]["z-effort"] == {
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    }
    assert reloaded.models["m"].extra["variants_preset"] == "z-effort"


# --- state --------------------------------------------------------------------

def test_load_state_returns_empty_when_missing(tmp_path):
    assert load_state(tmp_path / "state.toml") == State()


def test_state_round_trip(tmp_path):
    p = tmp_path / "state.toml"
    s = State(active_main="a", last_updated="2026-01-01T00:00:00Z")
    save_state(p, s)
    assert load_state(p) == s


def test_state_omits_none_fields(tmp_path):
    p = tmp_path / "state.toml"
    save_state(p, State())
    text = p.read_text()
    assert "active_main" not in text
    assert "active_small" not in text
    assert "last_updated" not in text