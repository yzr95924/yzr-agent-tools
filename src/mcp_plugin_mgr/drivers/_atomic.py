"""Shared driver helpers: atomic JSON write.

The atomicity rule lives in `mcp_plugin_mgr.store.atomic_write_text` (a
per-tool copy, so the tools stay independent). A half-written config matters
doubly for ~/.claude.json: a truncated file would wedge the running Claude
Code session.
"""
import json
from pathlib import Path

from mcp_plugin_mgr.store import atomic_write_text


def atomic_write_json(path: Path, data: dict) -> None:
    """Serialize `data` and write it via `store.atomic_write_text`."""
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
