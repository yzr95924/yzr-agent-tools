"""Base Protocol + shared implementation + Registry for MCP-target drivers.

A driver encapsulates two things about one agent:
  1. WHERE its MCP-server map lives (Claude Code: ~/.claude.json `mcpServers`;
     OpenCode: opencode.json `mcp`).
  2. the VOCABULARY it uses (Claude Code: type http/stdio, separate
     command+args+env; OpenCode: type remote/local, combined command array,
     `environment` instead of `env`).

`BaseMcpDriver` implements the generic read/list/has/add/remove over a JSON
file that keeps its server map under one top-level key (`_KEY`); it touches
only that key and preserves every other key in the file. Subclasses set
`name`, `_KEY`, a default `config_path`, and implement `render(entry)` to map
a canonical ServerEntry into the agent's shape.
"""
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from mcp_plugin_mgr.store import ServerEntry


class McpDriver(Protocol):
    """Structural type every concrete driver satisfies."""
    name: str
    config_path: Path

    def list_servers(self) -> Dict[str, dict]: ...

    def has_server(self, name: str) -> bool: ...

    def add_server(self, name: str, entry: ServerEntry) -> None: ...

    def remove_server(self, name: str) -> bool: ...

    def render(self, entry: ServerEntry) -> dict: ...


class BaseMcpDriver:
    """Generic JSON-file driver keyed on one top-level server map.

    Subclasses must set `name`, `_KEY`, and implement `render`.
    """
    name: str = ""
    _KEY: str = ""
    config_path: Optional[Path] = None

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

    def list_servers(self) -> Dict[str, dict]:
        return dict(self._read().get(self._KEY, {}))

    def has_server(self, name: str) -> bool:
        return name in self.list_servers()

    def add_server(self, name: str, entry: ServerEntry) -> None:
        from mcp_plugin_mgr.drivers._atomic import atomic_write_json

        config = self._read()
        servers = config.get(self._KEY, {})
        if not isinstance(servers, dict):
            servers = {}
        servers[name] = self.render(entry)
        config[self._KEY] = servers
        atomic_write_json(self.config_path, config)  # type: ignore[arg-type]

    def remove_server(self, name: str) -> bool:
        from mcp_plugin_mgr.drivers._atomic import atomic_write_json

        config = self._read()
        servers = config.get(self._KEY, {})
        if not isinstance(servers, dict) or name not in servers:
            return False
        del servers[name]
        config[self._KEY] = servers
        atomic_write_json(self.config_path, config)  # type: ignore[arg-type]
        return True

    def render(self, entry: ServerEntry) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError


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
        """Return the default driver (currently: claude-code)."""
        if "claude-code" in self._drivers:
            return self._drivers["claude-code"]
        if not self._drivers:
            return None
        return self._drivers[sorted(self._drivers.keys())[0]]


# Singleton registry; built-in drivers are registered lazily by
# cli._ensure_default_registered() on first use (never at import time).
registry = DriverRegistry()
