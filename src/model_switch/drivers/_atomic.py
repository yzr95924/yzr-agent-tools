"""Shared driver helpers: atomic JSON write."""
import json
import os
from pathlib import Path


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: write to `<path>.tmp`, then `os.replace`.

    Used by every driver for its `apply()`. Atomicity prevents users from
    ever seeing a half-written agent config file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
