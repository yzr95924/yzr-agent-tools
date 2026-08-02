"""Manage Claude Code ``permissions.allow`` for the ``--auto-allow`` flag.

When an MCP server (outline especially) is wired up, Claude Code's auto-mode
classifier can false-positive BLOCK large writes (≥3000 chars) to its tools.
Pre-approving the tool names in ``permissions.allow`` makes the classifier skip
that second guess. This module writes ONLY the ``permissions.allow`` list in
Claude Code's settings file, preserving every other key (``env``/``model`` are
owned by model-switch) — the same read-all / modify-one-key / atomic-write +
preserve-unknown discipline the MCP drivers and model-switch's driver use, and
the same key-ownership-sharing pattern both tools already use on opencode.json.
"""
import json
from pathlib import Path
from typing import Iterable, List, Optional

from mcp_plugin_mgr.drivers._atomic import atomic_write_json


def allow_entries_for(name, preset=None):
    # type: (str, Optional[object]) -> List[str]
    """Permission rules to pre-approve for a server.

    Uses the preset's explicit ``allow_tools`` when it has them (outline's
    verified 15); otherwise the server-level wildcard ``mcp__<name>``.
    """
    if preset is not None and getattr(preset, "allow_tools", None):
        return list(preset.allow_tools)
    return ["mcp__{}".format(name)]


def _read(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text)


def add_allowed_tools(path, entries):
    # type: (Path, Iterable[str]) -> List[str]
    """Merge `entries` into permissions.allow (dedup, preserve other keys).

    Returns the entries that were newly added (empty if all already present).
    """
    entries = list(entries)
    if not entries:
        return []
    config = _read(path)
    perms = config.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
    allow = perms.get("allow")
    if not isinstance(allow, list):
        allow = []
    existing = set(allow)
    added = [e for e in entries if e not in existing]
    if not added:
        return []
    perms["allow"] = allow + added
    config["permissions"] = perms
    atomic_write_json(path, config)
    return added


def remove_allowed_tools(path, entries):
    # type: (Path, Iterable[str]) -> List[str]
    """Remove `entries` from permissions.allow (preserve other keys).

    Returns the entries that were actually present and removed.
    """
    entries = list(entries)
    if not entries:
        return []
    config = _read(path)
    perms = config.get("permissions")
    if not isinstance(perms, dict):
        return []
    allow = perms.get("allow")
    if not isinstance(allow, list):
        return []
    to_remove = set(entries)
    new_allow = [e for e in allow if e not in to_remove]
    if len(new_allow) == len(allow):
        return []
    perms["allow"] = new_allow
    config["permissions"] = perms
    atomic_write_json(path, config)
    return [e for e in allow if e in to_remove]
