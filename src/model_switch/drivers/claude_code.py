"""Claude Code driver — reads/writes ~/.claude/settings.json.

Writes a single model identifier to:
- `env.ANTHROPIC_BASE_URL` — upstream base URL
- `env.ANTHROPIC_AUTH_TOKEN` — resolved API key
- `env.ANTHROPIC_MODEL` — bare model id, with `[1m]` suffix when context
  window >= 1_000_000 (the modern single-model shape).
- `env.ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` + `ANTHROPIC_SMALL_FAST_MODEL`
  — every Claude Code model *tier* pinned to our id. Auxiliary calls (the
  auto-mode Bash safety classifier, conversation/title generation, ...) resolve
  through these tier slots; at their built-in defaults they hit hardcoded Claude
  ids (e.g. `claude-sonnet-5[1m]`) that a custom upstream can't serve — which
  surfaces as "auto mode ... temporarily unavailable". Pinning every tier to our
  model id forces those calls onto the configured upstream too.
- top-level `model` — mirrors `ANTHROPIC_MODEL`.

Anything else in `env` and the rest of the JSON file is preserved.
"""
import json
from pathlib import Path
from typing import Optional

from model_switch.drivers._atomic import atomic_write_json
from model_switch.store import ModelEntry as Model


# Connection + main-model keys we own in the `env` block.
_OWNED_KEYS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
)

# Claude Code model tiers. Auxiliary calls resolve through these slots, so we
# pin every one to our model id — otherwise they fall back to hardcoded Claude
# ids (e.g. claude-sonnet-5[1m]) the upstream can't serve, which is the root
# cause of "auto mode temporarily unavailable" on custom upstreams.
_TIER_MODEL_KEYS = (
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
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
        for k in _OWNED_KEYS + _TIER_MODEL_KEYS:
            env.pop(k, None)

        model_id = _with_1m_suffix(model.name, model.context_window)

        env["ANTHROPIC_BASE_URL"] = model.base_url
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_MODEL"] = model_id
        # Pin every Claude Code model tier to our id so auxiliary calls (the
        # Bash safety classifier, title/conversation generation, ...) ride the
        # same upstream instead of a hardcoded Claude id the gateway lacks.
        for k in _TIER_MODEL_KEYS:
            env[k] = model_id
        config["env"] = env

        # Top-level `model` mirrors the suffixed active id.
        config["model"] = model_id

        atomic_write_json(self.settings_path, config)

    def current(self) -> dict:
        return self.read().get("env", {})


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
