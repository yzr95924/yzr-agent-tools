"""Tolerant JSON read + atomic write (self-contained per-tool copy).

A half-written opencode.json would wedge every OpenCode session, so writes
always go through `.tmp` + `os.replace`. Unknown keys round-trip untouched:
callers read the whole document, mutate only `plugins`, and write it back.

A config that fails to parse MUST raise (never degrade to ``{}``): the caller
would then write back a plugins-only document and destroy every other key the
user had. Same for an unreadable/unwritable file.
"""
import json
import os
from pathlib import Path


class JsonError(Exception):
    """User-facing config IO/parse failure (bad JSON, unwritable file)."""


def read_json(path: Path) -> dict:
    """Read `path` as JSON; ``{}`` only when the file is missing or empty.

    Raises JsonError when the content is not plain JSON (OpenCode also accepts
    JSONC with comments — this tool manages plain `opencode.json` only) or the
    file cannot be read.
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return {}
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise JsonError(
            "{0} is not plain JSON (JSONC comments?): {1}".format(path, e)
        )
    except OSError as e:
        raise JsonError("cannot read {0}: {1}".format(path, e))


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        raise JsonError("cannot write {0}: {1}".format(path, e))


def atomic_write_json(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")
