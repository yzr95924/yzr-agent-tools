"""OpenCode driver — reads/writes the OpenCode global config.

OpenCode loads its global config from ``$XDG_CONFIG_HOME/opencode/opencode.json``
(default ``~/.config/opencode/opencode.json``) — **not** ``~/.opencode.json``.
Writing the wrong path means the config is silently ignored and OpenCode
starts on its default model.

Writes a single model under our ``provider.<id>`` block (``PROVIDER_ID =
"yzr"``). A non-built-in provider must declare ``npm`` so OpenCode knows which
AI-SDK adapter to load; Anthropic-compatible upstreams use ``@ai-sdk/anthropic``::

  {
    "provider": {
      "yzr": {
        "npm": "@ai-sdk/anthropic",
        "name": "yzr",
        "options": { "baseURL": ..., "apiKey": "<resolved-key>" },
        "models": { "<model_id>": {} }
      }
    },
    "model": "yzr/<model_id>"
  }

The resolved API key is written **verbatim** into ``options.apiKey`` — matching
the claude-code driver and OpenCode's own convention for custom providers
(OpenCode supports a ``{env:VAR}`` placeholder, but we don't use it: the key
lives in the config file, so the file holds a secret; keep its permissions
tight). ``Model.context_window`` is intentionally NOT surfaced: OpenCode's
schema requires ``limit.output`` whenever ``limit`` is present, and we only
track context — emitting a partial ``{limit:{context}}`` fails validation and
makes the model unavailable. Omitting matches OpenCode's own handling for
custom providers.
"""
import json
from pathlib import Path
from typing import Dict

from model_switch import paths
from model_switch.drivers._atomic import atomic_write_json
from model_switch.store import ModelEntry as Model


PROVIDER_ID = "yzr"

# Anthropic-compatible upstreams (model-switch's only supported protocol) load
# the @ai-sdk/anthropic adapter. Without `npm`, OpenCode reports
# "Provider not found" and silently falls back to its default model.
NPM_ADAPTER = "@ai-sdk/anthropic"


class OpenCodeDriver:
    name = "opencode"

    def __init__(self, settings_path: Path = None) -> None:
        if settings_path is None:
            settings_path = paths.opencode_config_file()
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
        """Write the model into the OpenCode config.

        The resolved `api_key` is written verbatim into `options.apiKey`
        (matching the claude-code driver). model-switch does not use OpenCode's
        `{env:VAR}` placeholder, so the key is stored in the config file.
        """
        config = self.read()
        providers = config.get("provider", {})

        provider_block: Dict = providers.get(PROVIDER_ID, {})

        # Tell OpenCode which AI-SDK adapter loads this provider. Without it
        # the custom provider is unresolvable.
        provider_block["npm"] = NPM_ADAPTER
        provider_block.setdefault("name", PROVIDER_ID)

        options = provider_block.get("options", {})
        options["baseURL"] = model.base_url
        options["apiKey"] = api_key
        provider_block["options"] = options

        # NOTE: no `limit` — see module docstring (partial limit is invalid).
        provider_block["models"] = {model.name: {}}

        providers[PROVIDER_ID] = provider_block
        config["provider"] = providers

        config["model"] = "{}/{}".format(PROVIDER_ID, model.name)

        atomic_write_json(self.settings_path, config)

    def current(self) -> dict:
        config = self.read()
        if not config:
            return {}
        return {
            "provider": PROVIDER_ID,
            "model": config.get("model", ""),
        }


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
