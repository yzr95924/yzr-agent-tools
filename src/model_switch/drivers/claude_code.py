"""Claude Code driver — reads/writes ~/.claude/settings.json.

Writes a single model identifier to:
- `env.ANTHROPIC_BASE_URL` — upstream base URL
- `env.ANTHROPIC_AUTH_TOKEN` — resolved API key
- `env.ANTHROPIC_MODEL` — bare model id, with `[1m]` suffix when context
  window >= 1_000_000 (the modern single-model shape).
- top-level `model` — mirrors `ANTHROPIC_MODEL`.

Anything else in `env` and the rest of the JSON file is preserved.
"""
import json
from pathlib import Path
from typing import Optional

from model_switch.drivers._atomic import atomic_write_json
from model_switch.store import ModelEntry as Model


_OWNED_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
)

_1M_THRESHOLD = 1_000_000


def _with_1m_suffix(model_name: str, context_window: Optional[int]) -> str:
    """Append [1m] suffix when context_window is set to the 1M tier."""
    if context_window is not None and context_window >= _1M_THRESHOLD:
        return model_name + "[1m]"
    return model_name


class ClaudeCodeDriver:
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

    def apply(self, model: Model, api_key: str) -> None:
        config = self.read()
        env = config.get("env", {})

        # Drop our previously-written keys so a model switch removes old refs.
        for k in _OWNED_KEYS:
            env.pop(k, None)

        model_id = _with_1m_suffix(model.name, model.context_window)

        env["ANTHROPIC_BASE_URL"] = model.base_url
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_MODEL"] = model_id
        config["env"] = env

        # Top-level `model` mirrors the suffixed active id.
        config["model"] = model_id

        atomic_write_json(self.settings_path, config)

    def current(self) -> dict:
        return self.read().get("env", {})


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
