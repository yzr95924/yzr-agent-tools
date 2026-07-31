"""XDG-aware config directory path resolution."""
import os
from pathlib import Path


def config_dir() -> Path:
    """Return the model-switch config directory (does not create it)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "model-switch"


def models_file() -> Path:
    return config_dir() / "models.toml"


def state_file() -> Path:
    return config_dir() / "state.toml"


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def opencode_config_file() -> Path:
    """Return OpenCode's global config file.

    OpenCode reads ``$XDG_CONFIG_HOME/opencode/opencode.json`` (default
    ``~/.config/opencode/opencode.json``) — **not** ``~/.opencode.json``.
    Writing anywhere else means our config is silently never loaded, so
    OpenCode starts on its default model.
    """
    return _config_base() / "opencode" / "opencode.json"