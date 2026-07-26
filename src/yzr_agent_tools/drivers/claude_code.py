"""Claude Code driver — reads/writes ~/.claude/settings.json."""
import json
import os
from pathlib import Path

from yzr_agent_tools.config import Model


# Keys we own (yzr writes these on `model use`). Anything else in env
# (DISABLE_TELEMETRY, theme colors, custom env vars) is preserved.
_YZR_OWNED_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)


class ClaudeCodeDriver:
    """Modifies Claude Code's global settings.json env block."""

    name = "claude-code"

    def __init__(self, settings_path: Path = None) -> None:
        if settings_path is None:
            settings_path = Path.home() / ".claude" / "settings.json"
        self.settings_path = settings_path

    def read(self) -> dict:
        if not self.settings_path.exists():
            return {}
        with open(self.settings_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return {}
        return json.loads(text)

    def apply(self, main: Model, small: Model, api_key: str) -> None:
        config = self.read()
        env = config.get("env", {})
        # Drop our previously-written keys so a model switch removes old refs.
        for k in _YZR_OWNED_KEYS:
            env.pop(k, None)
        env["ANTHROPIC_BASE_URL"] = main.base_url
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = main.model_name
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = main.model_name
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = small.model_name
        config["env"] = env
        _atomic_write_json(self.settings_path, config)

    def current(self) -> dict:
        return self.read().get("env", {})


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: write tmp, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# NOTE: We intentionally do NOT auto-register this driver at import time.
# Doing so creates a ClaudeCodeDriver pointed at the real
# ~/.claude/settings.json the moment any test imports yzr_agent_tools —
# a test-isolation hazard. The CLI registers the default driver lazily
# on first use (see cli._default_driver).
# Tests that want isolation should populate the registry themselves.