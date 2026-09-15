"""Variant-preset expansion for the OpenCode driver.

`models.toml` can define a named tier table once::

    [variants_presets.z-effort]
    high = { effort = "high" }
    max  = { effort = "max" }

and models reference it with a single line::

    [[models]]
    name = "glm-5.3"
    variants_preset = "z-effort"

`expand()` materializes the reference into the plain `variants` dict the
OpenCode driver already understands (a model's own hand-written
`[models.variants]` wins field-by-field, so it doubles as an escape hatch).
Expansion happens in memory, right before drivers render, and the result is
never written back to `models.toml` — the file keeps the preset + reference
form. Drivers know nothing about presets; they only pass `reasoning` and
`variants` through.

Tier *bodies* must be tables (both in a preset and inline) — that one shape
is checked here so a typo fails locally; OpenCode rejects the whole config
for it (``Expected object, got "high" provider.<id>.models.<name>.variants.high``).
Payload content is never inspected.

Presets are pure data supplied by the user: no model names, gateways or
payload shapes live in this module (guarded by test_variants.py), so adding
a model or an upstream is a models.toml edit, never a code change.
"""
from dataclasses import replace
from typing import Any, Dict, List

from model_switch.store import ModelEntry, Registry


# Top-level table holding named tier tables: [variants_presets.<name>].
PRESETS_KEY = "variants_presets"

# Per-model reference to one of those names.
PRESET_REF_KEY = "variants_preset"

# Per-model tier table (hand-written escape hatch; overrides the preset).
VARIANTS_KEY = "variants"


class VariantsError(Exception):
    """A model's variant declaration can't be resolved or is malformed."""


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge `override` into `base` (override wins per field, recursively).

    Neither input is mutated; merged branches get fresh dicts.
    """
    out = dict(base)
    for k, v in override.items():
        cur = out.get(k)
        if isinstance(cur, dict) and isinstance(v, dict):
            out[k] = _deep_merge(cur, v)
        else:
            out[k] = v
    return out


def _check_shape(where: str, variants: Any) -> None:
    """Reject a `variants` declaration that OpenCode would reject wholesale.

    Tiers must map to tables; a scalar body makes OpenCode refuse the entire
    config file, so fail here where the message can name the model/preset.
    Payload *content* is passed through untouched (OpenCode validates it).
    """
    if not isinstance(variants, dict):
        raise VariantsError(
            "{}: {} must be a table, got {}".format(
                where, VARIANTS_KEY, type(variants).__name__
            )
        )
    for tier, body in variants.items():
        if not isinstance(body, dict):
            raise VariantsError(
                "{}: tier {!r} must be a table, got {}".format(
                    where, tier, type(body).__name__
                )
            )


def expand_model(reg: Registry, model: ModelEntry) -> ModelEntry:
    """Materialize one model's preset reference (see `expand`)."""
    ref = model.extra.get(PRESET_REF_KEY)
    inline = model.extra.get(VARIANTS_KEY)

    if ref is None:
        if inline is not None:
            _check_shape("model {!r}".format(model.model_id), inline)
        return model

    if not isinstance(ref, str):
        raise VariantsError(
            "model {!r}: {} must be a string, got {}".format(
                model.model_id, PRESET_REF_KEY, type(ref).__name__
            )
        )
    presets = reg.extra_top.get(PRESETS_KEY)
    if not isinstance(presets, dict) or not presets:
        raise VariantsError(
            "model {!r} references preset {!r} but models.toml declares no "
            "[{}] entries".format(model.model_id, ref, PRESETS_KEY)
        )
    preset = presets.get(ref)
    if not isinstance(preset, dict):
        raise VariantsError(
            "model {!r}: unknown preset {!r}; available: {}".format(
                model.model_id, ref, ", ".join(sorted(presets)) or "<none>"
            )
        )
    if not preset:
        raise VariantsError(
            "model {!r}: preset {!r} declares no tiers".format(model.model_id, ref)
        )
    if inline is not None and not isinstance(inline, dict):
        raise VariantsError(
            "model {!r}: {} must be a table, got {}".format(
                model.model_id, VARIANTS_KEY, type(inline).__name__
            )
        )

    merged = _deep_merge(preset, inline or {})
    _check_shape("model {!r} (preset {!r})".format(model.model_id, ref), merged)

    extra = dict(model.extra)
    extra[VARIANTS_KEY] = merged
    return replace(model, extra=extra)


def expand(reg: Registry) -> List[ModelEntry]:
    """Materialize `variants_preset` references into `extra["variants"]`.

    Entries without a reference are returned as the same object (no copy);
    entries with one get a copy whose `extra` is a new dict, leaving `reg`
    untouched. Intended to be called just before handing models to a driver.
    """
    return [expand_model(reg, model) for model in reg.models.values()]
