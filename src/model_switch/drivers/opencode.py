"""OpenCode driver — reads/writes the OpenCode global config.

OpenCode loads its global config from ``$XDG_CONFIG_HOME/opencode/opencode.json``
(default ``~/.config/opencode/opencode.json``) — **not** ``~/.opencode.json``.
Writing the wrong path means the config is silently ignored and OpenCode
starts on its default model.

Unlike Claude Code (a single model slot), OpenCode holds a **catalog**: every
registered provider's models are listed in its model picker, and ``model``
names the default. So model-switch mirrors *all* models from models.toml into
the ``yzr-*`` provider namespace and treats ``config["model"]`` as a pointer
to the active one::

  {
    "provider": {
      "yzr-glm": {
        "npm": "@ai-sdk/anthropic",
        "name": "yzr-glm",
        "options": { "baseURL": "<base_url>/v1", "apiKey": "<resolved-key>" },
        "models": { "<model_id>": {} }
      },
      "yzr-kimi": { ... }
    },
    "model": "yzr-glm/glm-4"
  }

One provider per model: ``baseURL`` and ``apiKey`` are **provider-level**, not
per-model, so models from different upstreams (different base_url/key) cannot
share a provider block. Each ``yzr-<model_id>`` provider is self-contained and
the model picker shows one group per upstream.

Reconciliation is a mirror: ``apply()`` / ``sync_catalog()`` rewrite the whole
``yzr-*`` namespace from models.toml, deleting any ``yzr-*`` provider (or the
legacy single-slot ``yzr``) that is no longer registered — so a removed model's
provider block, including its plaintext key, disappears from disk. Everything
outside the ``yzr-*`` namespace (other providers, ``$schema``, user blocks) is
preserved. ``sync_catalog()`` keeps the current default pointer unless it
vanished (then it falls to the first remaining model, or drops the key when
none are left).

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
from typing import Any, Dict, List, Optional

from model_switch import paths
from model_switch.drivers._atomic import atomic_write_json
from model_switch.store import ModelEntry as Model


PROVIDER_ID = "yzr"

# The provider namespace model-switch owns. Each registered model becomes one
# provider `yzr-<model_id>` (baseURL/apiKey are provider-level, so models from
# different upstreams can't share a block). The bare `yzr` id is the legacy
# single-slot form — still reclaimed so an upgrade migrates automatically.
PROVIDER_PREFIX = "yzr-"

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


def _provider_id(model_id: str) -> str:
    """Provider id for a registered model: ``yzr-<model_id>``."""
    return PROVIDER_PREFIX + model_id


def _model_id_from_provider(provider_id: str) -> Optional[str]:
    """Reverse ``_provider_id``; None for foreign / legacy-``yzr`` ids."""
    if provider_id.startswith(PROVIDER_PREFIX):
        return provider_id[len(PROVIDER_PREFIX):]
    return None


def _is_owned_provider(provider_id: str) -> bool:
    """Whether model-switch owns (and may reclaim) this provider id.

    Covers both the per-model ``yzr-*`` ids and the legacy single-slot ``yzr``,
    so an upgrade to the catalog form migrates automatically.
    """
    return provider_id == PROVIDER_ID or provider_id.startswith(PROVIDER_PREFIX)


def _model_id_from_reference(model_ref: str) -> Optional[str]:
    """Extract the model_id from a ``yzr-<id>/<name>`` default reference."""
    if not model_ref or "/" not in model_ref:
        return None
    return _model_id_from_provider(model_ref.split("/", 1)[0])


def _find_model(models: List[Model], model_id: str) -> Optional[Model]:
    for m in models:
        if m.model_id == model_id:
            return m
    return None


class OpenCodeDriver:
    name = "opencode"
    supports_catalog = True

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

    def apply(self, models: List[Model], active: Model) -> None:
        """Write the full catalog into the OpenCode config, defaulting to `active`.

        The resolved `api_key` is written verbatim into each provider's
        `options.apiKey` (matching the claude-code driver). model-switch does
        not use OpenCode's `{env:VAR}` placeholder, so keys are stored in the
        config file.

        `baseURL` is /v1-adapted via `_base_url_for_ai_sdk` — see the module
        docstring for why this differs from the claude-code driver.
        """
        if not active.api_key:
            raise ValueError(
                "model {!r} has no api_key in models.toml.".format(active.model_id)
            )
        self.sync_catalog(models, active_id=active.model_id, create=True)

    def sync_catalog(self, models: List[Model], active_id: str = None,
                     create: bool = False) -> None:
        """Mirror `models` into the ``yzr-*`` provider namespace.

        Reconciles the whole namespace: every registered model gets its own
        ``yzr-<model_id>`` provider; any ``yzr-*``/legacy ``yzr`` provider not
        in `models` is deleted (with its plaintext key). Foreign providers and
        top-level keys are preserved.

        The default pointer (`config["model"]`) is kept when it still names a
        synced provider; otherwise it falls to `active_id`, then the first
        remaining model, then the key is dropped. Models without an api_key are
        skipped (they'd render an unusable provider).

        `create=False` (the catalog-sync path from add/remove/import) leaves a
        missing config file alone — no file is created out of thin air; only a
        targeted `apply()` (`create=True`) does.
        """
        if not create and not self.settings_path.exists():
            return

        config = self.read()
        providers = {
            k: v for k, v in config.get("provider", {}).items()
            if not _is_owned_provider(k)
        }
        for model in models:
            if not model.api_key:
                continue
            provider_block = {
                "npm": NPM_ADAPTER,
                "name": _provider_id(model.model_id),
                "options": {
                    "baseURL": _base_url_for_ai_sdk(model.base_url),
                    "apiKey": model.api_key,
                },
                # Per-model object: a `limit` block when context_window is known
                # (a custom provider isn't on models.dev, so OpenCode needs it
                # told), else an empty entry. See _render_model_entry for the
                # schema constraint.
                "models": {model.name: _render_model_entry(model)},
            }
            providers[_provider_id(model.model_id)] = provider_block

        config["provider"] = providers
        default = self._resolve_default(config.get("model"), models, active_id)
        if default is None:
            config.pop("model", None)
        else:
            config["model"] = default

        atomic_write_json(self.settings_path, config)

    def _resolve_default(self, current: Optional[str], models: List[Model],
                         active_id: Optional[str]) -> Optional[str]:
        """Pick `config["model"]`: active_id wins, else the current pointer
        stays if it's ours (`yzr-*`) and still names a synced provider; ours
        but vanished falls to the first remaining model, then None (drop the
        key). A foreign pointer (or an absent key) is never touched — moving
        the default is the `model use` path's job, and sync_catalog must not
        hijack a default the user set themselves."""
        if active_id is not None:
            m = _find_model(models, active_id)
            if m is not None and m.api_key:
                return "{}/{}".format(_provider_id(m.model_id), m.name)
        if current:
            mid = _model_id_from_reference(current)
            if mid is not None:
                m = _find_model(models, mid)
                if m is not None and m.api_key:
                    return current
                # Ours but vanished — fall to the first remaining model.
                for m in models:
                    if m.api_key:
                        return "{}/{}".format(_provider_id(m.model_id), m.name)
                return None
            # Foreign reference — not ours to move.
            return current
        # No default key — don't conjure one; `model use` sets it.
        return None

    def current(self) -> dict:
        config = self.read()
        if not config:
            return {}
        out = {"model": config.get("model", "")}
        providers = sorted(
            k for k in config.get("provider", {}) if _is_owned_provider(k)
        )
        if providers:
            out["catalog"] = ", ".join(providers)
        return out


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
