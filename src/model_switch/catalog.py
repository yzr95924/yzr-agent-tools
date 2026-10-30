"""Derive OpenCode-compatible model fields from OpenCode's catalog cache.

Consistency with OpenCode's built-in catalog means copying the declarations
OpenCode itself would use for the same upstream model — same source, same
values. This module reads OpenCode's local models.dev snapshot — since
OpenCode 2.0 a SQLite database at
``$XDG_DATA_HOME/opencode/opencode.db`` (default
``~/.local/share/opencode/opencode.db``), refreshed by OpenCode about
hourly; it never touches the network. A missing cache is not an error: the
caller falls back to manual values, because auto-fill is an assist, never a
requirement.

Since OpenCode 2.2 the snapshot (kv key ``models-dev:v2:catalog``) stores the
V2 layout: every model entry carries its own ``api`` routes (``messages`` is
the Anthropic-compatible one this tool connects over), a
``capabilities.reasoning`` block, and MIME-typed ``modalities``. Modalities
are collapsed to the coarse forms OpenCode itself uses when it loads the
catalog (``image/jpeg`` → ``image``, ``application/pdf`` → ``pdf``); writing
the raw MIME would actually break OpenCode's input gate, which compares
``startswith(modality)`` and would not match ``application/pdf`` against
``pdf``.

Disambiguation is deliberately conservative. One model name appears under
many providers with conflicting declarations, so candidates are narrowed by
the ``base_url`` host: a candidate matches when any of its ``api`` routes
declares exactly that host (netloc equality — a substring rule would let
``dashscope.example.com`` match ``coding.dashscope.example.com``, a different
product on a different endpoint). When that leaves several candidates their
derived fields must agree, otherwise the caller has to pin one with
``--catalog-provider`` — nothing is ever guessed, because a wrong pick
silently mis-configures reasoning tiers. Entries whose ``type`` is not
``chat`` (the snapshot also carries ``image`` and ``decision`` models) are
ignored: OpenCode offers only chat models for sessions.

Fields derived (see `derive`): ``context_window`` (from ``limit.context``),
``variants`` (one tier per declared ``capabilities.reasoning.effort`` value,
plus ``none`` translated to a thinking-off tier when declared), ``modalities``
and ``display_name`` (the entry's human-readable ``name``). A ``toggle``
option adds no tier of its own, mirroring OpenCode's own derivation; budget
ladders are never invented, so a model declaring only ``budget`` gets no
tiers.

Known limits, by design:

- Catalog entries describe each provider's *declared* endpoints (an
  OpenAI-compatible route and, for most vendors, an Anthropic-compatible
  one); model-switch connects over the Anthropic-compatible one. Tier *names*
  follow OpenCode; bodies are the driver's translation of them: an effort
  tier becomes ``{effort = <name>, thinking = {type = "adaptive"}}``, and
  ``none`` — which the Anthropic effort enum has no room for — becomes
  ``{thinking = {type = "disabled"}}``, the same shape OpenCode gives
  ``none`` on Anthropic-style adapters and the one Kimi's docs define for it.
- A ``toggle`` option is ignored when effort values exist, matching
  OpenCode's own derivation (it emits effort tiers only, dropping ``toggle``).
  A model declaring *only* a toggle therefore derives no tiers — declare one
  by hand if the upstream needs it.
- Acceptance is not effectiveness: an upstream may accept a tier and clamp it
  silently. Only vendor docs plus task-level observation can tell.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from model_switch import paths

# Input modalities worth declaring, as the coarse forms OpenCode's config and
# input gate understand. The Anthropic Messages wire format has no video or
# audio part, so declaring them would only make the gate pass something the
# upstream rejects. A text-only entry needs no declaration at all: undeclared
# parts are already blocked, which is the same outcome.
_SUPPORTED_INPUT = ("text", "image", "pdf")

# Output modalities worth declaring: the Anthropic Messages path produces
# text, full stop. Entries also describe OpenAI-compatible endpoints, where a
# TTS model may declare audio output; mirroring that would advertise an
# output this path can never return.
_SUPPORTED_OUTPUT = ("text",)

# Effort values that never become an ``effort`` tier. ``none`` is not here:
# it becomes a thinking-off tier instead (see `derive`). ``minimal`` is: it
# means "a little thinking", not "no thinking", and the Anthropic effort enum
# is low|medium|high|xhigh|max — clamping it to ``low`` would lie about the
# tier name, so it is skipped.
_SKIP_EFFORT_TIERS = ("minimal",)


@dataclass
class Candidate:
    """One catalog provider entry that has this model name.

    ``api`` is the entry's representative declared base_url (the
    Anthropic-compatible route when present) — display only, for pin hints.
    """

    provider: str
    api: str
    entry: Dict[str, Any]
    host_match: bool


@dataclass
class Pick:
    """The outcome of narrowing candidates to one provider."""

    candidate: Optional[Candidate]
    reason: str
    alternatives: List[Candidate] = field(default_factory=list)


@dataclass
class Row:
    """One catalog model, flattened for the interactive picker."""

    provider: str
    model: str
    entry: Dict[str, Any]


def host_of(url: str) -> str:
    """The netloc of a URL, lowercased (``""`` when unparseable).

    Tolerates the bare-host base_urls models.dev sometimes declares
    (``api.moonshot.ai`` with no scheme): urlsplit would treat that as a
    path, so a scheme-less value is re-parsed as protocol-relative.
    """
    raw = str(url or "")
    netloc = urlsplit(raw).netloc.lower()
    if not netloc and "://" not in raw:
        netloc = urlsplit("//" + raw).netloc.lower()
    return netloc


# OpenCode keeps the models.dev snapshot in its SQLite database: table ``kv``,
# this key, value = JSON envelope {updatedAt, digest, body} where ``body``
# carries the provider map as a JSON string. (A sibling ``:meta`` row repeats
# the timestamps; the envelope already has everything needed here.)
_CATALOG_KV_KEY = "models-dev:v2:catalog"


def load_cache(path: Optional[Path] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """Read the catalog cache: ``(data-or-None, human description)``.

    ``path`` is an OpenCode database file (default
    `paths.catalog_db_file`). Never raises and never fetches anything — the
    failure modes are all local (missing db, missing snapshot row,
    unreadable content), both reported in the description. The database is
    opened read-only: model-switch never writes it.
    """
    p = Path(path) if path is not None else paths.catalog_db_file()
    if not p.exists():
        return None, "no catalog cache at {} (OpenCode builds it on first run)".format(p)
    try:
        con = sqlite3.connect(p.absolute().as_uri() + "?mode=ro", uri=True)
    except (OSError, ValueError, sqlite3.Error):
        return None, "unreadable catalog cache at {}".format(p)
    try:
        try:
            row = con.execute("SELECT value FROM kv WHERE key = ?",
                              (_CATALOG_KV_KEY,)).fetchone()
        except sqlite3.Error:
            return None, "unreadable catalog cache at {}".format(p)
    finally:
        con.close()
    if row is None:
        return None, "no catalog cache at {} (OpenCode builds it on first run)".format(p)
    try:
        envelope = json.loads(row[0])
    except (ValueError, TypeError):
        return None, "unreadable catalog cache at {}".format(p)
    if not isinstance(envelope, dict):
        return None, "unexpected catalog cache shape at {}".format(p)
    try:
        data = json.loads(envelope["body"])
    except (ValueError, TypeError, KeyError):
        return None, "unreadable catalog cache at {}".format(p)
    if not isinstance(data, dict):
        return None, "unexpected catalog cache shape at {}".format(p)
    updated = envelope.get("updatedAt")
    ts = (updated / 1000.0
          if isinstance(updated, (int, float)) and updated > 0
          else p.stat().st_mtime)
    stamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    return data, "{} (updated {})".format(p, stamp)


def _api_base_urls(entry: Dict[str, Any]) -> Dict[str, str]:
    """The entry's ``api`` routes as ``{family: base_url}``."""
    routes = entry.get("api")
    if not isinstance(routes, dict):
        return {}
    return {family: route["base_url"]
            for family, route in routes.items()
            if isinstance(route, dict) and isinstance(route.get("base_url"), str)}


def _is_chat(entry: Dict[str, Any]) -> bool:
    """True unless the entry declares a non-chat ``type``.

    The snapshot also carries ``image`` and ``decision`` models; OpenCode
    offers only chat models for sessions, so anything else is noise here.
    """
    return str(entry.get("type") or "chat") == "chat"


def _display_api(base_urls: Dict[str, str]) -> str:
    """The base_url pin hints show: the Anthropic-compatible route when
    declared (it is the path model-switch connects over), else the first
    family alphabetically."""
    for family in ("messages", "chat-completions"):
        if family in base_urls:
            return base_urls[family]
    return base_urls[sorted(base_urls)[0]] if base_urls else ""


def candidates(data: Dict[str, Any], model_name: str, base_url: str) -> List[Candidate]:
    """Every provider entry carrying ``model_name``, deterministically sorted.

    ``host_match`` marks entries one of whose declared ``api`` routes has
    exactly our ``base_url`` host — the one signal that identifies *our*
    upstream among the dozens of providers that share a model name. Paths may
    differ per family; the host is what identifies the vendor, and equality
    (not substring) keeps ``coding.dashscope.example.com`` from matching
    ``dashscope.example.com``.
    """
    host = host_of(base_url)
    out: List[Candidate] = []
    for provider in sorted(data):
        entry_map = data.get(provider) or {}
        models = entry_map.get("models") or {}
        entry = models.get(model_name)
        if not isinstance(entry, dict) or not _is_chat(entry):
            continue
        base_urls = _api_base_urls(entry)
        out.append(Candidate(
            provider=provider,
            api=_display_api(base_urls),
            entry=entry,
            host_match=bool(host) and host in
            set(host_of(u) for u in base_urls.values()),
        ))
    return out


def search(data: Dict[str, Any], query: str = "",
           host: Optional[str] = None) -> List[Row]:
    """Every catalog chat model matching ``query``, flattened for a menu.

    Matching is case-insensitive and token-wise (all whitespace-separated
    tokens must appear somewhere in ``provider id / provider display name /
    model id / model display name``). ``host`` restricts to entries with an
    ``api`` route declaring exactly that host — the same equality rule as
    `candidates`, and the reason the picker can offer "models on your
    upstream" without asking which provider is meant.

    Rows are sorted by ``(provider, model)`` so menus are deterministic.
    Nothing is capped here: the caller truncates the display and reports how
    many rows were hidden, and the true count drives its "refine" hint.
    """
    tokens = [t for t in (query or "").lower().split() if t]
    wanted_host = (host or "").lower()
    out: List[Row] = []
    for provider in sorted(data):
        entry_map = data.get(provider) or {}
        if not isinstance(entry_map, dict):
            continue
        provider_name = str(entry_map.get("name") or provider)
        models = entry_map.get("models") or {}
        if not isinstance(models, dict):
            continue
        for model_id in sorted(models):
            entry = models.get(model_id)
            if not isinstance(entry, dict) or not _is_chat(entry):
                continue
            if wanted_host:
                hosts = set(host_of(u) for u in _api_base_urls(entry).values())
                if wanted_host not in hosts:
                    continue
            if tokens:
                haystack = " ".join((
                    provider, provider_name, model_id,
                    str(entry.get("name") or ""),
                )).lower()
                if not all(t in haystack for t in tokens):
                    continue
            out.append(Row(provider, model_id, entry))
    return out


def _reasoning(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The entry's ``capabilities.reasoning`` block, when it is a table."""
    capabilities = entry.get("capabilities")
    reasoning = (capabilities.get("reasoning")
                 if isinstance(capabilities, dict) else None)
    return reasoning if isinstance(reasoning, dict) else {}


def derive(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Map one catalog entry to the fields model-switch writes.

    Returns ``context_window`` (``limit.context``), ``variants`` (``{}`` when
    the entry declares none we can honor), ``modalities`` (``None`` when the
    entry is text-only — declaring that adds nothing) and ``display_name``
    (the entry's human-readable ``name``, or ``None``).
    """
    limit = entry.get("limit") or {}
    context = limit.get("context") if isinstance(limit, dict) else None
    if not (isinstance(context, int) and context > 0):
        context = None
    return {
        "context_window": context,
        "variants": _derive_variants(entry),
        "modalities": _derive_modalities(entry),
        "display_name": _derive_display_name(entry),
    }


def _derive_variants(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The effort tiers the entry yields, in declaration order.

    Each ``capabilities.reasoning.effort`` value becomes a tier; ``none``
    becomes a thinking-off tier (see ``_SKIP_EFFORT_TIERS``), and ``minimal``
    is skipped because the Anthropic effort enum has no room for it. A
    ``toggle`` adds nothing: OpenCode's own derivation emits effort tiers
    only when effort values exist, so keeping the toggle would expose a cycle
    OpenCode itself does not. Budget ladders are never invented.
    """
    variants: Dict[str, Any] = {}
    for value in (_reasoning(entry).get("effort") or []):
        if not isinstance(value, str):
            continue
        if value == "none":
            variants[value] = {"thinking": {"type": "disabled"}}
        elif value not in _SKIP_EFFORT_TIERS:
            variants[value] = {"effort": value, "thinking": {"type": "adaptive"}}
    return variants


def _coarse_modality(token: Any) -> Optional[str]:
    """One catalog modality token as the coarse form OpenCode compares.

    Mirrors OpenCode's own loader: ``text`` and ``text/*`` → ``text``,
    ``image`` and ``image/*`` → ``image``, ``application/pdf`` → ``pdf``
    (and the bare legacy forms pass through). Everything else — audio,
    video, unknown — has no coarse form this path can honor. The ``pdf``
    mapping is load-bearing: OpenCode's input gate matches
    ``startswith("pdf")``, which the raw MIME would fail.
    """
    token = str(token)
    if token in _SUPPORTED_INPUT:
        return token
    if token == "application/pdf":
        return "pdf"
    major = token.split("/", 1)[0]
    if major in ("text", "image"):
        return major
    return None


def _derive_modalities(entry: Dict[str, Any]) -> Optional[Dict[str, List[str]]]:
    """Input/output modalities, or ``None`` when text-only.

    Catalog MIME types are collapsed to the coarse modalities (see
    `_coarse_modality`) and deduplicated; text-only needs no declaration —
    undeclared parts are already blocked, which is the same outcome.
    ``video``/``audio`` inputs and any non-text output are dropped: the
    Anthropic Messages path has no such parts.
    """
    mods = entry.get("modalities") or {}
    inputs: List[str] = []
    for token in (mods.get("input") or []):
        coarse = _coarse_modality(token)
        if coarse in _SUPPORTED_INPUT and coarse not in inputs:
            inputs.append(coarse)
    if not inputs or inputs == ["text"]:
        return None
    outputs = [c for c in map(_coarse_modality, mods.get("output") or [])
               if c in _SUPPORTED_OUTPUT]
    return {"input": inputs, "output": outputs or ["text"]}


def _derive_display_name(entry: Dict[str, Any]) -> Optional[str]:
    """The entry's human-readable name, stripped; ``None`` when blank."""
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def no_tiers_declared(entry: Dict[str, Any]) -> bool:
    """True when the entry declares reasoning but none of it yields tiers.

    Delegates to `derive` so the two can never disagree about what makes a
    tier — budget-only entries, bare toggles and all-skippable effort lists
    are exactly the cases whose ``variants`` come back empty. An explicit
    ``supported: false`` declares the *absence* of reasoning, not options.
    """
    reasoning = _reasoning(entry)
    return (bool(reasoning)
            and reasoning.get("supported") is not False
            and not derive(entry)["variants"])


def pick(cands: List[Candidate], pin: Optional[str] = None) -> Pick:
    """Narrow candidates to one provider, or refuse with a reason.

    ``pin`` (``--catalog-provider``) always wins and must exist. Otherwise
    only host-matching candidates count; several are acceptable only when
    the fields they would produce are identical (then the alphabetically
    first is picked, deterministically). Conflicting declarations are never
    resolved by heuristics — the report stays and the user pins one.
    """
    if pin is not None:
        for c in cands:
            if c.provider == pin:
                return Pick(c, "pinned provider {!r}".format(pin))
        return Pick(None, "provider {!r} has no entry for this model".format(pin),
                    list(cands))
    if not cands:
        return Pick(None, "no entry under this model name")
    matches = sorted((c for c in cands if c.host_match), key=lambda c: c.provider)
    if not matches:
        return Pick(None, "no candidate api host matches this base_url", list(cands))
    if len(matches) == 1:
        return Pick(matches[0], "host match")
    first = matches[0]
    first_fields = derive(first.entry)
    if all(derive(c.entry) == first_fields for c in matches[1:]):
        return Pick(first, "host match, {} candidates agree".format(len(matches)),
                    matches[1:])
    return Pick(None,
                "conflicting declarations across {} host-matching providers".format(
                    len(matches)),
                matches)
