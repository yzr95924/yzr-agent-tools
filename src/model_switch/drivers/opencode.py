"""OpenCode driver — reads/writes ~/.opencode.json.

Writes a single model under our `provider.<id>` block (`PROVIDER_ID = "yzr"`):

  {
    "provider": {
      "yzr": {
        "options": { "baseURL": ..., "apiKey": "{env:VAR}" },
        "models": { "<model_id>": { "limit": { "context": N } } }
      }
    },
    "model": "yzr/<model_id>"
  }

`Model.context_window` is written to `models.<id>.limit.context` (not as a
suffix on the id). API key is referenced via OpenCode's `{env:VAR}` placeholder.
"""
import json
from pathlib import Path
from typing import Dict

from model_switch.drivers._atomic import atomic_write_json
from model_switch.store import ModelEntry as Model


PROVIDER_ID = "yzr"


class OpenCodeDriver:
    name = "opencode"

    def __init__(self, settings_path: Path = None) -> None:
        if settings_path is None:
            settings_path = Path.home() / ".opencode.json"
        self.settings_path = settings_path

    def read(self) -> dict:
        if not self.settings_path.exists():
            return {}
        with open(self.settings_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return {}
        return json.loads(text)

    def apply(self, model: Model, api_key: str) -> None:  # noqa: ARG002
        """Write the model into the OpenCode config.

        The raw `api_key` is intentionally NOT written — we only reference
        `model.api_key_env` via OpenCode's `{env:NAME}` placeholder.
        """
        config = self.read()
        providers = config.get("provider", {})

        provider_block: Dict = providers.get(PROVIDER_ID, {})
        options = provider_block.get("options", {})
        options["baseURL"] = model.base_url
        options["apiKey"] = "{" + "env:" + model.api_key_env + "}"
        provider_block["options"] = options

        entry: Dict = {}
        if model.context_window is not None:
            entry["limit"] = {"context": model.context_window}
        provider_block["models"] = {model.name: entry}

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
