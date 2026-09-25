"""XDG-aware path resolution for OpenCode's global plugin locations.

`bundled_plugins_dir()` is package-relative (the tool's own source of truth);
the rest point into OpenCode's global config. All accessors are functions so
tests can monkeypatch `paths.<fn>` on the module (same isolation contract as
model_switch / mcp_plugin_mgr).
"""
import os
from pathlib import Path


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def opencode_config_dir() -> Path:
    return _config_base() / "opencode"


def opencode_config_file() -> Path:
    """OpenCode's global config file (~/.config/opencode/opencode.json)."""
    return opencode_config_dir() / "opencode.json"


def plugins_target_dir() -> Path:
    """Where installed plugins live. `./plugins/<name>` entries in the
    global config resolve here (OpenCode resolves them relative to the
    config file's directory)."""
    return opencode_config_dir() / "plugins"


def bundled_plugins_dir() -> Path:
    """The plugins shipped in this package — the source of truth."""
    return Path(__file__).resolve().parent / "plugins"
