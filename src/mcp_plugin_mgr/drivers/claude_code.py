"""Claude Code MCP driver — reads/writes ~/.claude.json `mcpServers`.

Claude Code stores user-scope MCP servers under the top-level ``mcpServers``
key of ~/.claude.json — NOT ~/.claude/settings.json (that file holds
env/model/theme and is owned by model-switch). ~/.claude.json also holds
onboarding flags, project history, telemetry counters, etc.; we touch only
``mcpServers`` and preserve every other key, so the running session is never
disturbed.

Shapes we write (verified against the real ~/.claude.json on this machine):
  http:  {"type": "http",  "url": <url>, "headers": {...}}            # headers only if non-empty
  stdio: {"type": "stdio", "command": <cmd>, "args": [...], "env": {...}}
"""
from pathlib import Path

from mcp_plugin_mgr import paths
from mcp_plugin_mgr.drivers.base import BaseMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP


class ClaudeCodeMcpDriver(BaseMcpDriver):
    name = "claude-code"
    _KEY = "mcpServers"

    def __init__(self, config_path: Path = None) -> None:
        if config_path is None:
            config_path = paths.claude_json_file()
        super().__init__(config_path=config_path)

    def render(self, entry: ServerEntry) -> dict:
        if entry.transport == TRANSPORT_HTTP:
            out = {"type": "http", "url": entry.url}
            if entry.headers:
                out["headers"] = dict(entry.headers)
            return out
        # stdio — env is always emitted (matches what `claude mcp add` writes).
        return {
            "type": "stdio",
            "command": entry.command,
            "args": list(entry.args),
            "env": dict(entry.env),
        }


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
