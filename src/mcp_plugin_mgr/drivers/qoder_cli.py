"""Qoder CLI MCP driver — reads/writes ~/.qoder/settings.json `mcpServers`.

Qoder CLI stores user-scope MCP servers under the top-level ``mcpServers`` key
of ~/.qoder/settings.json — the SAME key name Claude Code uses, but in a
different file. That file also holds ``model``/``ui``/``permissions``/``git``/
``security`` (qodercli's own settings); we touch only ``mcpServers`` and
preserve every other key.

Qoder CLI's MCP vocabulary is nearly identical to Claude Code's (it ships a
``qodercli mcp add/remove/list`` CLI modeled on ``claude mcp``), with one
difference verified against qodercli 1.0.43 by adding servers via
``qodercli --config-dir <tmp> mcp add ... --scope user`` and inspecting the
resulting settings.json:

  - **stdio carries NO ``type`` field** (``qodercli mcp add`` omits it), and
    ``env`` is omitted entirely when empty — whereas Claude Code always emits
    ``"type": "stdio"`` and an ``env`` object. We mirror qodercli's own output
    so our writes are indistinguishable from its CLI.
  - http/sse DO carry ``type``.

Shapes we write (match ``qodercli mcp add`` exactly):
  stdio: {"command": <cmd>, "args": [...], "env": {...}}   # env only if non-empty; NO type
  http:  {"url": <url>, "type": "http", "headers": {...}}   # headers only if non-empty

Enable/disable mirrors ``qodercli mcp disable/enable`` (verified against
qodercli 1.1.21 with a temp --config-dir): disable adds ``"disabled": true``
to the server object in place, enable removes that key again. Both preserve
every other key, so foreign fields survive flag flips.

Note: qodercli also supports ``sse``/``ws`` transports and OAuth fields, but
mcp-plugin-mgr's canonical ServerEntry only models http/stdio, so we render
those two.
"""
from pathlib import Path

from mcp_plugin_mgr import paths
from mcp_plugin_mgr.drivers.base import BaseMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP


class QoderCliMcpDriver(BaseMcpDriver):
    name = "qodercli"
    _KEY = "mcpServers"
    native_disable = True

    def __init__(self, config_path: Path = None) -> None:
        if config_path is None:
            config_path = paths.qoder_settings_file()
        super().__init__(config_path=config_path)

    def render(self, entry: ServerEntry) -> dict:
        if entry.transport == TRANSPORT_HTTP:
            out = {"url": entry.url, "type": "http"}
            if entry.headers:
                out["headers"] = dict(entry.headers)
            return out
        # stdio — NO type field and NO env key when empty, matching
        # `qodercli mcp add` output (differs from Claude Code on both points).
        out = {"command": entry.command, "args": list(entry.args)}
        if entry.env:
            out["env"] = dict(entry.env)
        return out

    def _flag_mutation(self, enabled: bool):
        def mutate(obj):
            if enabled:
                changed = "disabled" in obj
                obj.pop("disabled", None)
                return changed
            changed = obj.get("disabled") is not True
            obj["disabled"] = True
            return changed

        return mutate

    def flag_state(self, enabled: bool) -> str:
        return "disabled={}".format("false" if enabled else "true")


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
