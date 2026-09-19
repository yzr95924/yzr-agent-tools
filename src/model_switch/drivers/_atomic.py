"""Shared driver JSON IO: a tolerant read + an atomic write."""
import json
from pathlib import Path

from model_switch.store import atomic_write_text


def read_json(path: Path) -> dict:
    """Read `path` as JSON; ``{}`` when the file is missing or empty."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return {}
    return json.loads(text)


def atomic_write_json(path: Path, data: dict) -> None:
    """Serialize `data` and write it via `store.atomic_write_text`."""
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
