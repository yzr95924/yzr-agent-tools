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
4. `api_key`      → `api_key` (verbatim; required — the store refuses an
                     entry without it, and so does the converter)
5. `context_window` → read as int if present; `None` if absent. NO
                     reverse-engineering from `name` suffix.
6. `is_default`   → preserved in `extra` (model-switch doesn't read it).
7. Unknown top-level keys and per-model keys flow through to `extra`.
"""
from pathlib import Path
from typing import Any, Dict, Union

from model_switch._compat import toml_loads
from model_switch.store import (
    ModelEntry,
    Registry,
    StoreError,
    entry_from_dict,
)


class ImportError_(Exception):
    """Conversion error (bad source TOML, duplicate model_id, etc.)."""


def _convert_entry(src: Dict[str, Any]) -> ModelEntry:
    """Convert one llmw `[[models]]` entry via the store's own schema.

    The conversion rules and the required-field list live in
    `store.entry_from_dict`; this only re-labels its errors as import
    failures.
    """
    try:
        return entry_from_dict(src)
    except StoreError as e:
        raise ImportError_(str(e))


def import_from_path(path: Union[str, Path]) -> Registry:
    """Read an llmw-format TOML file and convert it to a Registry."""
    return import_from_text(Path(path).read_text(encoding="utf-8"))


def import_from_text(raw_text: str) -> Registry:
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
        converted = _convert_entry(entry)
        if converted.model_id in reg.models:
            raise ImportError_(
                f"duplicate model_id {converted.model_id!r} in source"
            )
        reg.models[converted.model_id] = converted

    return reg
