"""TOML-backed registry of MCP servers (~/.config/mcp-plugin-mgr/servers.toml).

Each ``[servers.<name>]`` table is one MCP server in a *canonical*,
transport-neutral form. The per-agent drivers translate an entry into Claude
Code / OpenCode's own vocabulary when applying. Unknown top-level keys and
unknown per-server keys round-trip untouched (same passthrough discipline as
model_switch/store.py).

Round-trip invariant: ``save_servers(load_servers(p), p) == load_servers(p)``
modulo field presence, AND unknown top-level + per-server keys survive a
load/save cycle.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp_plugin_mgr._compat import toml_dump, toml_loads


# Canonical transports. "http" covers Streamable HTTP / SSE remotes; "stdio"
# covers local subprocess servers. Each agent driver maps these to its own
# type tokens (Claude Code: http/stdio; OpenCode: remote/local).
TRANSPORT_HTTP = "http"
TRANSPORT_STDIO = "stdio"
_VALID_TRANSPORTS = (TRANSPORT_HTTP, TRANSPORT_STDIO)


class StoreError(Exception):
    """Base for store-level errors."""


class MissingRequiredField(StoreError):
    """A required field is missing from a [servers.<name>] entry."""


class InvalidTransport(StoreError):
    """transport was missing or not one of the allowed values."""


# Fields mcp-plugin-mgr understands on a [servers.<name>] entry. Anything else
# on an entry is preserved in `ServerEntry.extra` and round-tripped verbatim.
_SERVER_FIELDS = (
    "transport",
    "url",
    "headers",
    "command",
    "args",
    "env",
    "description",
)


@dataclass
class ServerEntry:
    """One MCP server in canonical form, plus any fields we don't own."""
    name: str
    transport: str
    # http
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    # stdio
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    # both
    description: Optional[str] = None
    # Keys not in _SERVER_FIELDS are stored here and round-tripped.
    extra: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.transport not in _VALID_TRANSPORTS:
            raise InvalidTransport(
                "server {!r}: transport must be one of {}, got {!r}".format(
                    self.name, list(_VALID_TRANSPORTS), self.transport
                )
            )
        if self.transport == TRANSPORT_HTTP:
            if not self.url:
                raise MissingRequiredField(
                    "http server {!r} requires 'url'".format(self.name)
                )
        else:  # stdio
            if not self.command:
                raise MissingRequiredField(
                    "stdio server {!r} requires 'command'".format(self.name)
                )

    def to_toml_dict(self) -> Dict[str, Any]:
        """Serialize as a dict, with extras first then known fields."""
        out: Dict[str, Any] = dict(self.extra)
        out["transport"] = self.transport
        if self.transport == TRANSPORT_HTTP:
            out["url"] = self.url
            if self.headers:
                out["headers"] = dict(self.headers)
        else:  # stdio
            out["command"] = self.command
            if self.args:
                out["args"] = list(self.args)
            if self.env:
                out["env"] = dict(self.env)
        if self.description:
            out["description"] = self.description
        return out

    def detail(self) -> str:
        """One-line human summary of where this server points."""
        if self.transport == TRANSPORT_HTTP:
            return self.url or "(no url)"
        return "{} {}".format(self.command or "?", " ".join(self.args)).strip()


@dataclass
class ServerRegistry:
    """Top-level servers.toml content.

    `servers` maps name -> ServerEntry. `extra_top` holds keys at the top
    level we don't manage.
    """
    servers: Dict[str, ServerEntry] = field(default_factory=dict)
    extra_top: Dict[str, Any] = field(default_factory=dict)

    def to_toml_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = dict(self.extra_top)
        out["servers"] = {n: s.to_toml_dict() for n, s in self.servers.items()}
        return out


# ---- servers.toml ------------------------------------------------------------

def load_servers(path: Path) -> ServerRegistry:
    """Load servers.toml. Missing file -> empty ServerRegistry.

    Unknown top-level keys are preserved in `ServerRegistry.extra_top`; unknown
    per-server keys are preserved in `ServerEntry.extra`.
    """
    if not path.exists():
        return ServerRegistry()
    raw = toml_loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StoreError(
            "servers.toml root must be a table, got: {!r}".format(type(raw))
        )

    reg = ServerRegistry()
    for k, v in raw.items():
        if k == "servers":
            continue
        reg.extra_top[k] = v

    for name, entry in (raw.get("servers") or {}).items():
        if not isinstance(entry, dict):
            raise StoreError(
                "servers.toml: [servers.{}] must be a table, got: {!r}".format(
                    name, type(entry)
                )
            )

        transport = str(entry.get("transport", ""))
        e = ServerEntry(name=str(name), transport=transport)

        e.url = str(entry["url"]) if entry.get("url") else None
        if isinstance(entry.get("headers"), dict):
            e.headers = {str(k): str(v) for k, v in entry["headers"].items()}
        e.command = str(entry["command"]) if entry.get("command") else None
        if isinstance(entry.get("args"), list):
            e.args = [str(x) for x in entry["args"]]
        if isinstance(entry.get("env"), dict):
            e.env = {str(k): str(v) for k, v in entry["env"].items()}
        e.description = (
            str(entry["description"]) if entry.get("description") else None
        )

        # Anything else goes into extra (round-tripped verbatim).
        e.extra = {k: v for k, v in entry.items() if k not in _SERVER_FIELDS}

        e.validate()
        reg.servers[str(name)] = e
    return reg


def save_servers(path: Path, reg: ServerRegistry) -> None:
    """Atomic write of servers.toml. Preserves unknown top-level + per-server keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = reg.to_toml_dict()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        toml_dump(raw, f)
    os.replace(tmp, path)
