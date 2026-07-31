"""Importer from llmw's `workspace_models.toml` into model-switch's
`models.toml`.

Why a separate module: the conversion logic is pure (no I/O, no CLI), so
it's testable in isolation and can be reused by tools that want to
ingest llmw's format without going through the CLI.

Conversion rules (per `[[models]]` entry):

1. `model_id`     → `model_id` (verbatim)
2. `name`         → `name`  (verbatim; we do NOT strip suffixes or
                                 reverse-engineer anything from the id)
3. `base_url`     → `base_url` (verbatim)
4. `api_key`      → `api_key` (verbatim). The raw key is persisted.
                     `models.toml` is treated as a local-only config file
                     (same trust model as llmw's `workspace_models.toml`).
5. `context_window` → read as int if present; `None` if absent. NO
                     reverse-engineering from `name` suffix.
6. `is_default`   → preserved in `extra` (model-switch doesn't read it).
7. Unknown top-level keys and per-model keys flow through to `extra`.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Union

from model_switch.store import ModelEntry, Registry, toml_loads


class ImportError_(Exception):
    """Conversion error (bad source TOML, duplicate model_id, etc.)."""


@dataclass
class ImportResult:
    """Result of converting one source TOML."""
    registry: Registry


def _convert_entry(src: Dict[str, Any]) -> ModelEntry:
    """Convert one llmw `[[models]]` entry to a ModelEntry."""
    if "model_id" not in src:
        raise ImportError_("missing required field 'model_id'")
    if "name" not in src:
        raise ImportError_(f"missing required field 'name' for model_id={src.get('model_id')!r}")
    if "base_url" not in src:
        raise ImportError_(
            f"missing required field 'base_url' for model_id={src.get('model_id')!r}"
        )

    model_id = str(src["model_id"])
    api_key = str(src["api_key"]) if src.get("api_key") else None

    # Reverse-engineering policy: only read explicit `context_window`.
    # If absent, leave it as None — driver will write the bare model id.
    if "context_window" in src:
        cw = src["context_window"]
        if not isinstance(cw, int):
            raise ImportError_(
                f"model_id={model_id!r}: context_window must be int, got {type(cw).__name__}"
            )
        context_window = cw
    else:
        context_window = None

    # Preserve unknown fields (e.g. `is_default`) in `extra`.
    extra = {
        k: v for k, v in src.items()
        if k not in ("model_id", "name", "base_url",
                     "api_key", "context_window", "description")
    }

    return ModelEntry(
        model_id=model_id,
        name=str(src["name"]),
        base_url=str(src["base_url"]),
        api_key=api_key,
        context_window=context_window,
        description=(str(src["description"]) if src.get("description") else None),
        extra=extra,
    )


def import_from_path(path: Union[str, Path]) -> ImportResult:
    """Read an llmw-format TOML file and convert it to a Registry."""
    return import_from_text(Path(path).read_text(encoding="utf-8"))


def import_from_text(raw_text: str) -> ImportResult:
    """Parse llmw-format TOML text and convert it to a Registry."""
    parsed = toml_loads(raw_text)
    if not isinstance(parsed, dict):
        raise ImportError_(f"root must be a TOML table, got {type(parsed).__name__}")

    reg = Registry()
    # Preserve unknown top-level keys (schema_version, created_at, updated_at).
    for k, v in parsed.items():
        if k == "models":
            continue
        reg.extra_top[k] = v

    for entry in parsed.get("models", []) or []:
        if not isinstance(entry, dict):
            raise ImportError_(
                f"each [[models]] entry must be a table, got {type(entry).__name__}"
            )
        converted = _convert_entry(entry)
        if converted.model_id in reg.models:
            raise ImportError_(
                f"duplicate model_id {converted.model_id!r} in source"
            )
        reg.models[converted.model_id] = converted

    return ImportResult(registry=reg)
