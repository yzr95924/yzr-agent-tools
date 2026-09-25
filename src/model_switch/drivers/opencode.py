"""OpenCode driver — reads/writes the OpenCode global config.

OpenCode loads its global config from ``$XDG_CONFIG_HOME/opencode/opencode.json``
(default ``~/.config/opencode/opencode.json``) — **not** ``~/.opencode.json``.
Writing the wrong path means the config is silently ignored and OpenCode
starts on its default model.

The shapes written here are OpenCode **V2** native shapes. V2 still reads V1
config, but it drops V1 model fields with a warning and normalizes the rest in
memory, so this driver writes only what V2 actually consumes. The V1
``provider`` map is still *read* — one sync reclaims the ``yzr-*`` blocks an
older model-switch wrote there, then deletes the key if nothing else remains.

Unlike Claude Code (a single model slot), OpenCode holds a **catalog**: every
registered provider's models are listed in its model picker, and ``model``
names the default. So model-switch mirrors *all* models from models.toml into
the ``yzr-*`` provider namespace and treats ``config["model"]`` as a pointer
to the active one::

  {
    "providers": {
      "yzr-zai": {
        "package": "@opencode/ai/providers/anthropic",
        "name": "yzr-zai",
        "settings": { "baseURL": "<base_url>/v1", "apiKey": "<resolved-key>" },
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

The resolved API key is written **verbatim** into ``settings.apiKey`` —
matching the claude-code driver and OpenCode's own convention for custom
providers (OpenCode supports a ``{env:VAR}`` placeholder, but we don't use it:
the key lives in the config file, so the file holds a secret; keep its
permissions tight).

``baseURL`` is **not** written verbatim: the Anthropic package appends only
``/messages`` to it (treating it as a prefix that already includes the API
version), so the driver ensures it ends in a ``/v<N>`` segment. The model's
``base_url`` is stored without ``/v1`` — the form the claude-code driver
wants, since Claude Code appends ``/v1`` itself; this driver appends ``/v1``
when rendering for OpenCode, so the same stored value serves both agents.
Without this, opencode requests ``.../anthropic/messages``, the upstream
answers with a 404 wrapped in HTTP 200, and the SSE parser drops the
non-event body silently — a zero-token empty reply with no error event.

``Model.context_window`` is surfaced as ``limit.context``: a custom provider
isn't on models.dev, so OpenCode can't infer the context budget and would fall
back to a default. OpenCode's schema requires ``context`` and ``output``
together, so context is paired with a default ``output`` cap
(``_DEFAULT_MAX_OUTPUT``). When ``context_window`` is unknown the whole
``limit`` block is omitted — a partial ``{limit:{context}}`` fails validation
and makes the model unavailable.

``variants`` declares the effort tiers OpenCode's variant selection
(``provider/model#variant``) offers. V2 renders them as the array shape
``[{ "id": <tier>, "settings": <payload> }, ...]``; the payload is user data
from models.toml (optionally via ``[variants_presets]``, expanded by
`model_switch.variants.expand`) and this driver holds no per-model or
per-gateway knowledge, so adding a model or an upstream never touches it.
OpenCode V2 computes no built-in tiers for custom providers, so the declared
tiers are exactly the whole set — no muting, no merging. Declaration order is
the cycle order.

``modalities`` from a model entry becomes the model's ``capabilities`` block
(``input``/``output``) with ``tools`` always true. The block is emitted even
for a model without declared modalities, because OpenCode's fallback for a
model it cannot look up assumes image input — writing text-only explicitly is
what keeps such a model text-only. Values use the config schema's modality
enum and are validated locally (a bad value makes OpenCode reject the whole
file). Declaring a modality the upstream doesn't actually accept turns the
silent fallback into a hard request error, so entries opt in per model.

``display_name`` renders as the model-level ``name``, which is only the picker
label: OpenCode falls back to the model key when it is absent, and both the
key and ``api.id`` stay the upstream id. A ``display_name`` equal to that id
is skipped rather than repeated.
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from model_switch import paths
from model_switch.drivers._atomic import atomic_write_json, read_json
from model_switch.store import ModelEntry as Model
from model_switch.store import provider_group_key


PROVIDER_ID = "yzr"

# The provider namespace model-switch owns (grouped `yzr-<slug>` blocks plus
# the legacy forms `_is_owned_provider` reclaims).
PROVIDER_PREFIX = "yzr-"

# The V2 providers key and the V1 one this driver used to write. Owned blocks
# are reclaimed from both; only the V2 key is written.
PROVIDER_KEY = "providers"
LEGACY_PROVIDER_KEY = "provider"

# Without `package`, OpenCode reports "Provider not found" and silently falls
# back to its default model.
PACKAGE = "@opencode/ai/providers/anthropic"

# baseURL must carry a version segment; see the module docstring.
_VERSION_SEGMENT = re.compile(r"/v\d+$")

# Default max-output cap paired with every emitted ``limit.context``, because
# OpenCode's schema forces ``context`` and ``output`` to appear together while
# model-switch tracks only context. Aligns with OpenCode's bundled
# models.dev MiniMax-M3; upgrade to a per-model field when output must vary.
_DEFAULT_MAX_OUTPUT = 131_072

# OpenCode's modality enum for the capabilities block; this tuple also orders
# the values in rendered messages.
_MODALITY_VALUES = ("text", "audio", "image", "video", "pdf")


def _base_url_for_ai_sdk(base_url):
    """Render ``model.base_url`` into the baseURL the package expects."""
    base = base_url.rstrip("/")
    if not _VERSION_SEGMENT.search(base):
        base += "/v1"
    return base


def _render_capabilities(model: Model) -> Dict[str, Any]:
    """Render the model-level ``capabilities`` block.

    ``tools`` is always true (every model-switch entry is an agent model), and
    the block is always emitted: OpenCode's fallback for an unknown model
    claims image input, while an undeclared ``modalities`` here means
    text-only. ``model.extra['modalities']`` is validated like the config
    schema would — unknown keys, unknown modality names and empty lists fail
    locally, because OpenCode rejects the whole config file on a schema
    violation, taking every model down, not just this one.
    """
    inputs = ["text"]
    outputs = ["text"]
    value = model.extra.get("modalities")
    if value is not None:
        where = "model {!r}".format(model.model_id)
        if not isinstance(value, dict):
            raise ValueError(
                "{}: modalities must be a table like "
                '{{ input = ["text"], output = ["text"] }}, got {}.'.format(
                    where, type(value).__name__))
        if not value:
            raise ValueError(
                "{}: modalities must not be empty (omit the key "
                "instead).".format(where))
        for key, items in value.items():
            if key not in ("input", "output"):
                raise ValueError(
                    "{}: modalities.{!r} is not a known key (allowed: input, "
                    "output).".format(where, key))
            if not isinstance(items, list) or not items:
                raise ValueError(
                    "{}: modalities.{} must be a non-empty list (omit the key "
                    "instead).".format(where, key))
            for item in items:
                if item not in _MODALITY_VALUES:
                    raise ValueError(
                        "{}: modalities.{} contains {!r} (allowed: {}).".format(
                            where, key, item, ", ".join(_MODALITY_VALUES)))
        inputs = list(value.get("input") or ["text"])
        outputs = list(value.get("output") or ["text"])
    return {"tools": True, "input": inputs, "output": outputs}


def _render_model_entry(model: Model) -> Dict[str, Any]:
    """Render the per-model object stored under ``providers.<id>.models``.

    A ``variants`` table becomes the V2 array shape, one entry per declared
    tier in declaration order (which is the cycle order OpenCode offers);
    its values were shape-checked by `variants.expand` and are passed through
    as the entry's ``settings``. ``capabilities`` is rendered by
    `_render_capabilities`; ``display_name`` becomes the model-level ``name``
    unless it repeats the upstream id; ``limit`` appears only when
    ``context_window`` is known. With nothing set this returns just the
    capabilities block — every model declares text-only unless told otherwise.
    """
    entry: Dict[str, Any] = {}
    variants = model.extra.get("variants")
    if variants:
        entry["variants"] = [
            {"id": tier, "settings": payload}
            for tier, payload in variants.items()
        ]
    entry["capabilities"] = _render_capabilities(model)
    display_name = model.extra.get("display_name")
    if display_name is not None:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError(
                "model {!r}: display_name must be a non-empty string, got "
                "{!r}.".format(model.model_id, display_name))
        if display_name != model.name:
            entry["name"] = display_name
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


# Group key: (declared provider name or None, base_url, api_key) — the shape
# `store.provider_group_key` returns. A provider block is shareable exactly
# when all three match.
_GroupKey = Tuple[Optional[str], str, str]

_PROVIDER_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


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
    base_url changes. Groups are keyed by ``(declared, base_url, api_key)``
    (``store.provider_group_key``) — baseURL/apiKey are provider-level, so a
    block is shareable exactly when both match. Declared names win collisions
    with derived slugs; leftovers get ``-2``/``-3`` suffixes in sorted order,
    so repeated renders are byte-stable. All models declaring one name must
    share one upstream — a partial key rotation fails loudly instead of
    silently splitting the group in two; `_validate_unique_model_names`
    covers the other collision.
    """
    groups: Dict[_GroupKey, List[Model]] = {}
    for m in models:
        groups.setdefault(provider_group_key(m), []).append(m)
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

    _validate_unique_model_names(groups)
    return groups, pid_by_key


def _validate_unique_model_names(groups: Dict[_GroupKey, List[Model]]) -> None:
    """Reject two models sharing one name within a group.

    They would overwrite each other in the provider's ``models`` map, so the
    collision fails loudly instead of silently dropping a model.
    """
    for members in groups.values():
        seen = set()
        for m in members:
            if m.name in seen:
                raise ValueError(
                    "model names must be unique within one upstream: "
                    "{!r} is claimed by multiple models on {}".format(
                        m.name, m.base_url))
            seen.add(m.name)


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


def _without_owned(block: Any) -> Dict[str, Any]:
    """Return `block` minus the ``yzr-*`` providers model-switch owns.

    A missing or non-dict block reads as empty; foreign entries pass through
    untouched so a user's own providers survive every reconcile.
    """
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if not _is_owned_provider(k)}


class OpenCodeDriver:
    name = "opencode"
    supports_catalog = True

    def __init__(self, settings_path: Path = None) -> None:
        if settings_path is None:
            settings_path = paths.opencode_config_file()
        self.settings_path = settings_path

    def read(self) -> dict:
        return read_json(self.settings_path)

    def validate(self, models: List[Model], active: Model = None) -> None:
        """Render everything a write would render, without writing.

        Raises the same `ValueError` the write path would (bad modalities /
        display names, conflicting provider declarations, duplicate names),
        so `model use` can fail before any driver's config is touched.
        Optional protocol method — see `drivers.base.AgentDriver`.
        """
        if active is not None and not active.api_key:
            raise ValueError(
                "model {!r} has no api_key in models.toml.".format(active.model_id)
            )
        keyed = [m for m in models if m.api_key]
        _provider_layout(keyed)
        for m in keyed:
            _render_model_entry(m)

    def apply(self, models: List[Model], active: Model) -> None:
        """Write the full catalog into the OpenCode config, defaulting to `active`."""
        if not active.api_key:
            raise ValueError(
                "model {!r} has no api_key in models.toml.".format(active.model_id)
            )
        self.sync_catalog(models, active_id=active.model_id, create=True)

    def sync_catalog(self, models: List[Model], active_id: str = None,
                     create: bool = False) -> None:
        """Mirror `models` into the ``yzr-*`` provider namespace.

        Reconciliation, deletion and pointer rules are the module docstring's;
        `create=False` (the catalog-sync path from add/remove/import) leaves a
        missing config file alone — no file is created out of thin air. The
        render is validated right before the write, so a skipped sync (no
        config file) never fails on entries OpenCode would not see.
        """
        if not create and not self.settings_path.exists():
            return

        self.validate(models)
        config = self.read()
        self._compose(config, models, active_id)
        atomic_write_json(self.settings_path, config)

    def _compose(self, config: dict, models: List[Model],
                 active_id: Optional[str]) -> None:
        """Update `config` in place with the mirrored ``yzr-*`` namespace.

        Pure computation: nothing is read or written here, so `validate`
        can run the same rendering the write path runs (see `apply`). Owned
        blocks are stripped from both the V2 ``providers`` key and the legacy
        V1 ``provider`` key — a pre-V2 file is migrated by the same call, and
        the legacy key is dropped entirely once nothing is left in it.
        """
        legacy = _without_owned(config.get(LEGACY_PROVIDER_KEY))
        if legacy:
            config[LEGACY_PROVIDER_KEY] = legacy
        else:
            config.pop(LEGACY_PROVIDER_KEY, None)

        providers = _without_owned(config.get(PROVIDER_KEY))
        keyed = [m for m in models if m.api_key]  # no key → unusable block
        pid_by_key, groups, refs = _provider_layout(keyed)
        for key in sorted(groups, key=lambda k: pid_by_key[k]):
            _declared, base_url, api_key = key
            members = sorted(groups[key], key=lambda m: m.name)
            providers[pid_by_key[key]] = {
                "package": PACKAGE,
                "name": pid_by_key[key],
                "settings": {
                    "baseURL": _base_url_for_ai_sdk(base_url),
                    "apiKey": api_key,
                },
                "models": {m.name: _render_model_entry(m) for m in members},
            }

        config[PROVIDER_KEY] = providers
        default = self._resolve_default(config.get("model"), keyed, refs,
                                        active_id)
        if default is None:
            config.pop("model", None)
        else:
            config["model"] = default

    def _resolve_default(self, current: Optional[str], models: List[Model],
                         refs: Dict[str, str],
                         active_id: Optional[str]) -> Optional[str]:
        """Pick `config["model"]`: active_id wins, else the current pointer
        stays if it's ours (`yzr-*`) and still names a synced provider; ours
        but vanished falls to the first remaining model, then None (drop the
        key). A foreign pointer (or an absent key) is never touched — moving
        the default is the `model use` path's job, and sync_catalog must not
        hijack a default the user set themselves.

        ``refs`` is the caller's `_provider_layout` result, passed in so the
        grouping runs once per sync.
        """
        if not models:
            return None
        if active_id is not None and active_id in refs:
            return refs[active_id]
        if current:
            if current in refs.values():
                return current
            if _is_owned_provider(current.split("/", 1)[0]):
                # Ours but vanished — fall to the first remaining model.
                return refs[models[0].model_id]
            # Foreign reference — not ours to move.
            return current
        # No default key — don't conjure one; `model use` sets it.
        return None

    def current(self) -> dict:
        config = self.read()
        if not config:
            return {}
        out = {"model": config.get("model", "")}
        owned = set()
        for key in (PROVIDER_KEY, LEGACY_PROVIDER_KEY):
            block = config.get(key)
            if isinstance(block, dict):
                owned.update(k for k in block if _is_owned_provider(k))
        if owned:
            out["catalog"] = ", ".join(sorted(owned))
        return out


# NOTE: Do NOT auto-register at import time — see `cli._ensure_default_registered`.
