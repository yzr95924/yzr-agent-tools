"""Derive OpenCode-compatible model fields from OpenCode's catalog cache.

Consistency with OpenCode's built-in catalog means copying the declarations
OpenCode itself would use for the same upstream model — same source, same
values. This module reads OpenCode's local models.dev snapshot
(``~/.cache/opencode/models.json``, refreshed by OpenCode about hourly); it
never touches the network. A missing cache is not an error: the caller falls
back to manual values, because auto-fill is an assist, never a requirement.

Disambiguation is deliberately conservative. One model name appears under
many providers with conflicting declarations, so candidates are narrowed by
the ``base_url`` host first. When that leaves several candidates their
derived fields must agree, otherwise the caller has to pin one with
``--catalog-provider`` — nothing is ever guessed, because a wrong pick
silently mis-configures reasoning tiers.

Fields derived (see `derive`): ``context_window`` (from ``limit.context``),
``reasoning``, ``variants`` (``toggle`` → ``off`` plus one tier per declared
effort value) and ``modalities``. Budget ladders are never invented: a model
declaring only ``budget_tokens`` gets no tiers.

Known limits, by design:

- Catalog entries describe each provider's *declared* endpoint (its ``npm``
  SDK, usually the OpenAI-compatible API), while model-switch connects over
  the Anthropic-compatible path. Tier *names* are family-wide; the wire
  shape is the driver's translation, not the catalog's.
- Acceptance is not effectiveness: an upstream may accept a tier and clamp
  it silently. Only vendor docs plus task-level observation can tell.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from model_switch import paths

# Input modalities worth declaring. OpenCode itself accepts text/audio/image/
# video/pdf, but the Anthropic Messages wire format has no video/audio part,
# so declaring them would only make the gate pass something the upstream
# rejects. A catalog entry claiming text-only needs no declaration at all:
# undeclared parts are already blocked, which is the same outcome.
_SUPPORTED_INPUT = ("text", "image", "pdf")

# Effort values meaning "barely/no thinking"; the `off` toggle covers that
# better, so they never become tiers (same rule OpenCode's own derivation
# applies when picking a default).
_SKIP_EFFORT_TIERS = ("none", "minimal")


@dataclass
class Candidate:
    """One catalog provider entry that has this model name."""

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


def host_of(url: str) -> str:
    """The netloc of a URL, lowercased (``""`` when unparseable)."""
    return urlsplit(str(url or "")).netloc.lower()


def load_cache(path: Optional[Path] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """Read the catalog cache: ``(data-or-None, human description)``.

    Never raises and never fetches anything — the only failure modes are a
    missing or unreadable local file, both reported in the description.
    """
    p = Path(path) if path is not None else paths.catalog_cache_file()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return None, "no catalog cache at {} (OpenCode builds it on first run)".format(p)
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "unreadable catalog cache at {}".format(p)
    if not isinstance(data, dict):
        return None, "unexpected catalog cache shape at {}".format(p)
    stamp = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return data, "{} (updated {})".format(p, stamp)


def candidates(data: Dict[str, Any], model_name: str, base_url: str) -> List[Candidate]:
    """Every provider entry carrying ``model_name``, deterministically sorted.

    ``host_match`` marks entries whose declared API host equals the host of
    our ``base_url`` — the one signal that identifies *our* upstream among
    the dozens of providers that share a model name. Paths may differ (we
    connect over the Anthropic-compatible path, the catalog records the
    OpenAI-compatible one); the host is what identifies the vendor.
    """
    host = host_of(base_url)
    out: List[Candidate] = []
    for provider in sorted(data):
        entry_map = data.get(provider) or {}
        models = entry_map.get("models") or {}
        entry = models.get(model_name)
        if not isinstance(entry, dict):
            continue
        api = str(entry_map.get("api") or "")
        out.append(Candidate(
            provider=provider,
            api=api,
            entry=entry,
            # Substring (not netloc equality): catalog APIs sometimes carry
            # ports or bare hosts, and a host match must not be missed.
            host_match=bool(host and host in host_of(api)),
        ))
    return out


def derive(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Map one catalog entry to the fields model-switch writes.

    Returns ``context_window`` (``limit.context``), ``reasoning`` (any
    ``reasoning_options`` declared), ``variants`` (``{}`` when the entry
    declares none we can honor) and ``modalities`` (``None`` when the entry
    is text-only — declaring that adds nothing).
    """
    opts = [o for o in (entry.get("reasoning_options") or []) if isinstance(o, dict)]
    toggle = False
    effort_values: List[str] = []
    for o in opts:
        kind = o.get("type")
        if kind == "toggle":
            toggle = True
        elif kind == "effort" and not effort_values:
            effort_values = [v for v in (o.get("values") or []) if isinstance(v, str)]

    variants: Dict[str, Any] = {}
    if toggle:
        variants["off"] = {"thinking": {"type": "disabled"}}
    for v in effort_values:
        if v in _SKIP_EFFORT_TIERS:
            continue
        variants[v] = {"effort": v, "thinking": {"type": "adaptive"}}

    limit = entry.get("limit") or {}
    context = limit.get("context") if isinstance(limit, dict) else None
    if not (isinstance(context, int) and context > 0):
        context = None

    mods = entry.get("modalities") or {}
    inputs = [m for m in (mods.get("input") or []) if m in _SUPPORTED_INPUT]
    modalities = None
    if inputs and inputs != ["text"]:
        outputs = [m for m in (mods.get("output") or []) if isinstance(m, str)]
        modalities = {"input": inputs, "output": outputs or ["text"]}

    return {
        "context_window": context,
        "reasoning": bool(opts),
        "variants": variants,
        "modalities": modalities,
    }


def budget_only(entry: Dict[str, Any]) -> bool:
    """True when the entry declares reasoning but no toggle/effort tiers."""
    opts = [o for o in (entry.get("reasoning_options") or []) if isinstance(o, dict)]
    if not opts:
        return False
    return not any(o.get("type") in ("toggle", "effort") for o in opts)


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
    if all(derive(c.entry) == derive(first.entry) for c in matches[1:]):
        return Pick(first, "host match, {} candidates agree".format(len(matches)),
                    matches[1:])
    return Pick(None,
                "conflicting declarations across {} host-matching providers".format(
                    len(matches)),
                matches)
