"""OpenCode MCP driver — reads/writes opencode.json `mcp`.

OpenCode stores MCP servers under the top-level ``mcp`` key of
$XDG_CONFIG_HOME/opencode/opencode.json. The same file holds ``provider`` /
``model`` (owned by model-switch) and ``$schema``; those keys are disjoint from
``mcp``, so we touch only ``mcp`` and preserve the rest.

OpenCode's vocabulary differs from Claude Code's (per the schema at
https://opencode.ai/config.json):
  - type tokens are "remote"/"local" (not http/stdio);
  - there is no separate args field — `command` is an ARRAY of [cmd, ...args];
  - env vars live under `environment`, not `env`;
  - servers carry an `enabled` flag; we set it true on add.

Shapes we write:
  http:  {"type": "remote", "url": <url>, "enabled": true, "headers": {...}}
  stdio: {"type": "local",  "command": [<cmd>, ...args], "enabled": true, "environment": {...}}
"""
from pathlib import Path

from mcp_plugin_mgr import paths
from mcp_plugin_mgr.drivers.base import BaseMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP


class OpenCodeMcpDriver(BaseMcpDriver):
    name = "opencode"
    _KEY = "mcp"

    def __init__(self, config_path: Path = None) -> None:
        if config_path is None:
            config_path = paths.opencode_config_file()
        super().__init__(config_path=config_path)

    def render(self, entry: ServerEntry) -> dict:
        if entry.transport == TRANSPORT_HTTP:
            out = {"type": "remote", "url": entry.url, "enabled": True}
            if entry.headers:
                out["headers"] = dict(entry.headers)
            return out
        # stdio — command is cmd + args combined into one array.
        out = {
            "type": "local",
            "command": [entry.command] + list(entry.args),
            "enabled": True,
        }
        if entry.env:
            out["environment"] = dict(entry.env)
        return out


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
