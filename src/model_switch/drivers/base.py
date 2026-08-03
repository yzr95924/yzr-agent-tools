"""Base Protocol + Registry for agent drivers.

A driver encapsulates the knowledge of how to read and modify one
specific agent's global configuration file (e.g., Claude Code's
~/.claude/settings.json, OpenCode's ~/.config/opencode/opencode.json).
"""
from pathlib import Path
from typing import Dict, List, Optional

# typing.Protocol is Python 3.8+ (PEP 544); fall back to a plain stand-in on
# 3.7. Used here only as a structural type hint (no isinstance / nothing
# subclasses it), so a plain class is behaviorally equivalent on 3.7. Mirrors
# _compat.py's tomllib/tomli fallback.
try:
    from typing import Protocol
except ImportError:  # Python <3.8
    class Protocol:  # type: ignore[no-redef]
        pass

from model_switch.store import ModelEntry as Model


class AgentDriver(Protocol):
    """Protocol every agent driver must satisfy."""
    name: str
    settings_path: Path

    def read(self) -> dict:
        """Read the agent's config file as a dict; {} if missing/empty."""
        ...

    def apply(self, model: Model, api_key: str) -> None:
        """Write the model into the agent's config file."""
        ...

    def current(self) -> dict:
        """Return the env-relevant subset of the current config."""
        ...


class DriverRegistry:
    """In-process registry of installed drivers.

    claude-code and opencode are both registered lazily by
    cli._ensure_default_registered on first use. Tests populate the
    registry manually with tmp-path drivers.
    """
    def __init__(self) -> None:
        self._drivers: Dict[str, AgentDriver] = {}

    def register(self, driver: AgentDriver) -> None:
        self._drivers[driver.name] = driver

    def get(self, name: str) -> AgentDriver:
        if name not in self._drivers:
            raise KeyError(
                "Unknown agent driver {!r}. Available: {}".format(
                    name, sorted(self._drivers.keys())
                )
            )
        return self._drivers[name]

    def list(self) -> List[str]:
        return sorted(self._drivers.keys())

    def default(self) -> Optional[AgentDriver]:
        """Return the default driver (currently: claude-code)."""
        if "claude-code" in self._drivers:
            return self._drivers["claude-code"]
        if not self._drivers:
            return None
        return self._drivers[sorted(self._drivers.keys())[0]]


# Singleton registry; built-in drivers are registered lazily by
# cli._ensure_default_registered() on first use (never at import time).
registry = DriverRegistry()