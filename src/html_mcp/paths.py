"""XDG-aware config directory path resolution for html-mcp."""
import os
from pathlib import Path


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def config_dir() -> Path:
    """Return the html-mcp config directory (does not create it).

    Resolves to ``$XDG_CONFIG_HOME/html-mcp`` (default
    ``~/.config/html-mcp``).
    """
    return _config_base() / "html-mcp"


def config_file() -> Path:
    """Return the html-mcp config file path."""
    return config_dir() / "config.toml"


def nginx_example_file() -> Path:
    """Return the default path ``html-mcp nginx-config --write`` writes to."""
    return config_dir() / "nginx.conf.example"