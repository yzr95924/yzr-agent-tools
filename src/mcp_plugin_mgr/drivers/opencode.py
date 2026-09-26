"""OpenCode MCP driver — reads/writes opencode.json `mcp.servers`.

OpenCode V2 nests MCP servers under `mcp.servers` in
$XDG_CONFIG_HOME/opencode/opencode.json (the V1 form put each server
directly under `mcp`). This driver writes only the native V2 shape
(https://opencode.ai/v2/docs/mcp-servers); V1 entries an older version of
this tool wrote are reclaimed the next time an operation touches the same
name (`_migrate_legacy`). The same file holds ``providers`` / ``model``
(owned by model-switch) and ``$schema``; those keys are disjoint from
``mcp``, so we touch only ``mcp`` and preserve the rest.

OpenCode's vocabulary differs from Claude Code's:
  - type tokens are "remote"/"local" (not http/stdio);
  - there is no separate args field — `command` is an ARRAY of [cmd, ...args];
  - env vars live under `environment`, not `env`;
  - servers carry a native "disabled" flag (V1 used the inverse "enabled");
    `opencode mcp` has no enable/disable subcommand, so the flag is flipped
    here (set_enabled), in place, which preserves keys the user added by
    hand (timeout, oauth, ...).

Shapes we write:
  http:  {"type": "remote", "url": <url>, "disabled": false, "headers": {...}}
  stdio: {"type": "local",  "command": [<cmd>, ...args], "disabled": false, "environment": {...}}
"""
from pathlib import Path
from typing import Dict

from mcp_plugin_mgr import paths
from mcp_plugin_mgr.drivers._atomic import atomic_write_json
from mcp_plugin_mgr.drivers.base import BaseMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP


def _v1_to_v2(obj: dict) -> dict:
    """Convert a V1 server object (a dict under `mcp.<name>`) to V2 shape."""
    out = dict(obj)
    # Absence of V1 `enabled` meant connected — the same default V2 gives
    # `disabled`, so only synthesize the flag when it is not explicit.
    enabled = out.pop("enabled", True)
    if "disabled" not in out:
        out["disabled"] = not bool(enabled)
    return out


class OpenCodeMcpDriver(BaseMcpDriver):
    name = "opencode"
    _KEY = "mcp"
    _SUBKEY = "servers"
    native_disable = True

    def __init__(self, config_path: Path = None) -> None:
        if config_path is None:
            config_path = paths.opencode_config_file()
        super().__init__(config_path=config_path)

    def render(self, entry: ServerEntry) -> dict:
        if entry.transport == TRANSPORT_HTTP:
            out = {
                "type": "remote",
                "url": entry.url,
                "disabled": not bool(entry.enabled),
            }
            if entry.headers:
                out["headers"] = dict(entry.headers)
            return out
        # stdio — command is cmd + args combined into one array.
        out = {
            "type": "local",
            "command": [entry.command] + list(entry.args),
            "disabled": not bool(entry.enabled),
        }
        if entry.env:
            out["environment"] = dict(entry.env)
        return out

    def list_servers(self) -> Dict[str, dict]:
        """Native `mcp.servers` map plus any still-live V1 entries.

        V2 keeps reading servers written directly under `mcp`, so reporting
        only the native location would deny a connection the agent really
        has. Same name in both places: V2 lets the native entry win, and so
        do we.
        """
        servers = super().list_servers()
        outer = self._read().get(self._KEY)
        if isinstance(outer, dict):
            for name, obj in outer.items():
                if name != self._SUBKEY and isinstance(obj, dict) and name not in servers:
                    servers[name] = _v1_to_v2(obj)
        return servers

    def _migrate_legacy(self, name: str) -> None:
        """Move this tool's V1 entry for `name` into `mcp.servers`, on disk.

        Runs before every mutation. A native entry of the same name wins —
        the stale V1 copy is just dropped (matching V2's own precedence).
        Names not being operated on — hand-written V1 entries included — are
        never touched.
        """
        if name == self._SUBKEY:
            # Otherwise a server literally named "servers" would be treated
            # as a legacy entry and would delete the native container.
            return
        config = self._read()
        outer = config.get(self._KEY)
        if not isinstance(outer, dict):
            return
        legacy = outer.get(name)
        if not isinstance(legacy, dict):
            return
        servers = self._get_server_map(config)
        if name not in servers:
            servers[name] = _v1_to_v2(legacy)
        del outer[name]
        atomic_write_json(self.config_path, config)

    def add_server(self, name: str, entry: ServerEntry) -> None:
        self._migrate_legacy(name)
        super().add_server(name, entry)

    def remove_server(self, name: str) -> bool:
        self._migrate_legacy(name)
        return super().remove_server(name)

    def set_enabled(self, name: str, entry: ServerEntry, enabled: bool) -> str:
        self._migrate_legacy(name)
        return super().set_enabled(name, entry, enabled)

    def _flag_mutation(self, enabled: bool):
        desired = not enabled

        def mutate(obj):
            changed = obj.get("disabled") is not desired
            obj["disabled"] = desired
            return changed

        return mutate

    def flag_state(self, enabled: bool) -> str:
        return "disabled={}".format("false" if enabled else "true")


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
