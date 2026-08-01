"""Annotations on HTML files: <name>.meta sidecar JSON files.

Per design §7.2:
  - One `<name>.meta` file per `<name>.html` in docroot.
  - Atomic write via .tmp + os.replace (same rule as storage.upload).
  - ULID ids (no external dep — base32 of os.urandom).
  - author = "tk_" + sha256(token)[:8], irreversible, same token → same author.
  - quote normalization for iframe substring matching: collapse whitespace only.
"""
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# 26-char Crockford-base32-ish ULID: 10-char time (48-bit sec → 10 base32-ish
# chars from [0-9A-Z]) + 16-char random. Use uppercase A-Z0-9 minus I/L/O/U
# to keep it URL-safe and OCR-friendly.
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_LEN_TIME = 10
_ULID_LEN_RANDOM = 16

_META_VERSION = 1


def ulid_new() -> str:
    """Return a fresh 26-char ULID-ish id, lexicographically sortable by time."""
    now_ms = int(time.time() * 1000)
    time_part = ""
    for _ in range(_ULID_LEN_TIME):
        time_part = _ULID_ALPHABET[now_ms % 32] + time_part
        now_ms //= 32
    rand_bytes = secrets.token_bytes(16)
    rand_part = "".join(_ULID_ALPHABET[b % 32] for b in rand_bytes)
    return time_part + rand_part


def author_of_token(token: str) -> str:
    """Return a stable, irreversible identifier for this token."""
    h = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
    return "tk_" + h


_WS_RE = re.compile(r"\s+")


def normalize_quote(s: str) -> str:
    """Collapse whitespace runs to single space, strip ends.

    Preserves Chinese/CJK punctuation and word characters; only ASCII
    whitespace runs are folded. This lets iframe text matching tolerate
    HTML re-rendering that may collapse newlines.
    """
    return _WS_RE.sub(" ", s).strip()


def _empty_doc() -> Dict[str, Any]:
    return {"version": _META_VERSION, "annotations": []}


def load(docroot: Path, name: str) -> Dict[str, Any]:
    """Read `<name>.meta` from docroot. Returns empty doc if file missing."""
    p = docroot / (name + ".meta")
    if not p.exists():
        return _empty_doc()
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        # Corrupt meta → treat as empty (do NOT raise; agents may rely on
        # graceful read even after partial writes).
        return _empty_doc()
    if not isinstance(data, dict):
        return _empty_doc()
    if "annotations" not in data or not isinstance(data["annotations"], list):
        data["annotations"] = []
    if "version" not in data:
        data["version"] = _META_VERSION
    return data


def save(docroot: Path, name: str, doc: Dict[str, Any]) -> None:
    """Atomic write of doc to `<name>.meta`."""
    p = docroot / (name + ".meta")
    tmp = p.with_name(p.name + ".tmp")
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
    try:
        with open(tmp, "wb") as f:
            f.write(payload)
        os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    except BaseException:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise