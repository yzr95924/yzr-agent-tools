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
from typing import Any, Dict, Optional

from model_switch._compat import toml_dump, toml_loads


# Fields model-switch understands on a `[[models]]` entry. Anything else on
# an entry (e.g. `api_key`, `is_default` from llmw's workspace_models.toml)
# is preserved in `ModelEntry.extra` and round-tripped verbatim.
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


# ---- models.toml -------------------------------------------------------------

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
        if not isinstance(entry, dict):
            raise StoreError(
                "models.toml: each [[models]] entry must be a table, got: {!r}".format(type(entry))
            )

        # Required fields
        for required in ("model_id", "name", "base_url"):
            if required not in entry:
                raise MissingRequiredField(
                    "models.toml: [[models]] entry missing {!r}: {}".format(
                        required, entry
                    )
                )

        # `api_key` is required — it's the sole credential source.
        if "api_key" not in entry:
            raise MissingRequiredField(
                "models.toml: [[models]] entry must have 'api_key': {}".format(entry)
            )

        model_id = str(entry["model_id"])
        if model_id in reg.models:
            raise DuplicateModelId(
                "models.toml: duplicate model_id {!r}".format(model_id)
            )

        # Optional fields
        cw = entry.get("context_window")
        if cw is not None and not isinstance(cw, int):
            raise InvalidContextWindow(
                "models.toml: context_window must be int, got: {!r}".format(type(cw))
            )

        # Anything else goes into extra.
        extra = {
            k: v for k, v in entry.items() if k not in _MODEL_ENTRY_FIELDS
        }

        reg.models[model_id] = ModelEntry(
            model_id=model_id,
            name=str(entry["name"]),
            base_url=str(entry["base_url"]),
            api_key=(str(entry["api_key"]) if entry.get("api_key") else None),
            context_window=cw,
            description=(str(entry["description"]) if entry.get("description") else None),
            extra=extra,
        )
    return reg


def save_models(path: Path, reg: Registry) -> None:
    """Atomic write of `models.toml`. Preserves unknown top-level + per-model keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = reg.to_toml_dict()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        toml_dump(raw, f)
    os.replace(tmp, path)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: Dict[str, Any] = {}
    if state.active_main is not None:
        raw["active_main"] = state.active_main
    if state.last_updated is not None:
        raw["last_updated"] = state.last_updated
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        toml_dump(raw, f)
    os.replace(tmp, path)