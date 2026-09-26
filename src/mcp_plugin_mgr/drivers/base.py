"""Base Protocol + shared implementation + Registry for MCP-target drivers.

A driver encapsulates two things about one agent:
  1. WHERE its MCP-server map lives (Claude Code: ~/.claude.json `mcpServers`;
     OpenCode: opencode.json `mcp.servers`).
  2. the VOCABULARY it uses (Claude Code: type http/stdio, separate
     command+args+env; OpenCode: type remote/local, combined command array,
     `environment` instead of `env`).

`BaseMcpDriver` implements the generic read/list/has/add/remove over a JSON
file that keeps its server map under one top-level key (`_KEY`), optionally
nested one level deeper (`_SUBKEY`); it touches only that key and preserves
every other key in the file. Subclasses set `name`, `_KEY` (and `_SUBKEY`),
a default `config_path`, and implement `render(entry)` to map a canonical
ServerEntry into the agent's shape.
"""
from pathlib import Path
from typing import Dict, List, Optional

# typing.Protocol is Python 3.8+ (PEP 544); fall back to a plain stand-in on
# 3.7. Used here only as a structural type hint (no isinstance / nothing
# subclasses it), so a plain class is behaviorally equivalent on 3.7. Mirrors
# _compat.py's tomllib/tomli fallback.
try:
    from typing import Protocol
except ImportError:  # Python <3.8
    class Protocol:  # type: ignore[no-redef]
        pass

from mcp_plugin_mgr.drivers._atomic import atomic_write_json
from mcp_plugin_mgr.store import ServerEntry


class McpDriver(Protocol):
    """Structural type every concrete driver satisfies."""
    name: str
    config_path: Path
    native_disable: bool

    def list_servers(self) -> Dict[str, dict]: ...

    def has_server(self, name: str) -> bool: ...

    def add_server(self, name: str, entry: ServerEntry) -> None: ...

    def remove_server(self, name: str) -> bool: ...

    def set_enabled(self, name: str, entry: ServerEntry, enabled: bool) -> str: ...

    def render(self, entry: ServerEntry) -> dict: ...


class BaseMcpDriver:
    """Generic JSON-file driver keyed on one top-level server map.

    Subclasses must set `name`, `_KEY`, and implement `render`.
    """
    name: str = ""
    _KEY: str = ""
    # Optional nesting level below _KEY holding the server map itself
    # (OpenCode: `mcp.servers`).
    _SUBKEY: Optional[str] = None
    config_path: Optional[Path] = None
    # True when the agent has a native disable flag (OpenCode / Qoder CLI:
    # `disabled`) that can be flipped in place; False when the only way to
    # switch a server off is to remove it from the map.
    native_disable: bool = False

    def __init__(self, config_path: Optional[Path] = None) -> None:
        if config_path is not None:
            self.config_path = config_path

    def _read(self) -> dict:
        """Read the agent's config file as a dict; {} if missing/empty."""
        assert self.config_path is not None
        if not self.config_path.exists():
            return {}
        with open(self.config_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return {}
        return _json_loads(text)

    def _read_server_map(self, config: dict) -> Dict[str, dict]:
        """The server map inside a parsed config; {} when absent or malformed.

        Read-only counterpart of `_get_server_map`: never creates containers,
        so lookups on junk values (a non-dict `_KEY`) simply miss.
        """
        outer = config.get(self._KEY)
        if not isinstance(outer, dict):
            return {}
        if self._SUBKEY is None:
            return outer
        servers = outer.get(self._SUBKEY)
        return servers if isinstance(servers, dict) else {}

    def _get_server_map(self, config: dict) -> dict:
        """The server map inside `config` for mutation, creating containers."""
        outer = config.get(self._KEY)
        if not isinstance(outer, dict):
            outer = {}
            config[self._KEY] = outer
        if self._SUBKEY is None:
            return outer
        servers = outer.get(self._SUBKEY)
        if not isinstance(servers, dict):
            servers = {}
            outer[self._SUBKEY] = servers
        return servers

    def list_servers(self) -> Dict[str, dict]:
        return dict(self._read_server_map(self._read()))

    def has_server(self, name: str) -> bool:
        return name in self.list_servers()

    def add_server(self, name: str, entry: ServerEntry) -> None:

        config = self._read()
        servers = self._get_server_map(config)
        servers[name] = self.render(entry)
        atomic_write_json(self.config_path, config)  # type: ignore[arg-type]

    def remove_server(self, name: str) -> bool:

        config = self._read()
        servers = self._read_server_map(config)
        if name not in servers:
            return False
        del servers[name]
        atomic_write_json(self.config_path, config)  # type: ignore[arg-type]
        return True

    def set_enabled(self, name: str, entry: ServerEntry, enabled: bool) -> str:
        """Turn a server on/off for this agent; returns the action taken.

        Drivers without a native flag fall back to presence/absence: enable
        re-renders the registry entry, disable removes it. The registry keeps
        the full entry (url, token, ...), so `enable` needs no re-configuration.
        Drivers with one only supply the vocabulary (`_flag_mutation`); the
        control flow here flips the flag in place, preserving every other key.

        Returns one of: "written" (entry rendered), "flagged" (native flag
        flipped), "removed" (entry deleted), "absent" (already off / not there).
        """
        if not self.native_disable:
            if enabled:
                self.add_server(name, entry)
                return "written"
            return "removed" if self.remove_server(name) else "absent"
        # Native flag: patched in place (file rewritten only on a real change).
        if self._update_server(name, self._flag_mutation(enabled)) != "missing":
            return "flagged"
        if not enabled:
            return "absent"
        self.add_server(name, entry)
        return "written"

    def _flag_mutation(self, enabled: bool):
        """`mutate(obj) -> changed` for the agent's native disable flag.

        Only drivers with `native_disable = True` implement this; it is where
        each agent's vocabulary lives (OpenCode / Qoder CLI: `disabled`,
        OpenCode V1 used the inverse `enabled`).
        """
        raise NotImplementedError

    def _update_server(self, name: str, mutate) -> str:
        """Patch one stored server object in place.

        `mutate(obj)` returns True when it changed the object. Returns
        "changed" (file rewritten), "unchanged" (no write) or "missing"
        (this agent has no such server).
        """

        config = self._read()
        obj = self._read_server_map(config).get(name)
        if not isinstance(obj, dict):
            return "missing"
        if not mutate(obj):
            return "unchanged"
        atomic_write_json(self.config_path, config)  # type: ignore[arg-type]
        return "changed"

    def render(self, entry: ServerEntry) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def flag_state(self, enabled: bool) -> str:
        """Native disable flag as the agent spells it, for CLI messages.

        Empty for drivers without one. Overridden by flag-flipping drivers
        (OpenCode / Qoder CLI: disabled=false/true).
        """
        return ""


def _json_loads(text: str) -> dict:
    import json

    return json.loads(text)


class DriverRegistry:
    """In-process registry of installed MCP drivers.

    claude-code and opencode are registered lazily by
    `cli._ensure_default_registered` on first use. Tests populate the registry
    manually with tmp-path drivers BEFORE the first CLI invocation, so the lazy
    default never creates a driver pointed at the real ~/.claude.json.
    """
    def __init__(self) -> None:
        self._drivers: Dict[str, McpDriver] = {}

    def register(self, driver: McpDriver) -> None:
        self._drivers[driver.name] = driver

    def get(self, name: str) -> McpDriver:
        if name not in self._drivers:
            raise KeyError(
                "Unknown agent driver {!r}. Available: {}".format(
                    name, sorted(self._drivers.keys())
                )
            )
        return self._drivers[name]

    def list(self) -> List[str]:
        return sorted(self._drivers.keys())

    def default(self) -> Optional[McpDriver]:
        """Return the default driver (currently: claude-code).

        `_ensure_default_registered` always registers claude-code, so this is
        a plain lookup; None means the caller ran before any registration.
        """
        return self._drivers.get("claude-code")


# Singleton registry; built-in drivers are registered lazily by
# cli._ensure_default_registered() on first use (never at import time).
registry = DriverRegistry()
