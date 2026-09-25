"""XDG-aware config directory path resolution."""
import os
from pathlib import Path


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def config_dir() -> Path:
    """Return the model-switch config directory (does not create it)."""
    return _config_base() / "model-switch"


def models_file() -> Path:
    return config_dir() / "models.toml"


def state_file() -> Path:
    return config_dir() / "state.toml"


def opencode_config_file() -> Path:
    """Return OpenCode's global config file.

    OpenCode reads ``$XDG_CONFIG_HOME/opencode/opencode.json`` (default
    ``~/.config/opencode/opencode.json``) — **not** ``~/.opencode.json``.
    Writing anywhere else means our config is silently never loaded, so
    OpenCode starts on its default model.
    """
    return _config_base() / "opencode" / "opencode.json"


def catalog_db_file() -> Path:
    """OpenCode's local models.dev snapshot, maintained by OpenCode itself.

    OpenCode >= 2.0 stores the fetched catalog in its SQLite database
    ``$XDG_DATA_HOME/opencode/opencode.db`` (default
    ``~/.local/share/opencode/opencode.db``), table ``kv``, key
    ``models-dev:catalog``; the value is a JSON envelope whose ``body`` is
    the provider map as a JSON string.

    Read-only for model-switch: we derive catalog-aligned fields from it but
    never write it and never fetch the catalog over the network.
    """
    data_base = os.environ.get("XDG_DATA_HOME")
    base = Path(data_base) if data_base else Path.home() / ".local" / "share"
    return base / "opencode" / "opencode.db"
