"""XDG-aware path resolution for model-switch."""
import os
from pathlib import Path


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def _data_base() -> Path:
    """The XDG data root: $XDG_DATA_HOME, else ~/.local/share."""
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else Path.home() / ".local" / "share"


def config_dir() -> Path:
    """Return the model-switch config directory (does not create it)."""
    return _config_base() / "model-switch"


def models_file() -> Path:
    """The TOML registry model-switch owns."""
    return config_dir() / "models.toml"


def opencode_config_file() -> Path:
    """OpenCode's global config file.

    OpenCode reads ``$XDG_CONFIG_HOME/opencode/opencode.json`` (default
    ``~/.config/opencode/opencode.json``) — **not** ``~/.opencode.json``.
    """
    return _config_base() / "opencode" / "opencode.json"


def catalog_db_file() -> Path:
    """OpenCode's local models.dev snapshot, maintained by OpenCode itself.

    OpenCode >= 2.0 stores the fetched catalog in its SQLite database
    ``$XDG_DATA_HOME/opencode/opencode.db``, table ``kv``, key
    ``models-dev:v2:catalog``. Read-only for model-switch.
    """
    return _data_base() / "opencode" / "opencode.db"
