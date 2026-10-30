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
    Registry,
    StoreError,
    registry_from_raw,
)


class ImportError_(Exception):
    """Conversion error (bad source TOML, duplicate model_id, etc.)."""


def import_from_path(path: Union[str, Path]) -> Registry:
    """Read an llmw-format TOML file and convert it to a Registry."""
    return import_from_text(Path(path).read_text(encoding="utf-8"))


def import_from_text(raw_text: str) -> Registry:
    """Parse llmw-format TOML text and convert it to a Registry.

    The source format is models.toml's, so the structure rules live in
    `store.registry_from_raw`; this only re-labels its errors as import
    failures.
    """
    parsed = toml_loads(raw_text)
    if not isinstance(parsed, dict):
        raise ImportError_(f"root must be a TOML table, got {type(parsed).__name__}")

    try:
        return registry_from_raw(parsed)
    except StoreError as e:
        raise ImportError_(str(e))
