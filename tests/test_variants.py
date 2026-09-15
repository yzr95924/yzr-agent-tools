"""Tests for variant-preset expansion (`model_switch.variants`).

Presets are user data declared in models.toml; expansion turns a reference
into the plain `variants` dict the OpenCode driver renders. The last test in
this file is a structural guard: no model or gateway names may appear in the
conversion code, so adding a model/upstream stays a models.toml edit.
"""
import ast
import re
from pathlib import Path

import pytest

from model_switch.store import ModelEntry, Registry, load_models, save_models
from model_switch.variants import (
    PRESETS_KEY,
    PRESET_REF_KEY,
    VARIANTS_KEY,
    VariantsError,
    expand,
    expand_model,
)


def _entry(model_id="m", **extra):
    """A ModelEntry carrying `extra` (the fields model-switch doesn't own)."""
    return ModelEntry(
        model_id=model_id,
        name=model_id,
        base_url="https://api.example.com",
        api_key="K",
        extra=extra,
    )


def _registry(models, presets=None):
    top = {PRESETS_KEY: presets} if presets is not None else {}
    return Registry(models={m.model_id: m for m in models}, extra_top=top)


EFFORT_PRESET = {"high": {"effort": "high"}, "max": {"effort": "max"}}


# --- expansion ----------------------------------------------------------------

def test_expand_materializes_preset_and_keeps_the_reference():
    reg = _registry(
        [_entry(variants_preset="z-effort")],
        presets={"z-effort": EFFORT_PRESET},
    )

    out = expand(reg)

    assert out[0].extra[VARIANTS_KEY] == EFFORT_PRESET
    # The reference stays so the entry can be saved back in preset form.
    assert out[0].extra[PRESET_REF_KEY] == "z-effort"
    # The input registry is untouched, and the expanded entry is a copy.
    assert VARIANTS_KEY not in reg.models["m"].extra
    assert out[0] is not reg.models["m"]


def test_expand_without_reference_returns_the_same_object():
    model = _entry()
    reg = _registry([model], presets={"unused": EFFORT_PRESET})

    out = expand(reg)

    assert out[0] is model


def test_expand_inline_variants_override_the_preset_fieldwise():
    reg = _registry(
        [_entry(variants_preset="p", variants={
            "high": {"effort": "low"},          # field-level override
            "extra": {"disabled": True},        # additional tier
        })],
        presets={"p": {"high": {"effort": "high", "thinking": {"type": "adaptive"}}}},
    )

    out = expand(reg)

    assert out[0].extra[VARIANTS_KEY] == {
        # effort overridden by the model, thinking inherited from the preset
        "high": {"effort": "low", "thinking": {"type": "adaptive"}},
        "extra": {"disabled": True},
    }


def test_expand_unknown_preset_lists_available_names():
    reg = _registry([_entry(variants_preset="nope")],
                    presets={"z-effort": EFFORT_PRESET})

    with pytest.raises(VariantsError) as e:
        expand(reg)

    assert "nope" in str(e.value)
    assert "z-effort" in str(e.value)


def test_expand_empty_preset_is_an_error_not_an_unknown_name():
    """An empty tier table is a distinct mistake from a typo'd name — the
    message must not claim the (existing) preset is unknown."""
    reg = _registry([_entry(variants_preset="empty")], presets={"empty": {}})

    with pytest.raises(VariantsError) as e:
        expand(reg)

    assert "no tiers" in str(e.value)


def test_expand_reference_without_presets_table():
    reg = _registry([_entry(variants_preset="z-effort")])

    with pytest.raises(VariantsError):
        expand(reg)


def test_expand_rejects_non_string_reference():
    reg = _registry([_entry(variants_preset=1)],
                    presets={"z-effort": EFFORT_PRESET})

    with pytest.raises(VariantsError):
        expand(reg)


def test_expand_rejects_non_table_tier():
    reg = _registry([_entry(variants_preset="bad")],
                    presets={"bad": {"high": "high"}})

    with pytest.raises(VariantsError) as e:
        expand(reg)

    assert "high" in str(e.value)


def test_expand_rejects_inline_tier_that_is_not_a_table():
    """Inline variants get the same shape check as presets — OpenCode would
    otherwise reject the whole config file."""
    reg = _registry([_entry(variants={"high": "high"})])

    with pytest.raises(VariantsError) as e:
        expand(reg)

    assert "high" in str(e.value)


def test_expand_rejects_inline_variants_that_are_not_a_table():
    reg = _registry([_entry(variants_preset="z-effort", variants="high")],
                    presets={"z-effort": EFFORT_PRESET})

    with pytest.raises(VariantsError) as e:
        expand(reg)

    assert "must be a table" in str(e.value)


def test_expand_model_skips_other_models_errors():
    """`expand_model` touches one entry only — `model show <healthy>` must
    not fail because another model's preset is broken."""
    healthy = _entry(variants_preset="z-effort")
    broken = _entry(model_id="broken", variants_preset="typo")
    reg = _registry([broken, healthy], presets={"z-effort": EFFORT_PRESET})

    out = expand_model(reg, healthy)

    assert out.extra["variants"] == EFFORT_PRESET
    with pytest.raises(VariantsError):
        expand_model(reg, broken)


def test_expansion_is_never_saved_back(tmp_path):
    """save_models must receive the raw registry: the file keeps the preset
    and the reference, never the materialized tiers."""
    p = tmp_path / "models.toml"
    p.write_text('[variants_presets.z-effort]\n'
                 'high = { effort = "high" }\n'
                 'max = { effort = "max" }\n\n'
                 '[[models]]\n'
                 'model_id = "m"\nname = "n"\nbase_url = "u"\napi_key = "K"\n'
                 'variants_preset = "z-effort"\n')

    reg = load_models(p)
    assert expand(reg)[0].extra[VARIANTS_KEY]  # expansion does something...
    save_models(p, reg)                        # ...but only the raw reg is saved

    reloaded = load_models(p)
    assert reloaded.models["m"].extra[PRESET_REF_KEY] == "z-effort"
    assert VARIANTS_KEY not in reloaded.models["m"].extra
    assert "z-effort" in reloaded.extra_top[PRESETS_KEY]


# --- structural guard: no per-model knowledge in the conversion code ----------

_FORBIDDEN = re.compile(
    r"kimi|glm|qwen|minimax|deepseek|moonshot|z\.ai|bigmodel", re.IGNORECASE
)

_SRC = Path(__file__).resolve().parent.parent / "src" / "model_switch"
_GUARDED = [_SRC / "variants.py", _SRC / "drivers" / "opencode.py"]


def _str_const(node):
    """String value of a literal node, or None (3.7 `ast.Str` / 3.8+ `Constant`)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if node.__class__.__name__ == "Str":  # Python 3.7 parses strings as ast.Str
        return getattr(node, "s", None)
    return None


def _code_tokens(path):
    """Identifiers + non-docstring string literals (comments are dropped by
    the parser, docstrings are excluded explicitly)."""
    tree = ast.parse(Path(path).read_text())
    doc_positions = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and _str_const(body[0].value) is not None:
                doc_positions.add((body[0].value.lineno, body[0].value.col_offset))

    tokens = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) or node.__class__.__name__ == "Str":
            s = _str_const(node)
            if s is not None and (node.lineno, node.col_offset) not in doc_positions:
                tokens.append(s)
        elif isinstance(node, ast.Name):
            tokens.append(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.append(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            tokens.append(node.name)
        elif isinstance(node, ast.arg):
            tokens.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            tokens.append(node.arg)
    return tokens


@pytest.mark.parametrize("path", _GUARDED, ids=lambda p: p.name)
def test_no_model_names_in_conversion_code(path):
    """`variants.py` and the opencode driver must stay model-agnostic: tiers
    are data (models.toml presets), so no model/gateway name may appear in
    code. Docstrings and comments may cite examples."""
    hits = [t for t in _code_tokens(path) if _FORBIDDEN.search(t)]
    assert hits == []
