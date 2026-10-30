"""Resolve canonical model sources from OpenCode's catalog cache.

The catalog snapshot (kv key ``models-dev:v2:catalog``, OpenCode 2.2+) gives
every model its own ordered ``api`` routes. OpenCode runs a chat model through
the first route that carries an SDK, so that route is the one an alias
inherits. model-switch only accepts sources whose default route is
``chat-completions`` with a base URL: aliasing any other default would change
the protocol, not just the provider name.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from model_switch import paths


_CATALOG_KV_KEY = "models-dev:v2:catalog"


@dataclass
class Candidate:
    """One catalog provider whose default route can back an alias."""

    provider: str
    base_url: str


@dataclass
class Pick:
    """The outcome of narrowing candidates to one provider."""

    candidate: Optional[Candidate]
    reason: str
    alternatives: List[Candidate] = field(default_factory=list)


def default_route(entry: Dict[str, Any]) -> Tuple[str, str]:
    """The entry's first SDK-carrying route as ``(route, base_url)``."""
    routes = entry.get("api")
    if not isinstance(routes, dict):
        return "", ""
    for name, route in routes.items():
        if not isinstance(route, dict):
            continue
        sdk = route.get("sdk")
        if not isinstance(sdk, dict):
            continue
        package = sdk.get("opencodeai") or sdk.get("aisdk")
        base_url = route.get("base_url")
        if (isinstance(package, str) and package
                and isinstance(base_url, str) and base_url):
            return name, base_url
    return "", ""


def _candidate(provider: str, entry: Dict[str, Any]) -> Optional[Candidate]:
    route, base_url = default_route(entry)
    if route != "chat-completions":
        return None
    return Candidate(provider=provider, base_url=base_url)


def _is_chat(entry: Dict[str, Any]) -> bool:
    return str(entry.get("type") or "chat") == "chat"


def model_candidates(data: Dict[str, Any],
                     model_id: str) -> List[Candidate]:
    """Every catalog provider serving ``model_id`` over Chat Completions."""
    out: List[Candidate] = []
    for provider in sorted(data):
        entry_map = data.get(provider) or {}
        models = entry_map.get("models") or {}
        entry = models.get(model_id)
        if not isinstance(entry, dict) or not _is_chat(entry):
            continue
        candidate = _candidate(provider, entry)
        if candidate is not None:
            out.append(candidate)
    return out


def lookup(data: Dict[str, Any], provider: str,
           model_id: str) -> Optional[Candidate]:
    """The Chat Completions candidate under one exact canonical provider."""
    entry_map = data.get(provider) or {}
    models = entry_map.get("models") or {}
    entry = models.get(model_id)
    if not isinstance(entry, dict) or not _is_chat(entry):
        return None
    return _candidate(provider, entry)


def pick(cands: List[Candidate], pin: Optional[str] = None) -> Pick:
    """Narrow candidates to one provider, or refuse with a reason.

    ``pin`` always wins and must exist. More than one candidate is always
    ambiguous: two built-in providers can serve the same model over the same
    endpoint while using different runtime packages.
    """
    if pin is not None:
        for c in cands:
            if c.provider == pin:
                return Pick(c, "pinned provider {!r}".format(pin))
        return Pick(None, "provider {!r} has no matching model".format(pin),
                    list(cands))
    if not cands:
        return Pick(None, "no catalog model with a chat-completions default "
                          "route")
    if len(cands) > 1:
        return Pick(None, "ambiguous catalog providers", list(cands))
    return Pick(cands[0], "single catalog provider")


def load_cache(path: Optional[Path] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """Read the catalog cache: ``(data-or-None, human description)``.

    Never raises and never touches the network — every failure mode is local
    and reported in the description. The database is opened read-only.
    """
    p = Path(path) if path is not None else paths.catalog_db_file()
    if not p.exists():
        return None, "no catalog cache at {} (OpenCode builds it on first run)".format(p)
    try:
        con = sqlite3.connect(p.absolute().as_uri() + "?mode=ro", uri=True)
    except (OSError, ValueError, sqlite3.Error):
        return None, "unreadable catalog cache at {}".format(p)
    try:
        try:
            row = con.execute("SELECT value FROM kv WHERE key = ?",
                              (_CATALOG_KV_KEY,)).fetchone()
        except sqlite3.Error:
            return None, "unreadable catalog cache at {}".format(p)
    finally:
        con.close()
    if row is None:
        return None, "no catalog cache at {} (OpenCode builds it on first run)".format(p)
    try:
        envelope = json.loads(row[0])
        data = json.loads(envelope["body"])
    except (ValueError, TypeError, KeyError):
        return None, "unreadable catalog cache at {}".format(p)
    if not isinstance(data, dict):
        return None, "unexpected catalog cache shape at {}".format(p)
    updated = envelope.get("updatedAt")
    ts = (updated / 1000.0
          if isinstance(updated, (int, float)) and updated > 0
          else p.stat().st_mtime)
    stamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    return data, "{} (updated {})".format(p, stamp)
