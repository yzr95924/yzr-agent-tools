"""Base Protocol + Registry for agent drivers.

A driver encapsulates the knowledge of how to read and modify one
specific agent's global configuration file (e.g., Claude Code's
settings.json). V1 ships only ClaudeCodeDriver; V2 will add OpenCode, etc.
"""
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from yzr_agent_tools.config import Model


@runtime_checkable
class AgentDriver(Protocol):
    """Protocol every agent driver must satisfy."""
    name: str
    settings_path: Path

    def read(self) -> dict:
        """Read the agent's config file as a dict; {} if missing/empty."""
        ...

    def apply(self, main: "Model", small: "Model", api_key: str) -> None:
        """Write main + small model into the agent's config file."""
        ...

    def current(self) -> dict:
        """Return the env-relevant subset of the current config."""
        ...


class DriverRegistry:
    """In-process registry of installed drivers.

    V1: only claude-code is registered. Future versions can add more.
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


# Singleton registry; populated as driver modules are imported.
registry = DriverRegistry()