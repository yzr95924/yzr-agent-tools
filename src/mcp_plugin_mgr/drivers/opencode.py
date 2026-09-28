"""OpenCode MCP driver — reads/writes opencode.json `mcp.servers`.

OpenCode V2 nests MCP servers under `mcp.servers` in
$XDG_CONFIG_HOME/opencode/opencode.json (https://opencode.ai/v2/docs/mcp-servers).
The same file holds ``providers`` / ``model`` (owned by model-switch) and
``$schema``; those keys are disjoint from ``mcp``, so we touch only ``mcp``
and preserve the rest.

OpenCode's vocabulary differs from Claude Code's:
  - type tokens are "remote"/"local" (not http/stdio);
  - there is no separate args field — `command` is an ARRAY of [cmd, ...args];
  - env vars live under `environment`, not `env`;
  - servers carry a native "disabled" flag; `opencode mcp` has no
    enable/disable subcommand, so the flag is flipped here (set_enabled), in
    place, which preserves keys the user added by hand (timeout, oauth, ...).

Shapes we write:
  http:  {"type": "remote", "url": <url>, "disabled": false, "headers": {...}}
  stdio: {"type": "local",  "command": [<cmd>, ...args], "disabled": false, "environment": {...}}
"""
from pathlib import Path

from mcp_plugin_mgr import paths
from mcp_plugin_mgr.drivers.base import BaseMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP


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
