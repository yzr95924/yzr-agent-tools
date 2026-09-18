"""Probe an upstream endpoint for reasoning (thinking) shape acceptance.

Sends one small request per payload row — never streams, one transport-level
retry — and reports an acceptance matrix: which thinking shapes the gateway
takes (HTTP-level), whether thinking blocks come back, and what the response
usage looks like. Read-only by default; ``--apply`` is the only writing mode
and it only ever touches a ``probe-<model_id>`` preset (atomic write +
``.bak``), never a user preset.

The probe matrix is **catalog-driven**: the models.dev entry that matches the
model (live from ``https://models.opencode.ai/api.json`` or opencode's local cache,
``~/.cache/opencode/models.json``) contributes the candidate shapes — every
declared effort value, and a budget ladder bounded by the declared
``budget_tokens`` min/max. With no catalog entry the legacy fixed matrix runs
(control / disabled / default budget ladder / adaptive / effort low+high).

Caveat the report makes explicit: models.dev entries describe each provider's
*declared* endpoint, which for the coding-plan providers is usually the
OpenAI-compatible API — while model-switch connects over the Anthropic-compatible
one. Tier *names* tend to be family-wide, but the catalog row is an inference,
not a lookup; the probe rows are the only evidence about OUR endpoint.

What the matrix can and cannot tell you:

- CAN: acceptance boundaries (an HTTP 200 proves the shape parses), plus
  error messages, which often name the real constraint (e.g. a budget
  ceiling). It also shows whether a thinking block actually came back.
- CANNOT: the effective budget — a gateway may accept 32768 and silently
  clamp it. That question needs provider docs and task-level observation.
"""
import io
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from model_switch import store
from model_switch._compat import toml_dump
from model_switch.drivers.opencode import _base_url_for_ai_sdk

DEFAULT_BUDGETS = (1024, 4096, 8192, 32768)
TRIVIAL_PROMPT = "Reply with exactly: OK"
PROBE_PRESET_PREFIX = "probe-"
CATALOG_URL = "https://models.opencode.ai/api.json"
CATALOG_CACHE = "~/.cache/opencode/models.json"
CATALOG_LIVE_TIMEOUT = 15
DEFAULT_TIMEOUT = 90
_THINKING_HINTS = ("thinking", "budget", "reasoning", "effort")

# Effort values that mean "barely/no thinking" — not useful as a cycle tier
# (a `disabled` row covers that), so never suggested as presets.
_SKIP_EFFORT_TIERS = ("none", "minimal")

_HTTP_OK_LO = 200
_HTTP_OK_HI = 300


@dataclass
class ProbeResult:
    """One probe row outcome."""

    label: str
    payload: Dict[str, Any]
    status: int
    verdict: str  # accepted | rejected | endpoint-error
    blocks: List[str] = field(default_factory=list)
    out_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    error: str = ""


def _budget_ladder(spec: Dict[str, Any]) -> List[int]:
    """Budget ladder bounded by a catalog ``budget_tokens`` spec.

    The default ladder is clipped to [min, max]; when fewer than two default
    rungs survive (min/max narrower than the defaults), the bounds themselves
    become the ladder.
    """
    lo = max(int(spec.get("min") or 1024), 1024)
    hi = int(spec.get("max") or 32768)
    if hi < lo:
        lo, hi = hi, lo
    ladder = [b for b in DEFAULT_BUDGETS if lo <= b <= hi]
    if len(ladder) < 2:
        ladder = sorted({lo, hi})
    return ladder


def build_rows(entry: Optional[Dict[str, Any]],
               budgets: Optional[Tuple[int, ...]] = None
               ) -> List[Tuple[str, Dict[str, Any], int]]:
    """Build the probe matrix as (label, payload, max_tokens) triples.

    ``entry`` is the selected models.dev model entry (``None`` → legacy fixed
    matrix). An explicit ``budgets`` tuple overrides the budget ladder. When
    the catalog declares effort values, the budget family is skipped — effort
    is the native family and probing budgets alongside would only burn
    requests (unless ``budgets`` is explicit).

    HTTP-level shapes: snake_case ``budget_tokens`` and ``output_config`` —
    this is what the endpoint actually receives (opencode's config-side
    camelCase form is lowered before the request).
    """
    opts = ((entry or {}).get("reasoning_options") or [])
    effort_values = []
    for o in opts:
        if o.get("type") == "effort":
            effort_values = [v for v in (o.get("values") or [])
                             if isinstance(v, str)]
            break
    budget_spec = next(
        (o for o in opts if o.get("type") == "budget_tokens"), None)

    rows: List[Tuple[str, Dict[str, Any], int]] = [
        ("control", {}, 2048),
        ("disabled", {"thinking": {"type": "disabled"}}, 2048),
        ("adaptive", {"thinking": {"type": "adaptive"}}, 4096),
    ]

    if effort_values:
        for v in effort_values:
            rows.append((
                "adaptive-effort-{}".format(v),
                {"thinking": {"type": "adaptive"},
                 "output_config": {"effort": v}},
                4096,
            ))
    elif entry is None:
        # No catalog knowledge at all → discovery mode: probe the two
        # canonical effort points alongside the budget ladder.
        rows.append((
            "adaptive-effort-low",
            {"thinking": {"type": "adaptive"},
             "output_config": {"effort": "low"}},
            4096,
        ))
        rows.append((
            "adaptive-effort-high",
            {"thinking": {"type": "adaptive"},
             "output_config": {"effort": "high"}},
            4096,
        ))

    if budgets is not None:
        ladder = [b for b in budgets if b >= 1024] or list(budgets)
    elif effort_values:
        ladder = []  # effort is the declared family; budgets would be noise
    elif budget_spec is not None:
        ladder = _budget_ladder(budget_spec)
    elif entry is None:
        ladder = list(DEFAULT_BUDGETS)
    else:
        ladder = []  # catalog says toggle-only; `disabled` covers it

    for b in ladder:
        rows.append((
            "budget-{}".format(b),
            {"thinking": {"type": "enabled", "budget_tokens": b}},
            b + 2048,
        ))
    return rows


def _verdict(status: int, error_text: str) -> str:
    if _HTTP_OK_LO <= status < _HTTP_OK_HI:
        return "accepted"
    if any(h in error_text.lower() for h in _THINKING_HINTS):
        return "rejected"
    return "endpoint-error"


def _default_sender(
    url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int
) -> Tuple[int, Any]:
    """POST JSON and return (status, parsed-body-or-text). Stdlib only."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def _default_fetcher(url: str, timeout: int) -> Any:
    """GET JSON from `url`; raises on any failure. Injectable for tests.

    Sends an explicit User-Agent: models.opencode.ai 403s the stdlib's
    default ``Python-urllib/x.y`` agent while accepting anything else.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "model-switch"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_catalog(source: str = "auto",
                 catalog_path: Optional[str] = None,
                 fetcher: Optional[Callable[[str, int], Any]] = None,
                 live_timeout: int = CATALOG_LIVE_TIMEOUT
                 ) -> Tuple[Optional[Dict[str, Any]], str]:
    """Load the models.dev catalog, layered: live fetch / local cache.

    Returns ``(data-or-None, human description)``. ``source``:

    - ``live``  — fetch ``CATALOG_URL`` only; None on failure.
    - ``cache`` — read the opencode cache only; None when missing/broken.
    - ``auto``  — try live, fall back to cache (the default).
    """
    fetch = fetcher or _default_fetcher
    path = Path(os.path.expanduser(catalog_path or CATALOG_CACHE))

    def _cache() -> Tuple[Optional[Dict[str, Any]], str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, "none (no readable cache at {})".format(path)
        ts = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        return data, "cache ({}, mtime {})".format(path, ts)

    if source in ("live", "auto"):
        try:
            data = fetch(CATALOG_URL, live_timeout)
            return data, "live ({})".format(CATALOG_URL)
        except Exception:
            if source == "live":
                return None, "none (live fetch failed, cache not consulted)"
    elif source != "cache":
        raise ValueError("catalog source must be auto|live|cache, got %r" % source)
    return _cache()


def _candidate_sort_key(m: Dict[str, Any]) -> Tuple:
    """Deterministic candidate ordering.

    host-matched first, then entries declaring actionable shapes (effort or
    budget) over toggle-only, then richer declarations, then provider id —
    so a name present under many providers always resolves the same way.
    """
    opts = m.get("reasoning_options") or []
    actionable = any(o.get("type") in ("effort", "budget_tokens") for o in opts)
    return (not m.get("host_match"), not actionable, -len(opts), m.get("provider", ""))


def lookup_catalog(
    model: store.ModelEntry,
    catalog_path: Optional[str] = None,
    catalog_data: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Find catalog entries whose model key equals ``model.name``.

    Returns a list of dicts (provider, api, reasoning_options, limit,
    host_match), best entry first. ``provider`` pins the lookup to one
    models.dev provider id (the multi-candidate ambiguity is real: the same
    model name appears under dozens of providers with conflicting
    ``reasoning_options``). Empty list when no data / no match / pinned
    provider unknown.
    """
    if catalog_data is None:
        data, _desc = load_catalog("cache", catalog_path=catalog_path)
    else:
        data = catalog_data
    if not isinstance(data, dict):
        return []

    host = model.base_url.split("//")[-1].split("/")[0]
    matches: List[Dict[str, Any]] = []
    for prov, p in data.items():
        models = (p or {}).get("models") or {}
        entry = models.get(model.name)
        if not entry:
            continue
        api = str(p.get("api") or "")
        matches.append({
            "provider": prov,
            "api": api,
            "reasoning_options": entry.get("reasoning_options"),
            "limit": entry.get("limit"),
            "host_match": bool(host and host in api),
        })
    if provider is not None:
        matches = [m for m in matches if m["provider"] == provider]
    matches.sort(key=_candidate_sort_key)
    return matches


def probe(
    model: store.ModelEntry,
    budgets: Optional[Tuple[int, ...]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    sender: Optional[Callable[..., Tuple[int, Any]]] = None,
    entry: Optional[Dict[str, Any]] = None,
) -> List[ProbeResult]:
    """Run the probe matrix against ``model``'s endpoint.

    ``sender`` is injectable for tests; the default is a stdlib HTTP POST.
    ``entry`` is the selected catalog entry driving the matrix (see
    `build_rows`); ``None`` runs the legacy fixed matrix.
    """
    send = sender or _default_sender
    url = _base_url_for_ai_sdk(model.base_url) + "/messages"
    headers = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": model.api_key or "",
    }

    results: List[ProbeResult] = []
    for label, body, max_tokens in build_rows(entry, budgets):
        payload = {
            "model": model.name,
            "max_tokens": max_tokens,
            "stream": False,
            "messages": [{"role": "user", "content": TRIVIAL_PROMPT}],
        }
        payload.update(body)
        started = time.time()
        status = None
        resp_body = None
        last_err = None
        for _ in range(2):  # one retry: transient transport stalls are common
            try:
                status, resp_body = send(url, headers, payload, timeout)
                last_err = None
                break
            except Exception as e:  # network-level: no HTTP status at all
                last_err = e
        if last_err is not None:
            results.append(ProbeResult(
                label=label, payload=body, status=0, verdict="endpoint-error",
                latency_ms=int((time.time() - started) * 1000),
                error="transport: {}".format(last_err),
            ))
            continue
        latency = int((time.time() - started) * 1000)

        blocks: List[str] = []
        out_tokens = None
        error_text = ""
        if isinstance(resp_body, dict):
            if "error" in resp_body:
                error_text = json.dumps(resp_body["error"], ensure_ascii=False)
            blocks = [b.get("type", "?") for b in resp_body.get("content", [])]
            usage = resp_body.get("usage") or {}
            out_tokens = usage.get("output_tokens")
        else:
            error_text = str(resp_body)

        results.append(ProbeResult(
            label=label, payload=body, status=status,
            verdict=_verdict(status, error_text),
            blocks=blocks, out_tokens=out_tokens, latency_ms=latency,
            error=error_text[:200],
        ))
    return results


def suggest_variants(results: List[ProbeResult]) -> Dict[str, Any]:
    """Derive a suggested tier table from accepted probe rows.

    Every accepted effort value becomes a tier named after itself (the same
    names OpenCode's built-in derivation would use), except ``none``/``minimal``
    — a `disabled` row covers that better. Budget tiers are only suggested
    when no effort tier was accepted. ``off`` is added when ``disabled`` is
    accepted.
    """
    accepted = set(r.label for r in results if r.verdict == "accepted")
    tiers: Dict[str, Any] = {}
    if "disabled" in accepted:
        tiers["off"] = {"thinking": {"type": "disabled"}}
    effort_tiers: Dict[str, Any] = {}
    for r in results:
        if not r.label.startswith("adaptive-effort-"):
            continue
        value = r.label[len("adaptive-effort-"):]
        if r.verdict == "accepted" and value not in _SKIP_EFFORT_TIERS:
            effort_tiers[value] = {"thinking": {"type": "adaptive"}, "effort": value}
    if effort_tiers:
        tiers.update(effort_tiers)
    else:
        budgets = sorted(
            int(r.label.split("-", 1)[1])
            for r in results
            if r.label.startswith("budget-") and r.verdict == "accepted"
        )
        if budgets:
            tiers["low"] = {
                "thinking": {"type": "enabled", "budgetTokens": budgets[0]},
            }
            tiers["high"] = {
                "thinking": {"type": "enabled", "budgetTokens": budgets[-1]},
            }
    return tiers


def apply_preset(
    models_path: Path, model_id: str, tiers: Dict[str, Any]
) -> str:
    """Write ``tiers`` as ``variants_presets['probe-<model_id>']``.

    Only the probe-owned namespace is touched (plus a one-time ``.bak``
    backup of models.toml); everything else round-trips via the store.
    Returns the preset key that was written.
    """
    reg = store.load_models(models_path)
    presets = reg.extra_top.get("variants_presets")
    if not isinstance(presets, dict):
        presets = {}
        reg.extra_top["variants_presets"] = presets
    key = PROBE_PRESET_PREFIX + model_id
    if models_path.exists():
        shutil.copyfile(str(models_path), str(models_path) + ".bak")
    presets[key] = tiers
    store.save_models(models_path, reg)
    return key


def render_report(
    model: store.ModelEntry,
    results: List[ProbeResult],
    catalog: Optional[List[Dict[str, Any]]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the markdown report (stdout / ``--out`` file)."""
    when = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Probe report: {} ({})".format(model.name, model.model_id),
        "",
        "- base_url: {}".format(model.base_url),
        "- generated_at: {}".format(when),
    ]
    if meta and meta.get("source"):
        lines.append("- catalog source: {}".format(meta["source"]))
    lines += [
        "- note: acceptance is HTTP-level; a gateway may still clamp silently.",
        "",
        "| row | HTTP | verdict | blocks | out_tokens | latency_ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            r.label, r.status, r.verdict,
            ",".join(r.blocks) or "-",
            r.out_tokens if r.out_tokens is not None else "-",
            r.latency_ms if r.latency_ms is not None else "-",
        ))

    errors = [r for r in results if r.error]
    if errors:
        lines += ["", "## Errors"]
        for r in errors:
            lines.append("- `{}`: {}".format(r.label, r.error))

    lines += ["", "## Catalog (models.dev)"]
    if catalog:
        for i, m in enumerate(catalog[:5]):
            marker = " **<- matrix source**" if i == 0 else ""
            lines.append(
                "- [{}]{} reasoning_options={} limit={}".format(
                    m["provider"], marker,
                    json.dumps(m.get("reasoning_options"), ensure_ascii=False),
                    json.dumps(m.get("limit"), ensure_ascii=False),
                )
            )
        if len(catalog) > 5:
            lines.append(
                "- ... and {} more providers with the same model key".format(
                    len(catalog) - 5
                )
            )
        lines.append(
            "- caveat: catalog entries describe each provider's declared "
            "endpoint (usually its OpenAI-compatible API); this upstream is "
            "reached over an Anthropic-compatible path — the tier names are "
            "family-wide, the row above is an inference, the probe rows are "
            "the evidence."
        )
    else:
        lines.append("- (no matching model key found — legacy fixed matrix)")

    suggestion = suggest_variants(results)
    lines += ["", "## Suggested preset (evidence-derived, not written)"]
    if suggestion:
        buf = io.StringIO()
        toml_dump(
            {"variants_presets": {PROBE_PRESET_PREFIX + model.model_id: suggestion}},
            buf,
        )
        lines.append("```toml")
        lines.append(buf.getvalue().strip())
        lines.append("```")
    else:
        lines.append("- (no accepted thinking shape — nothing to suggest)")
    lines.append("")
    return "\n".join(lines)
