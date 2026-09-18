"""Tests for the TOML-backed store."""
import pytest

from model_switch._compat import toml_loads
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
            context_window=200000,
        ),
        "no-ctx": ModelEntry(
            model_id="no-ctx",
            name="n",
            base_url="https://y",
            api_key="K2",
        ),
    })
    save_models(p, reg)
    loaded = load_models(p)
    assert loaded.models["glm"].name == "glm-4-plus"
    assert loaded.models["glm"].api_key == "GLM_API_KEY"
    assert loaded.models["glm"].context_window == 200000
    assert loaded.models["no-ctx"].context_window is None


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


def test_provider_key_round_trips_as_per_model_extra(tmp_path):
    """`provider` is a grouping directive the store doesn't model — it must
    ride in the per-model extras untouched."""
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'provider = "dashscope"\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n')

    reg = load_models(p)
    assert reg.models["m"].extra["provider"] == "dashscope"

    save_models(p, reg)
    assert 'provider = "dashscope"' in p.read_text()
    assert load_models(p).models["m"].extra["provider"] == "dashscope"


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

@pytest.mark.parametrize("toml_text, expected, must_contain", [
    pytest.param(
        # Loader pulls a `[models.variants]` section into the model's extra
        # (never a top-level table), and the dumper writes it back inline.
        '[[models]]\n'
        'model_id = "glm-5_3-1m"\n'
        'name = "glm-5.3"\n'
        'base_url = "u"\n'
        'api_key = "K"\n'
        'reasoning = true\n'
        '\n[models.variants]\n'
        'high = { effort = "high" }\n'
        'max = { effort = "max" }\n',
        {"glm-5_3-1m": {"high": {"effort": "high"}, "max": {"effort": "max"}}},
        ('variants = { high = { effort = "high" }, max = { effort = "max" } }',),
        id="section-input",
    ),
    pytest.param(
        # Two entries carrying variants: the old dumper emitted a duplicate
        # top-level `[variants]` table and tomllib refused the whole file.
        '[[models]]\n'
        'model_id = "a"\nname = "a"\nbase_url = "u"\napi_key = "K"\n'
        'variants = { high = { effort = "high" } }\n'
        '[[models]]\n'
        'model_id = "b"\nname = "b"\nbase_url = "u"\napi_key = "K"\n'
        'variants = { max = { effort = "max" } }\n',
        {"a": {"high": {"effort": "high"}}, "b": {"max": {"effort": "max"}}},
        (),
        id="two-entries",
    ),
    pytest.param(
        # Opaque values survive verbatim: a float must not truncate to int.
        '[[models]]\n'
        'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
        'variants = { high = { temperature = 0.7 } }\n',
        {"m": {"high": {"temperature": 0.7}}},
        ("temperature = 0.7",),
        id="float-values",
    ),
])
def test_variants_round_trip(tmp_path, toml_text, expected, must_contain):
    p = tmp_path / "models.toml"
    p.write_text(toml_text)

    save_models(p, load_models(p))
    text = p.read_text()
    for needle in must_contain:
        assert needle in text
    assert "\n[variants]" not in text

    reloaded = load_models(p)
    assert {k: m.extra["variants"] for k, m in reloaded.models.items()} == expected
    assert reloaded.extra_top.get("variants") is None


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


# --- dumper inline compaction -------------------------------------------------
#
# Tables render inline (`key = { ... }`) when shallow enough; a pure-namespace
# table (no scalars of its own, all children expanding) drops its header. The
# invariant under all of this is plain round-trip equality.

def test_dumper_inlines_preset_tiers_and_skips_namespace_header(tmp_path):
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
                 'variants_preset = "z-effort"\n\n'
                 '[variants_presets.z-effort]\n'
                 'off = { thinking = { type = "disabled" } }\n'
                 'low = { thinking = { type = "adaptive" }, effort = "low" }\n'
                 'high = { thinking = { type = "adaptive" }, effort = "high" }\n'
                 'max = { thinking = { type = "adaptive" }, effort = "max" }\n\n'
                 '[variants_presets.q-budget]\n'
                 'off = { thinking = { type = "disabled" } }\n'
                 'low = { thinking = { type = "enabled", budgetTokens = 8192 } }\n'
                 'high = { thinking = { type = "enabled", budgetTokens = 32768 } }\n')
    before = toml_loads(p.read_text())

    save_models(p, load_models(p))
    text = p.read_text()

    assert "[[models]]" in text
    assert "\n[variants_presets]\n" not in text
    assert "[variants_presets.z-effort]" in text
    assert 'off = { thinking = { type = "disabled" } }' in text
    assert 'low = { thinking = { type = "adaptive" }, effort = "low" }' in text
    assert toml_loads(text) == before


def test_dumper_inlines_small_preset_whole(tmp_path):
    """A short enough root-level table inlines entirely. It must land before
    every [header] — after a header the line would be swallowed by it."""
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n\n'
                 '[variants_presets.z-effort]\n'
                 'high = { effort = "high" }\n'
                 'max = { effort = "max" }\n')
    before = toml_loads(p.read_text())

    save_models(p, load_models(p))
    text = p.read_text()

    assert ('variants_presets = { z-effort = { high = { effort = "high" }, '
            'max = { effort = "max" } } }') in text
    assert text.index("variants_presets =") < text.index("[[models]]")
    assert toml_loads(text) == before


def test_dumper_expands_overlong_subtree(tmp_path):
    """Past the line-length cap the subtree falls back to a [header], while
    each tier inside still inlines."""
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
                 'variants = { low = { effort = "low" }, '
                 'medium = { effort = "medium" }, high = { effort = "high" }, '
                 'xhigh = { effort = "xhigh" }, max = { effort = "max" } }\n')
    before = toml_loads(p.read_text())

    save_models(p, load_models(p))
    text = p.read_text()

    assert "[models.variants]" in text
    assert 'low = { effort = "low" }' in text
    assert 'max = { effort = "max" }' in text
    assert toml_loads(text) == before


def test_dumper_keeps_sibling_extras_out_of_expanded_table(tmp_path):
    """An expanded `[models.variants]` header must not swallow later sibling
    keys: a bare `modalities = ...` line emitted after it would land inside
    the variants table and silently corrupt the round-trip."""
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
                 'modalities = { input = ["text", "image"], output = ["text"] }\n'
                 'variants = { low = { effort = "low" }, '
                 'medium = { effort = "medium" }, high = { effort = "high" }, '
                 'xhigh = { effort = "xhigh" }, max = { effort = "max" } }\n')
    before = toml_loads(p.read_text())

    save_models(p, load_models(p))
    text = p.read_text()
    reloaded = load_models(p)

    assert text.index("modalities = ") < text.index("[models.variants]")
    assert reloaded.models["m"].extra["modalities"] == {
        "input": ["text", "image"], "output": ["text"]}
    assert "modalities" not in reloaded.models["m"].extra["variants"]
    assert toml_loads(text) == before


def test_dumper_empty_table_survives(tmp_path):
    """An empty table must render as `key = {}` — never vanish."""
    p = tmp_path / "models.toml"
    p.write_text('a = {}\n\n'
                 '[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n')
    before = toml_loads(p.read_text())

    save_models(p, load_models(p))
    text = p.read_text()

    assert "a = {}" in text
    assert toml_loads(text) == before


def test_dumper_quotes_non_bare_keys(tmp_path):
    """An inline key containing `.` must be quoted, or it would silently
    become an extra table level."""
    p = tmp_path / "models.toml"
    p.write_text('[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n\n'
                 '[variants_presets."z.effort"]\n'
                 'high = { effort = "high" }\n')
    before = toml_loads(p.read_text())

    save_models(p, load_models(p))
    text = p.read_text()

    assert '"z.effort"' in text
    assert toml_loads(text) == before


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