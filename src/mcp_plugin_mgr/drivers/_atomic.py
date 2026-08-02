"""Shared driver helpers: atomic JSON write.

Copy of model_switch/drivers/_atomic.py — kept per-tool so each tool stays
independent. Atomicity (write to <path>.tmp then os.replace) prevents users
from ever seeing a half-written agent config file, which matters doubly for
~/.claude.json: a truncated file would wedge the running Claude Code session.
"""
import json
import os
from pathlib import Path


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: write to `<path>.tmp`, then `os.replace`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
