"""Shared driver helper: atomic JSON write."""
import json
from pathlib import Path

from model_switch.store import atomic_write_text


def atomic_write_json(path: Path, data: dict) -> None:
    """Serialize `data` and write it via `store.atomic_write_text`."""
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
