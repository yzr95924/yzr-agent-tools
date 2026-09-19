"""TOML-backed store for models and state.

Designed for cross-tool reuse: a `models.toml` produced by `llmw` (with
`[[models]]`, `schema_version`, `created_at`, `updated_at`, `api_key`,
`is_default`, etc.) can be loaded directly. model-switch reads only the
fields it needs; everything else is preserved verbatim and written back
untouched on the next save.

Round-trip invariant: `save_models(load_models(p), p) == load_models(p)`
modulo our own field renames, AND unknown top-level keys + unknown
per-model keys survive a load/save cycle.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from model_switch._compat import toml_dumps, toml_loads


# Fields model-switch understands on a `[[models]]` entry. Anything else on
# an entry (e.g. llmw's `is_default`) is preserved in `ModelEntry.extra` and
# round-tripped verbatim.
_MODEL_ENTRY_FIELDS = (
    "model_id",
    "name",
    "base_url",
    "api_key",
    "context_window",
    "description",
)


class StoreError(Exception):
    """Base for store-level errors."""


class MissingRequiredField(StoreError):
    """A required field is missing from a [[models]] entry."""


class DuplicateModelId(StoreError):
    """Two [[models]] entries share the same model_id."""


class InvalidContextWindow(StoreError):
    """context_window was present but not a positive integer."""


@dataclass
class ModelEntry:
    """One model definition, plus any fields model-switch doesn't own."""
    model_id: str
    name: str
    base_url: str
    api_key: Optional[str] = None
    context_window: Optional[int] = None
    description: Optional[str] = None
    # Keys not in _MODEL_ENTRY_FIELDS are stored here and round-tripped.
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_toml_dict(self) -> Dict[str, Any]:
        """Serialize as a dict in load order, with extras appended."""
        out: Dict[str, Any] = dict(self.extra)  # extras first
        out["model_id"] = self.model_id
        out["name"] = self.name
        out["base_url"] = self.base_url
        if self.api_key is not None:
            out["api_key"] = self.api_key
        if self.context_window is not None:
            out["context_window"] = self.context_window
        if self.description:
            out["description"] = self.description
        return out


@dataclass
class Registry:
    """Top-level models.toml content.

    `models` is the parsed [[models]] entries. `extra_top` holds keys at
    the top level we don't manage (e.g. llmw's `schema_version`,
    `created_at`, `updated_at`).
    """
    models: Dict[str, ModelEntry] = field(default_factory=dict)
    extra_top: Dict[str, Any] = field(default_factory=dict)

    def to_toml_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = dict(self.extra_top)
        out["models"] = [m.to_toml_dict() for m in self.models.values()]
        return out


@dataclass
class State:
    active_main: Optional[str] = None
    last_updated: Optional[str] = None


# ---- provider grouping -------------------------------------------------------
#
# One agent-side provider block carries one baseURL and one apiKey, so a block
# is shareable exactly when those two match. The declared `provider` name (when
# present) is the group's identity: it names the block and outlives base_url
# changes. This rule is shared by the CLI — which inherits a group name when a
# model is added to an upstream that already declares one, see
# `model_switch.cli._resolve_provider` — and by the agent drivers that render
# the blocks. Keep it here so both read the same definition.
#
# Error type: these functions raise `ValueError`, not the `StoreError` family
# above. That family covers *load-time structure* (a malformed models.toml,
# raised by `load_models` before any command runs). These predicates are
# evaluated while a command is already running, at the same boundaries as the
# drivers' own render-time validation, and both are surfaced by the CLI's
# `except ValueError` handlers — so they fail one line cleanly instead of
# escaping as a traceback.

def upstream_key(model: ModelEntry) -> Tuple[str, str]:
    """``(base_url, api_key)`` — what a shareable provider block must agree on."""
    return (model.base_url, model.api_key or "")


def provider_group_key(model: ModelEntry) -> Tuple[Optional[str], str, str]:
    """``(declared name, base_url, api_key)`` — one provider block per key.

    ``extra["provider"]`` is the declaration; a value that is neither absent
    nor a string is rejected loudly rather than silently treated as undeclared
    (it would render an unusable provider id).
    """
    value = model.extra.get("provider")
    if value is None:
        name = None
    elif isinstance(value, str):
        name = value
    else:
        raise ValueError(
            "model {!r}: provider must be a string, got {}".format(
                model.model_id, type(value).__name__))
    return (name,) + upstream_key(model)


# ---- atomic io ---------------------------------------------------------------

def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` via `<path>.tmp` + `os.replace` — never a half-written file.

    Shared by this store and the drivers' JSON writer (`drivers._atomic`), so
    the atomicity rule has one implementation.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ---- models.toml -------------------------------------------------------------

def entry_from_dict(entry: Dict[str, Any]) -> ModelEntry:
    """Validate and convert one ``[[models]]`` table.

    The single owner of the entry schema — required fields (``api_key``
    included: it is the sole credential source), the ``context_window``
    type, the known/unknown split from `_MODEL_ENTRY_FIELDS`, and the
    api_key/description normalization. `load_models` and the llmw importer
    both go through it, so an imported file cannot produce an entry that
    `load_models` would then refuse.
    """
    if not isinstance(entry, dict):
        raise StoreError(
            "each [[models]] entry must be a table, got: {!r}".format(type(entry)))
    for required in ("model_id", "name", "base_url"):
        if required not in entry:
            raise MissingRequiredField(
                "[[models]] entry missing {!r}: {}".format(required, entry))
    if not entry.get("api_key"):
        raise MissingRequiredField(
            "[[models]] entry must have 'api_key': {}".format(entry))
    context_window = entry.get("context_window")
    if context_window is not None and not isinstance(context_window, int):
        raise InvalidContextWindow(
            "context_window must be int, got: {!r}".format(type(context_window)))
    return ModelEntry(
        model_id=str(entry["model_id"]),
        name=str(entry["name"]),
        base_url=str(entry["base_url"]),
        api_key=str(entry["api_key"]),
        context_window=context_window,
        description=(str(entry["description"]) if entry.get("description") else None),
        extra={k: v for k, v in entry.items() if k not in _MODEL_ENTRY_FIELDS},
    )


def load_models(path: Path) -> Registry:
    """Load `models.toml`. Missing file -> empty Registry.

    Unknown top-level keys are preserved in `Registry.extra_top`; unknown
    per-model keys are preserved in `ModelEntry.extra`.
    """
    if not path.exists():
        return Registry()
    raw = toml_loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StoreError("models.toml root must be a table, got: {!r}".format(type(raw)))

    reg = Registry()
    for k, v in raw.items():
        if k == "models":
            continue
        reg.extra_top[k] = v

    for entry in raw.get("models", []) or []:
        model = entry_from_dict(entry)
        if model.model_id in reg.models:
            raise DuplicateModelId(
                "models.toml: duplicate model_id {!r}".format(model.model_id))
        reg.models[model.model_id] = model
    return reg


def save_models(path: Path, reg: Registry) -> None:
    """Atomic write of `models.toml`. Preserves unknown top-level + per-model keys."""
    atomic_write_text(path, toml_dumps(reg.to_toml_dict()))


# ---- state.toml --------------------------------------------------------------

def load_state(path: Path) -> State:
    """Load `state.toml`. Missing file -> empty State."""
    if not path.exists():
        return State()
    raw = toml_loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StoreError("state.toml root must be a table, got: {!r}".format(type(raw)))
    return State(
        active_main=(str(raw["active_main"]) if raw.get("active_main") else None),
        last_updated=(str(raw["last_updated"]) if raw.get("last_updated") else None),
    )


def save_state(path: Path, state: State) -> None:
    """Atomic write of `state.toml`."""
    raw: Dict[str, Any] = {}
    if state.active_main is not None:
        raw["active_main"] = state.active_main
    if state.last_updated is not None:
        raw["last_updated"] = state.last_updated
    atomic_write_text(path, toml_dumps(raw))