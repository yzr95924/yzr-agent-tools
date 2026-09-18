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
      "yzr-zai": {
        "npm": "@ai-sdk/anthropic",
        "name": "yzr-zai",
        "options": { "baseURL": "<base_url>/v1", "apiKey": "<resolved-key>" },
        "models": { "<model name>": {} }
      },
      "yzr-kimi": { ... }
    },
    "model": "yzr-zai/glm-5.3"
  }

One provider per **upstream**, not per model: ``baseURL`` and ``apiKey`` are
**provider-level** (not per-model), so models share a block exactly when they
share both. A model may pin its group name with ``provider = "<name>"``
(→ ``yzr-<name>``); otherwise the name derives from the upstream host
(``api.z.ai`` → ``zai``, ``api.kimi.com`` → ``kimi``,
``dashscope.aliyuncs.com`` → ``dashscope``). Declared names win collisions
with derived slugs; leftovers get ``-2``/``-3`` suffixes in sorted order, so
re-renders are stable. All models under one declared name must share one
upstream — a partial key rotation fails loudly instead of silently splitting
the group — and model *names* must be unique within a group, since they key
the provider's ``models`` map.

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

``reasoning`` and ``variants`` from a model entry are passed through into the
model block as-is. ``reasoning = true`` marks the model as reasoning-capable
(OpenCode gates some of its behaviour on that flag), and ``variants`` declares
the effort tiers OpenCode's variant cycle (ctrl+t, ``variant_cycle``) offers —
each tier is an opaque payload OpenCode merges into the request options. What
the tiers are and which shapes an upstream accepts is user data in models.toml
(optionally via ``[variants_presets]``, expanded by
`model_switch.variants.expand`); this driver holds no per-model or per-gateway
knowledge, so adding a model or an upstream never touches it.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from model_switch import paths
from model_switch.drivers._atomic import atomic_write_json
from model_switch.store import ModelEntry as Model


PROVIDER_ID = "yzr"

# The provider namespace model-switch owns. Models are grouped by upstream
# (baseURL/apiKey are provider-level, so a block is shareable exactly when
# both match) and each group renders as `yzr-<host-slug>` — see
# `_upstream_slug` — or as `yzr-<name>` when the model pins one with
# `provider = "<name>"`. The bare `yzr` id is the legacy single-slot form and
# per-model `yzr-<model_id>` ids are the pre-grouping form; both stay
# reclaimable so upgrades migrate automatically.
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

    ``reasoning`` and ``variants`` are passed through verbatim from
    ``models.toml`` when present: ``reasoning = true`` marks the model as
    reasoning-capable, and ``variants`` declares the effort tiers OpenCode's
    variant cycle (ctrl+t) offers. Tier payloads are opaque — OpenCode merges
    them into the request options, so model-switch never inspects, rewrites
    or varies them by model. ``variants`` may arrive materialized from a
    preset (see `model_switch.variants.expand`); this driver only ever sees
    the plain dict.

    When ``model.context_window`` is known, emit a ``limit`` block so OpenCode
    manages the real context budget (a custom provider isn't on models.dev, so
    OpenCode otherwise can't infer it). OpenCode's schema requires ``context``
    and ``output`` together, so context is paired with ``_DEFAULT_MAX_OUTPUT``.
    When context is unknown, omit ``limit`` entirely — a partial block would
    fail validation and make the model unavailable.

    With neither optional field set and no context_window this returns ``{}``
    — the same output as before those fields existed.
    """
    entry: Dict[str, Any] = {}
    if model.extra.get("reasoning") is True:
        entry["reasoning"] = True
    variants = model.extra.get("variants")
    if isinstance(variants, dict) and variants:
        entry["variants"] = variants
    if model.context_window is not None:
        entry["limit"] = {
            "context": model.context_window,
            "output": _DEFAULT_MAX_OUTPUT,
        }
    return entry


def _upstream_slug(base_url: str) -> str:
    """Derive a short provider slug from an upstream base_url host.

    ``api.z.ai`` → ``zai`` (first label is ≤2 chars, so join the second),
    ``api.kimi.com`` → ``kimi``, ``dashscope.aliyuncs.com`` → ``dashscope``.
    Leading ``api.``/``www.`` labels are dropped; non-alphanumerics stripped.
    """
    host = base_url.split("//")[-1].split("/")[0].lower()
    labels = [l for l in host.split(".") if l]
    if labels and labels[0] in ("api", "www"):
        labels = labels[1:]
    if not labels:
        return "upstream"
    slug = labels[0]
    if len(slug) <= 2 and len(labels) > 1:
        slug += labels[1]
    slug = re.sub(r"[^a-z0-9]", "", slug)
    return slug or "upstream"


# Group key: (declared provider name or None, base_url, api_key). A provider
# block is shareable exactly when all three match.
_GroupKey = Tuple[Optional[str], str, str]

_PROVIDER_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def _declared_provider(m: Model) -> Optional[str]:
    """The model's ``provider = "<name>"`` declaration, if any."""
    value = m.extra.get("provider")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            "model {!r}: provider must be a string, got {}".format(
                m.model_id, type(value).__name__))
    return value


def _validate_provider_names(groups: Dict[_GroupKey, List[Model]]) -> None:
    """Loud checks on declared provider names (see `_group_assignments`)."""
    by_name: Dict[str, List[_GroupKey]] = {}
    for key in groups:
        if key[0] is not None:
            by_name.setdefault(key[0], []).append(key)
    for name, keys in sorted(by_name.items()):
        if name.startswith(PROVIDER_PREFIX):
            raise ValueError(
                "provider {!r} must not start with {!r} — the tool adds that "
                "prefix when building the provider id".format(
                    name, PROVIDER_PREFIX))
        if not _PROVIDER_NAME_RE.match(name):
            raise ValueError(
                "provider {!r} is not a valid name: use lowercase letters, "
                "digits and hyphens ({}); '/' or spaces would corrupt the "
                "'<provider>/<model>' default pointer".format(
                    name, _PROVIDER_NAME_RE.pattern))
        if len(keys) > 1:
            fields = []
            if len({k[1] for k in keys}) > 1:
                fields.append("base_url")
            if len({k[2] for k in keys}) > 1:
                fields.append("api_key")
            model_ids = sorted(m.model_id for k in keys for m in groups[k])
            raise ValueError(
                "provider {!r} is declared with conflicting upstreams ({} "
                "differ): {}. One provider block holds one baseURL/apiKey — "
                "give the models distinct provider names or align the "
                "values".format(
                    name, " and ".join(fields),
                    ", ".join(repr(i) for i in model_ids)))


def _group_assignments(models: List[Model]) -> Tuple[Dict[_GroupKey, List[Model]], Dict[_GroupKey, str]]:
    """Group models into provider blocks and assign provider ids.

    Returns ``(groups, pid_by_key)``. A model may pin its id with
    ``provider = "<name>"`` → ``yzr-<name>``; without it the id is derived
    from the base_url host (``yzr-<host-slug>``), so a pinned name outlives
    base_url changes. Groups are keyed by ``(declared, base_url, api_key)`` —
    baseURL/apiKey are provider-level, so a block is shareable exactly when
    both match. Declared names win collisions with derived slugs; leftovers
    get ``-2``/``-3`` suffixes in sorted order, so repeated renders are
    byte-stable. All models declaring one name must share one upstream — a
    partial key rotation fails loudly instead of silently splitting the
    group in two. Duplicate model names within a group would overwrite each
    other in the provider's ``models`` map — rejected loudly too.
    """
    groups: Dict[_GroupKey, List[Model]] = {}
    for m in models:
        groups.setdefault(
            (_declared_provider(m), m.base_url, m.api_key or ""), []
        ).append(m)
    _validate_provider_names(groups)

    pid_by_key: Dict[_GroupKey, str] = {}
    taken: set = set()

    def assign(key: _GroupKey, base: str) -> None:
        slug = base
        n = 2
        while slug in taken:
            slug = "{}-{}".format(base, n)
            n += 1
        taken.add(slug)
        pid_by_key[key] = PROVIDER_PREFIX + slug

    for key in sorted((k for k in groups if k[0] is not None),
                      key=lambda k: k[0]):
        assign(key, key[0])
    for key in sorted((k for k in groups if k[0] is None),
                      key=lambda k: (k[1], k[2])):
        assign(key, _upstream_slug(key[1]))

    for members in groups.values():
        seen = set()
        for m in members:
            if m.name in seen:
                raise ValueError(
                    "model names must be unique within one upstream: "
                    "{!r} is claimed by multiple models on {}".format(
                        m.name, m.base_url))
            seen.add(m.name)
    return groups, pid_by_key


def _provider_layout(models: List[Model]) -> Tuple[Dict[_GroupKey, str], Dict[_GroupKey, List[Model]], Dict[str, str]]:
    """Return ``(pid_by_key, groups, ref_by_model_id)`` for a model list.

    ``ref_by_model_id`` maps model_id → ``<provider_id>/<model name>`` (the
    form OpenCode's default pointer uses), letting references be resolved by
    lookup instead of string surgery on the provider id.
    """
    groups, pid_by_key = _group_assignments(models)
    ref_by_model_id: Dict[str, str] = {}
    for key, members in groups.items():
        for m in members:
            ref_by_model_id[m.model_id] = "{}/{}".format(pid_by_key[key], m.name)
    return pid_by_key, groups, ref_by_model_id


def _is_owned_provider(provider_id: str) -> bool:
    """Whether model-switch owns (and may reclaim) this provider id.

    Covers the grouped ``yzr-<slug>`` ids, the pre-grouping per-model
    ``yzr-<model_id>`` ids, and the legacy single-slot ``yzr``, so upgrades
    migrate automatically.
    """
    return provider_id == PROVIDER_ID or provider_id.startswith(PROVIDER_PREFIX)


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

        Reconciles the whole namespace: models are grouped into upstreams
        (``(declared provider, base_url, api_key)``; see
        `_group_assignments`) and each group renders as one
        ``yzr-<host-slug>`` or ``yzr-<name>`` provider; any ``yzr-*`` provider
        not produced by that grouping (including per-model ``yzr-<model_id>``
        blocks from the pre-grouping scheme, and the legacy single-slot
        ``yzr``) is deleted with its plaintext key. Foreign providers and
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
        keyed = [m for m in models if m.api_key]
        pid_by_key, groups, _refs = _provider_layout(keyed)
        for key in sorted(groups, key=lambda k: pid_by_key[k]):
            _declared, base_url, api_key = key
            members = sorted(groups[key], key=lambda m: m.name)
            providers[pid_by_key[key]] = {
                "npm": NPM_ADAPTER,
                "name": pid_by_key[key],
                "options": {
                    "baseURL": _base_url_for_ai_sdk(base_url),
                    "apiKey": api_key,
                },
                # Per-model object: `reasoning`/`variants` passed through from
                # models.toml (tier declarations for the variant cycle), plus a
                # `limit` block when context_window is known (a custom provider
                # isn't on models.dev, so OpenCode needs it told). See
                # _render_model_entry for the schema constraint.
                "models": {m.name: _render_model_entry(m) for m in members},
            }

        config["provider"] = providers
        default = self._resolve_default(config.get("model"), keyed, active_id)
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
        if not models:
            return None
        _pid_by_key, _groups, ref_by_model_id = _provider_layout(models)
        if active_id is not None and active_id in ref_by_model_id:
            return ref_by_model_id[active_id]
        if current:
            if current in ref_by_model_id.values():
                return current
            if _is_owned_provider(current.split("/", 1)[0]):
                # Ours but vanished — fall to the first remaining model.
                for m in models:
                    return ref_by_model_id[m.model_id]
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
