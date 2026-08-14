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
        "options": { "baseURL": "<base_url>/v1", "apiKey": "<resolved-key>" },
        "models": { "<model_id>": {} }
      }
    },
    "model": "yzr/<model_id>"
  }

The resolved API key is written **verbatim** into ``options.apiKey`` — matching
the claude-code driver and OpenCode's own convention for custom providers
(OpenCode supports a ``{env:VAR}`` placeholder, but we don't use it: the key
lives in the config file, so the file holds a secret; keep its permissions
tight).

``baseURL`` is **not** written verbatim: ``@ai-sdk/anthropic`` appends only
``/messages`` to it (treating it as a prefix that already includes the API
version), so the driver ensures it ends in a ``/v<N>`` segment. The model's
``base_url`` is stored without ``/v1`` — the form the claude-code driver
wants, since Claude Code appends ``/v1`` itself; this driver appends ``/v1``
when rendering for OpenCode, so the same stored value serves both agents.
Without this, opencode requests ``.../anthropic/messages``, the upstream
answers with a 404 wrapped in HTTP 200, and ai-sdk's SSE parser drops the
non-event body silently — a zero-token empty reply with no error event.

``Model.context_window`` is surfaced as ``limit.context``: a custom provider
isn't on models.dev, so OpenCode can't infer the context budget and would fall
back to a default. OpenCode's schema requires ``context`` and ``output``
together (``limit.required == [context, output]``), so context is paired with a
default ``output`` cap (``_DEFAULT_MAX_OUTPUT``). When ``context_window`` is
unknown the whole ``limit`` block is omitted — a partial ``{limit:{context}}``
fails validation and makes the model unavailable.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict

from model_switch import paths
from model_switch.drivers._atomic import atomic_write_json
from model_switch.store import ModelEntry as Model


PROVIDER_ID = "yzr"

# Anthropic-compatible upstreams (model-switch's only supported protocol) load
# the @ai-sdk/anthropic adapter. Without `npm`, OpenCode reports
# "Provider not found" and silently falls back to its default model.
NPM_ADAPTER = "@ai-sdk/anthropic"

# @ai-sdk/anthropic appends only `/messages` to baseURL, treating it as a
# prefix that already includes the API version. base_url is stored WITHOUT /v1
# (the form the claude-code driver wants — Claude Code appends /v1 itself), so
# here we ensure a version segment is present. Without it opencode requests
# `.../anthropic/messages`, which upstreams answer with a 404 wrapped in HTTP
# 200; ai-sdk's SSE parser drops the non-event body silently and you get a
# zero-token empty reply with no error event.
_VERSION_SEGMENT = re.compile(r"/v\d+$")

# Default max-output cap paired with every emitted ``limit.context``. OpenCode's
# schema forces ``context`` and ``output`` to appear together
# (``limit.required == [context, output]``); model-switch tracks only context,
# so output takes a habit-level default rather than a per-model registry field.
# Value aligns with OpenCode's bundled models.dev MiniMax-M3 (output 131072);
# real Anthropic-compatible gateways (glm/kimi/qwen/minimax) tolerate it (the
# same constant is end-to-end verified in llmw's opencode overlay). Upgrade to a
# per-model field when output needs to vary by model.
_DEFAULT_MAX_OUTPUT = 131_072


def _base_url_for_ai_sdk(base_url):
    """Render ``model.base_url`` into the baseURL ``@ai-sdk/anthropic`` expects.

    ai-sdk appends only ``/messages``, so baseURL must already contain the
    version segment. Stored base_url values lack ``/v1`` (Claude Code's form),
    so append it unless a ``/v<N>`` segment is already present.
    """
    base = base_url.rstrip("/")
    if not _VERSION_SEGMENT.search(base):
        base += "/v1"
    return base


def _render_model_entry(model: Model) -> Dict[str, Any]:
    """Render the per-model object stored under ``provider.<id>.models``.

    When ``model.context_window`` is known, emit a ``limit`` block so OpenCode
    manages the real context budget (a custom provider isn't on models.dev, so
    OpenCode otherwise can't infer it). OpenCode's schema requires ``context``
    and ``output`` together, so context is paired with ``_DEFAULT_MAX_OUTPUT``.
    When context is unknown, omit ``limit`` entirely — a partial block would
    fail validation and make the model unavailable.
    """
    if model.context_window is None:
        return {}
    return {
        "limit": {
            "context": model.context_window,
            "output": _DEFAULT_MAX_OUTPUT,
        }
    }


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

        `baseURL` is /v1-adapted via `_base_url_for_ai_sdk` — see the module
        docstring for why this differs from the claude-code driver.
        """
        config = self.read()
        providers = config.get("provider", {})

        provider_block: Dict = providers.get(PROVIDER_ID, {})

        # Tell OpenCode which AI-SDK adapter loads this provider. Without it
        # the custom provider is unresolvable.
        provider_block["npm"] = NPM_ADAPTER
        provider_block.setdefault("name", PROVIDER_ID)

        options = provider_block.get("options", {})
        options["baseURL"] = _base_url_for_ai_sdk(model.base_url)
        options["apiKey"] = api_key
        provider_block["options"] = options

        # Per-model object: a `limit` block when context_window is known (a
        # custom provider isn't on models.dev, so OpenCode needs it told), else
        # an empty entry. See _render_model_entry for the schema constraint.
        provider_block["models"] = {model.name: _render_model_entry(model)}

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
