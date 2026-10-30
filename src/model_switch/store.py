"""Canonical-alias TOML registry of OpenCode models (models.toml).

One ``[[models]]`` entry per custom model. The entry owns only what makes the
alias custom: the final ``yzr-*`` provider ID, the built-in provider it
inherits (``canonical_provider``), the built-in model ID, and the connection.
Every other model field is inherited by OpenCode through ``canonical`` and is
deliberately absent here — a copied field would override the built-in value
and reintroduce drift.

Unknown keys — top-level and per-entry — round-trip untouched.
::

    schema_version = 2
    active_model = "yzr-dashscope/glm-5.3"

    [[models]]
    model_id = "glm-5.3"
    provider = "yzr-dashscope"
    canonical_provider = "alibaba-cn"
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key = "sk-..."
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from model_switch._compat import toml_dumps, toml_loads


SCHEMA_VERSION = 2

_YZR_PROVIDER_RE = re.compile(r"^yzr-[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_PROVIDER_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_MODEL_ID_RE = re.compile(r"^[^\s/#]+$")

# Local model overrides would survive in the registry but never render, which
# would look like configuration while doing nothing. They are rejected instead.
_LOCAL_OVERRIDE_KEYS = (
    "display_name", "modalities", "context_window", "output_limit",
    "variants", "compatibility", "body", "package",
)


class StoreError(Exception):
    """Registry could not be loaded, parsed or validated."""


def _require_str(value: Any, where: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StoreError("{}: {} must be a non-empty string, got {!r}".format(
            where, field, value))
    return value


def validate_registry(data: Any) -> Dict[str, Any]:
    """Validate the registry shape; raise `StoreError` on the first problem."""
    if not isinstance(data, dict):
        raise StoreError("registry root must be a table, got {}".format(
            type(data).__name__))
    if "schema_version" in data and not isinstance(data["schema_version"], int):
        raise StoreError("schema_version must be an integer, got {!r}".format(
            data["schema_version"]))

    models = data.get("models")
    if models is None:
        models = data["models"] = []
    if not isinstance(models, list):
        raise StoreError("'models' must be an array of tables, got {}".format(
            type(models).__name__))

    seen = set()
    groups: Dict[str, Dict[str, Any]] = {}
    for entry in models:
        if not isinstance(entry, dict):
            raise StoreError("models[] entries must be tables, got {}".format(
                type(entry).__name__))
        mid = entry.get("model_id")
        if not isinstance(mid, str) or not _MODEL_ID_RE.match(mid):
            raise StoreError(
                "model_id {!r} is invalid (non-empty, no '/', '#' or "
                "whitespace)".format(mid))
        pid = entry.get("provider")
        if not isinstance(pid, str) or not _YZR_PROVIDER_RE.match(pid):
            raise StoreError(
                "provider {!r} is invalid: use a 'yzr-' prefix followed by "
                "lowercase letters, digits and hyphens".format(pid))
        canonical = entry.get("canonical_provider")
        if (not isinstance(canonical, str)
                or not _PROVIDER_RE.match(canonical)):
            raise StoreError(
                "canonical_provider {!r} is invalid: use a built-in provider "
                "ID of lowercase letters, digits and hyphens".format(canonical))
        where = "{}/{}".format(pid, mid)
        if (pid, mid) in seen:
            raise StoreError("{}: duplicate entry".format(where))
        seen.add((pid, mid))
        _require_str(entry.get("base_url"), where, "base_url")
        _require_str(entry.get("api_key"), where, "api_key")
        for key in _LOCAL_OVERRIDE_KEYS:
            if key in entry:
                raise StoreError(
                    "{}: '{}' is not stored locally; canonical_provider "
                    "inherits it from OpenCode".format(where, key))
        # One provider block carries one canonical/baseURL/apiKey triple, so
        # every entry under a provider ID must agree on all three.
        group = groups.setdefault(pid, {
            "canonical_provider": canonical,
            "base_url": entry["base_url"],
            "api_key": entry["api_key"],
            "from": where,
        })
        if (canonical != group["canonical_provider"]
                or entry["base_url"] != group["base_url"]
                or entry["api_key"] != group["api_key"]):
            raise StoreError(
                "{}: provider {!r} already uses the canonical_provider/"
                "base_url/api_key of {}; all models under one provider share "
                "them".format(where, pid, group["from"]))

    active = data.get("active_model")
    if active is not None:
        if not isinstance(active, str):
            raise StoreError("'active_model' must be 'provider/model_id'")
        try:
            provider, model_id = split_ref(active)
        except StoreError as e:
            raise StoreError("'active_model': {}".format(e))
        if (provider, model_id) not in seen:
            raise StoreError(
                "'active_model' points at {}, which is not in the "
                "registry".format(active))
    return data


def load_models(path: Path) -> Dict[str, Any]:
    """Load the registry; a missing file reads as an empty one.

    A malformed file raises `StoreError` — silently ignoring it would
    invite the next write to replace the user's registry with a
    near-empty one.
    """
    p = Path(path)
    if not p.exists():
        return {"schema_version": SCHEMA_VERSION, "models": []}
    try:
        data = toml_loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise StoreError("cannot read {}: {}".format(p, e))
    return validate_registry(data)


def save_models(path: Path, data: Dict[str, Any]) -> None:
    """Validate and atomically write the registry, mode 0600."""
    validate_registry(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(toml_dumps(data), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def split_ref(ref: str) -> Tuple[str, str]:
    """Split ``provider/model_id`` into its two parts, validating the shape."""
    if not isinstance(ref, str) or "/" not in ref:
        raise StoreError(
            "model reference must be 'provider/model', got {!r}".format(ref))
    provider, model = ref.split("/", 1)
    if not provider or not model:
        raise StoreError(
            "model reference must be 'provider/model', got {!r}".format(ref))
    return provider, model


def iter_refs(data: Dict[str, Any]) -> Iterator[str]:
    """Yield every ``provider/model_id`` reference, deterministically sorted."""
    models = data.get("models") or []
    for entry in sorted(models,
                        key=lambda e: (e.get("provider") or "",
                                       e.get("model_id") or "")):
        yield "{}/{}".format(entry.get("provider"), entry.get("model_id"))


def get_model(data: Dict[str, Any], ref: str) -> Optional[Dict[str, Any]]:
    """The entry for ``provider/model_id``, or None when absent."""
    try:
        provider, model_id = split_ref(ref)
    except StoreError:
        return None
    for entry in data.get("models") or []:
        if (isinstance(entry, dict) and entry.get("provider") == provider
                and entry.get("model_id") == model_id):
            return entry
    return None


def entries_for_provider(data: Dict[str, Any],
                         provider: str) -> List[Dict[str, Any]]:
    """The entries under one provider ID, sorted by model_id."""
    return [e for e in sorted(data.get("models") or [],
                              key=lambda e: e.get("model_id") or "")
            if isinstance(e, dict) and e.get("provider") == provider]


def provider_labels(data: Dict[str, Any]) -> List[str]:
    """Distinct provider IDs in the registry, sorted."""
    return sorted({e.get("provider") for e in data.get("models") or []
                   if isinstance(e, dict) and e.get("provider")})
