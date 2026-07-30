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