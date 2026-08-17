"""Target paths for the three agents' global instruction files.

Each accessor is a plain function so tests can monkeypatch it to a tmp path
(never touch the real files during tests). Nothing here touches Path.home()
at import time — that is the test-isolation discipline this repo enforces.
"""
import os
from pathlib import Path


def _config_base() -> Path:
    """The XDG config root: $XDG_CONFIG_HOME, else ~/.config."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def claude_md_file() -> Path:
    """Claude Code's user-level instruction file."""
    return Path.home() / ".claude" / "CLAUDE.md"


def opencode_agents_file() -> Path:
    """OpenCode's user-level rules file ($XDG_CONFIG_HOME/opencode/AGENTS.md)."""
    return _config_base() / "opencode" / "AGENTS.md"


def qoder_agents_file() -> Path:
    """Qoder CLI's user-level instruction file."""
    return Path.home() / ".qoder" / "AGENTS.md"


def template_file() -> Path:
    """The bundled template (the single source of truth for block content)."""
    return Path(__file__).resolve().parent / "templates" / "AGENTS.md"