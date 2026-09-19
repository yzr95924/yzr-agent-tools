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


# The driver `_resolve_driver(None)` falls back to. Kept here so the lookup
# and the registered driver's `name` cannot drift apart.
DEFAULT_DRIVER_NAME = "claude-code"


class AgentDriver(Protocol):
    """Protocol every agent driver must satisfy."""
    name: str
    settings_path: Path
    # Whether this agent holds a multi-model catalog that model-switch
    # mirrors from models.toml (opencode: True). Single-slot agents
    # (claude-code) keep just the active model: False.
    supports_catalog: bool = False

    def read(self) -> dict:
        """Read the agent's config file as a dict; {} if missing/empty."""
        ...

    def apply(self, models: List[Model], active: Model) -> None:
        """Write the active model into the agent's config file.

        `models` is the full registry list; single-slot drivers ignore it and
        render only `active`, catalog drivers mirror the whole list and set
        `active` as the default pointer. The uniform signature is deliberate:
        the CLI loops over drivers without branching on their kind.
        """
        ...

    def current(self) -> dict:
        """Return the env-relevant subset of the current config."""
        ...

    # Optional methods, probed by the CLI with getattr:
    #
    # - `validate(models, active=None)` — render without writing and raise
    #   `ValueError` on anything the write would reject. Catalog-capable
    #   drivers should implement it so `model use` can fail before touching
    #   any agent config; a driver with nothing to pre-flight may omit it.
    # - catalog-capable drivers (supports_catalog=True) implement
    #   `sync_catalog(models)` — reconcile the agent's catalog with `models`
    #   without changing the default pointer unless it vanished.
    # - single-slot drivers implement `clear()` — drop the managed slot's
    #   keys.


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
        """Return the default driver (`DEFAULT_DRIVER_NAME`).

        `_ensure_default_registered` always registers claude-code, so this is
        a plain lookup; None means the caller ran before any registration.
        """
        return self._drivers.get(DEFAULT_DRIVER_NAME)


# Singleton registry; built-in drivers are registered lazily by
# cli._ensure_default_registered() on first use (never at import time).
registry = DriverRegistry()