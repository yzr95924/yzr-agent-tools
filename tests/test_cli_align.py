"""CLI integration tests for `model align` and catalog-derived `model add`.

The catalog cache is a fixture database (never the real one — conftest
isolates `paths.catalog_db_file` into tmp), so these tests are deterministic
and offline. `align` writes models.toml and re-renders opencode.json; `add`
derives fields when a host-matching catalog entry exists.
"""
import json

import pytest

from _catalog_db import write_catalog_db as _write_catalog
from model_switch.store import load_models

from _cli_runner import invoke_cli as runner


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    return _isolate_yzr_state


def _entry(options, context=1000000, modalities=None):
    e = {
        "reasoning_options": options,
        "limit": {"context": context, "output": 131072},
    }
    if modalities is not None:
        e["modalities"] = {"input": modalities, "output": ["text"]}
    return e


def _write_models(path, text):
    path.write_text(text, encoding="utf-8")


MODEL_TOML = (
    "[[models]]\n"
    'provider = "fixture"\n'
    'model_id = "m"\n'
    'name = "fixture-model"\n'
    'base_url = "https://api.fixture.com/anthropic"\n'
    'api_key = "K"\n'
    "context_window = 100\n"
    'variants = { low = { effort = "low", thinking = { type = "adaptive" } } }\n'
)

CATALOG = {
    "fixture": {
        "api": "https://api.fixture.com/compatible-mode/v1",
        "models": {
            "fixture-model": _entry(
                [{"type": "toggle"},
                 {"type": "effort", "values": ["low", "medium"]}],
                context=500000,
                modalities=["text", "image", "video"],
            ),
        },
    },
}


def test_align_updates_inline_fields_and_renders(yzr_paths):
    _write_models(yzr_paths["models"], MODEL_TOML)
    _write_catalog(yzr_paths["catalog"], CATALOG)
    runner(["model", "use", "m", "--driver", "opencode"])

    result = runner(["model", "align"])

    assert result.exit_code == 0, result.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert m.context_window == 500000
    assert m.extra["variants"] == {
        "low": {"effort": "low", "thinking": {"type": "adaptive"}},
        "medium": {"effort": "medium", "thinking": {"type": "adaptive"}},
    }
    assert m.extra["modalities"] == {"input": ["text", "image"], "output": ["text"]}
    # The agent-facing render picked the new tiers up: declared tiers are the
    # whole set, in declaration order.
    cfg = json.loads(yzr_paths["opencode"].read_text())
    entry = cfg["providers"]["yzr-fixture"]["models"]["fixture-model"]
    assert [v["id"] for v in entry["variants"]] == ["low", "medium"]
    assert entry["limit"]["context"] == 500000
    assert entry["capabilities"]["input"] == ["text", "image"]


def test_align_derives_display_name(yzr_paths):
    """The human-readable name is derived like the other catalog fields —
    and a second run is a no-op."""
    _write_models(yzr_paths["models"], MODEL_TOML)
    entry = _entry([{"type": "effort", "values": ["low"]}], context=500000)
    entry["name"] = "Fixture Model"
    _write_catalog(yzr_paths["catalog"], {
        "fixture": {"api": "https://api.fixture.com/compatible-mode/v1",
                    "models": {"fixture-model": entry}},
    })
    runner(["model", "use", "m", "--driver", "opencode"])

    result = runner(["model", "align"])

    assert result.exit_code == 0, result.stdout
    assert "display_name→Fixture Model" in result.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert m.extra["display_name"] == "Fixture Model"
    cfg = json.loads(yzr_paths["opencode"].read_text())
    rendered = cfg["providers"]["yzr-fixture"]["models"]["fixture-model"]
    assert rendered["name"] == "Fixture Model"

    again = runner(["model", "align"])
    assert again.exit_code == 0, again.stdout
    assert "no change" in again.stdout


def test_align_skips_display_name_equal_to_the_upstream_id(yzr_paths):
    """A display name equal to the upstream id is not repeated."""
    _write_models(yzr_paths["models"], MODEL_TOML)
    entry = _entry([{"type": "effort", "values": ["low"]}], context=500000)
    entry["name"] = "fixture-model"   # same as the upstream id
    _write_catalog(yzr_paths["catalog"], {
        "fixture": {"api": "https://api.fixture.com/compatible-mode/v1",
                    "models": {"fixture-model": entry}},
    })
    runner(["model", "use", "m", "--driver", "opencode"])

    result = runner(["model", "align"])

    assert result.exit_code == 0, result.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert "display_name" not in m.extra
    cfg = json.loads(yzr_paths["opencode"].read_text())
    rendered = cfg["providers"]["yzr-fixture"]["models"]["fixture-model"]
    assert "name" not in rendered


def test_align_reports_and_keeps_preset_backed_variants(yzr_paths):
    _write_models(yzr_paths["models"], (
        "[[models]]\n"
        'model_id = "m"\nname = "fixture-model"\n'
        'base_url = "https://api.fixture.com/anthropic"\napi_key = "K"\n'
        'variants_preset = "p"\n'
        "[variants_presets.p]\n"
        'low = { effort = "low", thinking = { type = "adaptive" } }\n'
    ))
    _write_catalog(yzr_paths["catalog"], CATALOG)

    result = runner(["model", "align"])

    # Variants stay unresolved (the shared preset is not rewritten) → nonzero.
    assert result.exit_code == 1
    assert "left alone" in result.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert m.context_window == 500000          # scalars still aligned
    assert m.extra["variants_preset"] == "p"   # reference intact
    assert "variants" not in m.extra


def test_align_is_idempotent(yzr_paths):
    _write_models(yzr_paths["models"], MODEL_TOML)
    _write_catalog(yzr_paths["catalog"], CATALOG)
    runner(["model", "align"])
    first = yzr_paths["models"].read_bytes()

    result = runner(["model", "align"])

    assert result.exit_code == 0
    assert "0 updated" in result.stdout
    assert yzr_paths["models"].read_bytes() == first


def test_align_single_model_with_pin_resolves_conflict(yzr_paths):
    _write_models(yzr_paths["models"], MODEL_TOML)
    _write_catalog(yzr_paths["catalog"], {
        "a": {"api": "https://api.fixture.com/v1",
              "models": {"fixture-model": _entry(
                  [{"type": "effort", "values": ["low"]}], context=111)}},
        "b": {"api": "https://api.fixture.com/v2",
              "models": {"fixture-model": _entry(
                  [{"type": "effort", "values": ["high"]}], context=222)}},
    })

    conflict = runner(["model", "align"])
    assert conflict.exit_code == 1
    assert "conflicting" in conflict.stdout

    pinned = runner(["model", "align", "m", "--catalog-provider", "b"])
    assert pinned.exit_code == 0, pinned.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert m.context_window == 222
    assert list(m.extra["variants"]) == ["high"]


def test_align_pin_requires_single_model(yzr_paths):
    _write_models(yzr_paths["models"], MODEL_TOML + (
        "[[models]]\n"
        'model_id = "m2"\nname = "fixture-model"\n'
        'base_url = "https://api.fixture.com/anthropic"\napi_key = "K"\n'
    ))
    _write_catalog(yzr_paths["catalog"], CATALOG)
    result = runner(["model", "align", "--catalog-provider", "fixture"])
    assert result.exit_code == 1
    assert "single model" in result.stdout


def test_align_unknown_model_errors(yzr_paths):
    _write_models(yzr_paths["models"], MODEL_TOML)
    _write_catalog(yzr_paths["catalog"], CATALOG)
    result = runner(["model", "align", "nope"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_align_without_cache_errors(yzr_paths):
    _write_models(yzr_paths["models"], MODEL_TOML)
    result = runner(["model", "align"])
    assert result.exit_code == 1
    assert "no catalog cache" in result.stdout


def test_add_derives_fields_from_catalog(yzr_paths):
    _write_catalog(yzr_paths["catalog"], CATALOG)
    result = runner([
        "model", "add", "m",
        "--model-name", "fixture-model",
        "--base-url", "https://api.fixture.com/anthropic",
        "--api-key", "K",
    ])
    assert result.exit_code == 0, result.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert m.context_window == 500000
    assert list(m.extra["variants"]) == ["low", "medium"]
    assert m.extra["modalities"] == {"input": ["text", "image"], "output": ["text"]}


def test_add_no_catalog_skips_derivation(yzr_paths):
    _write_catalog(yzr_paths["catalog"], CATALOG)
    result = runner([
        "model", "add", "m",
        "--model-name", "fixture-model",
        "--base-url", "https://api.fixture.com/anthropic",
        "--api-key", "K",
        "--no-catalog",
    ])
    assert result.exit_code == 0, result.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert m.context_window is None
    assert "variants" not in m.extra
    assert "catalog:" not in result.stdout


def test_add_conflict_never_guesses(yzr_paths):
    _write_catalog(yzr_paths["catalog"], {
        "a": {"api": "https://api.fixture.com/v1",
              "models": {"fixture-model": _entry(
                  [{"type": "effort", "values": ["low"]}], context=111)}},
        "b": {"api": "https://api.fixture.com/v2",
              "models": {"fixture-model": _entry(
                  [{"type": "effort", "values": ["high"]}], context=222)}},
    })
    result = runner([
        "model", "add", "m",
        "--model-name", "fixture-model",
        "--base-url", "https://api.fixture.com/anthropic",
        "--api-key", "K",
    ])
    assert result.exit_code == 0, result.stdout
    assert "conflicting" in result.stdout
    m = load_models(yzr_paths["models"]).models["m"]
    assert m.context_window is None
    assert "variants" not in m.extra
