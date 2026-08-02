"""XDG-aware path resolution for mcp-plugin-mgr."""
import os
from pathlib import Path


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def config_dir() -> Path:
    """Return the mcp-plugin-mgr config directory (does not create it)."""
    return _config_base() / "mcp-plugin-mgr"


def servers_file() -> Path:
    """Local registry of MCP servers the user has added.

    ~/.config/mcp-plugin-mgr/servers.toml — the canonical, transport-neutral
    source of truth. Each agent driver translates entries from here into its
    own vocabulary when applying.
    """
    return config_dir() / "servers.toml"


def claude_json_file() -> Path:
    """Claude Code's user-scope config file (~/.claude.json).

    Claude Code reads MCP servers from the top-level ``mcpServers`` key here —
    NOT from ~/.claude/settings.json (that file holds env/model/theme and is
    owned by model-switch). Getting this wrong means our writes are silently
    ignored and the server never loads.
    """
    return Path.home() / ".claude.json"


def claude_settings_file() -> Path:
    """Claude Code's user settings file (~/.claude/settings.json).

    Holds ``env``/``model``/``theme`` (owned by model-switch) AND
    ``permissions.allow`` (which we own, for ``--auto-allow``). Same
    key-ownership-sharing pattern as opencode.json: each tool touches only its
    own keys and preserves the rest via atomic read-modify-write.
    """
    return Path.home() / ".claude" / "settings.json"


def opencode_config_file() -> Path:
    """OpenCode's global config ($XDG_CONFIG_HOME/opencode/opencode.json).

    OpenCode reads MCP servers from the top-level ``mcp`` key here. The same
    file also holds ``provider``/``model`` (owned by model-switch) and
    ``$schema`` — those keys are disjoint from ``mcp``, so the two tools
    coexist without conflict as long as each preserves unknown keys.
    """
    return _config_base() / "opencode" / "opencode.json"
