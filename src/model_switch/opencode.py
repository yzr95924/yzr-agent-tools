"""Render canonical aliases into OpenCode's global config (opencode.json).

model-switch owns the ``yzr-*`` provider namespace. Each rendered provider is
an alias of a built-in one: ``canonical`` names the source, ``settings`` only
carries the connection, and every model entry is empty so OpenCode inherits
the built-in model definition — including its runtime package. Anything
outside the ``yzr-*`` namespace is preserved untouched.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from model_switch import paths, store

PROVIDER_PREFIX = "yzr-"


def render_providers(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The full ``yzr-*`` provider map for a validated registry."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for entry in data.get("models") or []:
        groups.setdefault(entry["provider"], []).append(entry)
    rendered: Dict[str, Dict[str, Any]] = {}
    for pid in sorted(groups):
        entries = sorted(groups[pid], key=lambda e: e["model_id"])
        first = entries[0]
        rendered[pid] = {
            "canonical": first["canonical_provider"],
            "name": pid,
            "settings": {
                "baseURL": first["base_url"],
                "apiKey": first["api_key"],
            },
            "models": {e["model_id"]: {} for e in entries},
        }
    return rendered


def _is_owned(provider_id: str) -> bool:
    return provider_id.startswith(PROVIDER_PREFIX)


def _without_owned(block: Any) -> Dict[str, Any]:
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if not _is_owned(k)}


def _read_config(path: Path) -> Dict[str, Any]:
    """Read a JSON object tolerantly: missing/empty/invalid → {}."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON via ``<path>.tmp`` + ``os.replace``, mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _resolve_default(current: Optional[str],
                     data: Dict[str, Any]) -> Optional[str]:
    """Pick the config's ``model`` pointer from the registry.

    The registry stores the final ``yzr-*`` reference, so the pointer is the
    active model verbatim. Without one, a foreign pointer is left alone and a
    stale owned pointer is removed.
    """
    active = data.get("active_model")
    if active:
        return active
    if current and _is_owned(current.split("/", 1)[0]):
        return None
    return current


def sync(data: Dict[str, Any], create: bool = False) -> None:
    """Mirror the registry into ``opencode.json``.

    ``create=False`` (the remove/align path) leaves a missing config file
    alone — no file is conjured out of thin air.
    """
    path = paths.opencode_config_file()
    if not create and not path.exists():
        return

    store.validate_registry(data)
    config = _read_config(path)
    providers = _without_owned(config.get("providers"))
    providers.update(render_providers(data))
    if providers:
        config["providers"] = providers
    else:
        config.pop("providers", None)

    default = _resolve_default(config.get("model"), data)
    if default is None:
        config.pop("model", None)
    else:
        config["model"] = default

    _atomic_write_json(path, config)
