"""CLI-level tests for variant presets.

`model use` materializes presets before rendering (in memory only) so
OpenCode gets the V2 `variants` array; `model add`/`remove` rewrite
models.toml through the dumper, which must keep the preset table and the
per-model reference intact.
"""
import json

import pytest

from model_switch.store import load_models

from _cli_runner import invoke_cli as runner


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    return _isolate_yzr_state


MODELS_TOML = (
    '[variants_presets.z-effort]\n'
    'high = { effort = "high" }\n'
    'max = { effort = "max" }\n'
    '\n'
    '[[models]]\n'
    'model_id = "glm-5_3-1m"\n'
    'name = "glm-5.3"\n'
    'base_url = "https://api.example.com"\n'
    'api_key = "K1"\n'
    'context_window = 1000000\n'
    'variants_preset = "z-effort"\n'
    '\n'
    '[[models]]\n'
    'model_id = "inline-1m"\n'
    'name = "inline"\n'
    'base_url = "https://api.kimi.com/coding/"\n'
    'api_key = "K2"\n'
    'variants = { none = { thinking = { type = "disabled" } } }\n'
)


def _seed_models(yzr_paths, text=MODELS_TOML):
    p = yzr_paths["models"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_model_use_renders_expanded_variants(yzr_paths):
    _seed_models(yzr_paths)

    r = runner(["model", "use", "glm-5_3-1m", "--driver", "opencode"])
    assert r.exit_code == 0, r.stdout

    cfg = json.loads(yzr_paths["opencode"].read_text())
    entry = cfg["providers"]["yzr-example"]["models"]["glm-5.3"]
    # The preset's tiers are the whole set, in declaration order — V2
    # computes no built-ins for custom providers, so nothing is muted.
    assert entry["variants"] == [
        {"id": "high", "settings": {"effort": "high"}},
        {"id": "max", "settings": {"effort": "max"}},
    ]
    # An inline declaration renders the same way.
    inline = cfg["providers"]["yzr-kimi"]["models"]["inline"]
    assert inline["variants"] == [
        {"id": "none", "settings": {"thinking": {"type": "disabled"}}},
    ]


def test_model_use_keeps_preset_form_in_models_toml(yzr_paths):
    p = _seed_models(yzr_paths)
    before = p.read_text()

    runner(["model", "use", "glm-5_3-1m", "--driver", "opencode"])

    assert p.read_text() == before


def test_model_add_and_remove_keep_presets_and_references(yzr_paths):
    """add/remove rewrite models.toml through the dumper: the
    [variants_presets] table and the per-model reference must survive."""
    p = _seed_models(yzr_paths)

    assert runner([
        "model", "add", "temp",
        "--base-url", "https://api.example.com", "--api-key", "K3",
        "--model-name", "temp",
    ]).exit_code == 0
    assert runner(["model", "remove", "temp"]).exit_code == 0

    reloaded = load_models(p)
    assert reloaded.extra_top["variants_presets"]["z-effort"] == {
        "high": {"effort": "high"},
        "max": {"effort": "max"},
    }
    assert reloaded.models["glm-5_3-1m"].extra["variants_preset"] == "z-effort"
    assert reloaded.models["inline-1m"].extra["variants"] == {
        "none": {"thinking": {"type": "disabled"}}
    }


def test_model_show_reports_variants(yzr_paths):
    _seed_models(yzr_paths)

    r = runner(["model", "show", "glm-5_3-1m"])

    assert r.exit_code == 0, r.stdout
    assert "variants:       preset 'z-effort' -> high, max" in r.stdout


def test_model_show_reports_inline_variants(yzr_paths):
    _seed_models(yzr_paths)

    r = runner(["model", "show", "inline-1m"])

    assert r.exit_code == 0, r.stdout
    assert "variants:       (inline) -> none" in r.stdout


def test_model_show_reports_no_variants_when_undeclared(yzr_paths):
    """No declaration → no variant selection in OpenCode; say so instead of
    leaving the line out (which would read as an oversight)."""
    _seed_models(yzr_paths, MODELS_TOML.replace(
        'variants_preset = "z-effort"\n', '', 1))

    r = runner(["model", "show", "glm-5_3-1m"])

    assert r.exit_code == 0, r.stdout
    assert "variants:       <none declared>" in r.stdout


def test_model_show_ignores_other_models_broken_presets(yzr_paths):
    """`show <healthy>` is a read-only single-model view: a typo'd preset on
    another model must not take it down (write paths still catch it)."""
    broken = MODELS_TOML + (
        '\n[[models]]\n'
        'model_id = "typo-1m"\n'
        'name = "typo"\n'
        'base_url = "https://api.example.com"\n'
        'api_key = "K9"\n'
        'variants_preset = "does-not-exist"\n'
    )
    _seed_models(yzr_paths, broken)

    r = runner(["model", "show", "glm-5_3-1m"])

    assert r.exit_code == 0, r.stdout
    assert "variants:       preset 'z-effort' -> high, max" in r.stdout


def test_unknown_preset_fails_before_writing_any_config(yzr_paths):
    broken = MODELS_TOML.replace('"z-effort"', '"typo"', 1)
    p = _seed_models(yzr_paths, broken)

    r = runner(["model", "use", "glm-5_3-1m", "--driver", "opencode"])

    assert r.exit_code == 1
    assert "typo" in r.stderr
    assert not yzr_paths["opencode"].exists()
    assert p.read_text() == broken
