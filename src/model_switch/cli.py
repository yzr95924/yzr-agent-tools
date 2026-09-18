"""argparse-based CLI for model-switch.

The CLI is a thin wrapper that:
1. Reads models from ~/.config/model-switch/models.toml
2. Reads state from ~/.config/model-switch/state.toml
3. Calls the registered agent driver's read/apply/current methods
4. Writes updated state back

V1+ ships with `claude-code` (default) and `opencode` drivers, both
registered lazily on first use.

Output goes to stdout; errors to stderr. Exit codes:
  0 = success
  1 = user error (bad flag, missing model, missing api_key)
  2 = argparse error (unknown command / flag)
"""
import argparse
import datetime
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, NoReturn, Optional, Tuple

from model_switch import catalog, paths, ui
from model_switch.drivers.base import registry
from model_switch.store import (
    ModelEntry,
    Registry,
    State,
    load_models,
    load_state,
    provider_group_key,
    save_models,
    save_state,
    upstream_key,
)
from model_switch.variants import (
    PRESET_REF_KEY,
    VARIANTS_KEY,
    VariantsError,
    expand,
    expand_model,
)


# ---- shared helpers ---------------------------------------------------------

def _ensure_default_registered() -> None:
    """Register the built-in drivers lazily on first use.

    Lazy registration avoids import-time side effects that would create a
    driver pointed at the real ~/.claude/settings.json (a test-isolation
    hazard). Tests that want a tmp-path driver should populate the
    registry BEFORE the first CLI invocation.
    """
    from model_switch.drivers.claude_code import ClaudeCodeDriver
    from model_switch.drivers.opencode import OpenCodeDriver

    if "claude-code" not in registry.list():
        registry.register(ClaudeCodeDriver())
    if "opencode" not in registry.list():
        registry.register(OpenCodeDriver())


def _die(message) -> NoReturn:
    """Print ``Error: <message>`` to stderr and exit 1.

    The single failure path for user errors (see the module docstring's exit
    codes); ``message`` may be an exception or a plain string. Delegates the
    actual stop to `ui.abort` so every abort shares one channel.
    """
    ui.abort(f"Error: {message}")


def _interactive(args: argparse.Namespace) -> bool:
    """True when we may prompt: a TTY and no blanket ``--yes``."""
    return sys.stdin.isatty() and not args.yes


def _resolve_driver(name: Optional[str]):
    """Return the named driver, or the default if name is None/empty."""
    _ensure_default_registered()
    if name:
        try:
            return registry.get(name)
        except KeyError as e:
            _die(e)
    driver = registry.default()
    if driver is None:
        _die("no agent driver registered.")
    return driver


def _resolve_drivers(args) -> list:
    """Resolve which driver(s) to apply to.

    Precedence:
      1. `--all-drivers` → every registered driver.
      2. `--driver NAME` → that single driver.
      3. Interactive TTY prompt → comma-separated names (Enter = all).
      4. Non-TTY / no prompt → default driver (`claude-code`).
    """
    _ensure_default_registered()
    available = registry.list()
    if args.all_drivers:
        return [_resolve_driver(n) for n in available]
    if args.driver_name:
        return [_resolve_driver(args.driver_name)]
    if sys.stdin.isatty() and available:
        # Interactive prompt — defaults to ALL registered drivers, so hitting
        # Enter switches every agent at once (the common case: you want the
        # new model everywhere). Name a subset to scope it, e.g. "claude-code".
        print(f"Available drivers: {', '.join(available)}")
        try:
            raw = input(
                "Apply to which driver(s)? "
                "(comma-separated, 'all' or Enter for all): "
            ).strip()
        except EOFError:
            # Ctrl-D, or a piped session that ran out of answers: treat it
            # like Enter — the documented default — instead of a traceback.
            raw = ""
        if not raw or raw.lower() == "all":
            return [_resolve_driver(n) for n in available]
        names = [n.strip() for n in raw.split(",") if n.strip()]
        for n in names:
            if n not in available:
                _die(f"unknown driver {n!r}. Available: {available}")
        return [_resolve_driver(n) for n in names]
    # Non-interactive (no TTY): keep the old single-driver default so CI
    # scripts don't unexpectedly write multiple agent configs.
    return [_resolve_driver(None)]


def _resolve_api_key(model) -> str:
    """Return the model's API key (stored plaintext in models.toml)."""
    if model.api_key:
        return model.api_key
    _die(f"model {model.model_id!r} has no api_key in models.toml.")


def _registered_drivers() -> list:
    """Return every registered driver instance (defaults registered first)."""
    _ensure_default_registered()
    return [registry.get(n) for n in registry.list()]


def _expand_or_die(reg: Registry,
                   only: Optional[ModelEntry] = None) -> List[ModelEntry]:
    """Materialize variant-preset references, or exit with a clear error.

    `only` narrows expansion to one model (`model show` shouldn't trip over
    a different model's broken preset); the default expands the whole
    registry, which is what every write path wants.

    Expansion is in-memory only (see `model_switch.variants`) — `save_models`
    must always be handed the original Registry.
    """
    try:
        return [expand_model(reg, only)] if only is not None else expand(reg)
    except VariantsError as e:
        _die(e)


def _sync_catalog(reg: Registry) -> None:
    """Mirror `reg` (the full models.toml registry) into every
    catalog-capable driver — currently OpenCode. Reconcile keeps each
    driver's default pointer unless it vanished. Single-slot drivers
    (claude-code) are skipped; missing agent configs are left alone (a
    targeted `model use` creates them).

    Takes the Registry (not just the model list) so variant presets declared
    at the top level can be expanded before rendering. Grouping errors
    (conflicting provider declarations, duplicate names) surface as a clean
    one-line error instead of a traceback.
    """
    models = _expand_or_die(reg)
    try:
        for d in _registered_drivers():
            if getattr(d, "supports_catalog", False):
                d.sync_catalog(models)
    except ValueError as e:
        _die(e)


def _clear_active_if_orphaned(reg: Registry) -> None:
    """If state.active_main no longer names a model, drop it and clear the
    single-slot driver's managed keys — nothing of a deleted model (notably its
    key) may linger in any agent config."""
    state = load_state(paths.state_file())
    if state.active_main is None or state.active_main in reg.models:
        return
    state.active_main = None
    state.last_updated = _now_iso()
    save_state(paths.state_file(), state)
    for d in _registered_drivers():
        if not getattr(d, "supports_catalog", False):
            d.clear()


def _now_iso() -> str:
    # Timezone-aware UTC with a "Z" suffix — `datetime.utcnow()` is
    # deprecated on 3.12+, and `datetime.timezone` exists since 3.2, so
    # this is safe on the repo's 3.7+ floor.
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _prompt(label: str, default=None, *, type_=str, optional: bool = False):
    """Read one line from stdin (interactive only).

    Only prompts when stdin is a TTY. In non-interactive contexts (piped
    input, CI, tests), if the option is missing AND required, we exit with
    a clear error. If optional, return `None` (or `default`).

    Do NOT pass secrets here — input is echoed. We only prompt for model
    identifiers and descriptions. For the API key, use `_prompt_secret`
    (which does not echo).
    """
    suffix = ""
    if default is not None:
        suffix = f" [{default}]"
    elif optional:
        suffix = " (optional)"
    if not sys.stdin.isatty():
        # Non-interactive: honor `default` if set, otherwise fail.
        if default is not None:
            return default
        if optional:
            return None
        _die(f"{label!r} is required (no TTY for interactive prompt). "
             f"Pass it as a flag.")
    prompt_text = f"{label}{suffix}: "
    while True:
        try:
            line = input(prompt_text)
        except EOFError:
            # Stream ran out (e.g. test piped fewer answers than prompts):
            # fall back to the default if there's one, else fail clearly.
            if default is not None:
                return default
            if optional:
                return None
            _die(f"{label!r} is required (input exhausted). "
                 f"Pass it as a flag.")
        if line == "":
            if default is not None:
                return default
            if optional:
                return None
            _die("value is required.")
        try:
            return type_(line)
        except ValueError:
            # Bad type (e.g. "abc" for a token count) must re-ask, not
            # traceback mid-wizard.
            prompt_text = f"  {type_.__name__} expected — try again: "


def _prompt_secret(label: str) -> str:
    """Read a secret (the API key) from stdin, echoing what's typed.

    The key is persisted in plaintext to models.toml anyway, so hiding the
    input buys nothing and makes typos hard to catch. In non-interactive
    contexts with no input, exit with a clear error telling the user to
    pass `--api-key`.
    """
    if not sys.stdin.isatty():
        _die(f"{label} is required (no TTY for prompt). "
             f"Pass it via --api-key.")
    try:
        value = input(f"{label}: ")
    except EOFError:
        _die(f"{label} is required (input exhausted). "
             f"Pass it via --api-key.")
    if value == "":
        _die("value is required.")
    return value


# ---- parser construction ----------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model-switch",
        description="Switch Anthropic-compatible models for Claude Code and OpenCode.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    # init
    sub.add_parser("init", help="Initialize the model-switch config directory.")

    # model
    p_model = sub.add_parser("model", help="Manage model definitions.")
    model_sub = p_model.add_subparsers(dest="model_action", required=True, metavar="ACTION")

    p_add = model_sub.add_parser("add", help="Add a new model definition.")
    p_add.add_argument(
        "name", nargs="?", default=None,
        help="Local nickname for this model (prompted when omitted).",
    )
    p_add.add_argument("--base-url", default=None, help="Upstream API base URL.")
    p_add.add_argument(
        "--api-key", default=None,
        help="API key stored in models.toml (plaintext). Prompted securely if omitted.",
    )
    p_add.add_argument(
        "--model-name", default=None,
        help="Model identifier expected by upstream (bare id, no context suffix).",
    )
    p_add.add_argument("--description", default=None, help="Free-text description.")
    p_add.add_argument(
        "--provider", default=None,
        help="Pin the provider group name (id becomes yzr-<name>); defaults "
             "to a slug derived from base_url. Models sharing a name must "
             "share base_url and api_key. When omitted and an existing model "
             "on the same base_url + api_key already declares one, the "
             "wizard offers to join that group; pass '-' to leave this model "
             "undeclared instead.",
    )
    p_add.add_argument(
        "--context-window", type=int, default=None,
        help="Max input tokens (e.g. 200000 or 1000000 for 1M-context variants).",
    )
    p_add.add_argument(
        "--catalog-provider", default=None,
        help="Pin the OpenCode-catalog provider entry used to fill fields "
             "(disambiguates the same model under many providers).",
    )
    p_add.add_argument(
        "--no-catalog", action="store_true",
        help="Skip deriving fields from OpenCode's catalog cache.",
    )
    p_add.add_argument(
        "--yes", "-y", action="store_true",
        help="Assume yes: skip the final confirmation and overwrite an "
             "existing model of the same name without asking.",
    )

    model_sub.add_parser("list", help="List all configured models.")

    p_show = model_sub.add_parser("show", help="Show details of one model.")
    p_show.add_argument("name", nargs="?", default=None)

    p_rm = model_sub.add_parser("remove", help="Remove a model definition.")
    p_rm.add_argument("name", nargs="?", default=None)
    p_rm.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip the removal confirmation.",
    )

    p_use = model_sub.add_parser("use", help="Activate a model.")
    p_use.add_argument("name", nargs="?", default=None,
                       help="Model name to activate (prompted when omitted).")
    p_use.add_argument(
        "--driver", default=None, dest="driver_name",
        help="Target agent driver (e.g. 'claude-code' or 'opencode').",
    )
    p_use.add_argument(
        "--all-drivers", action="store_true", dest="all_drivers",
        help="Apply to every registered driver (skips interactive prompt).",
    )

    p_import = model_sub.add_parser(
        "import", help="Import model definitions from an llmw workspace_models.toml.",
    )
    p_import.add_argument(
        "path", help="Path to the source TOML file (e.g. workspace_models.toml).",
    )
    p_import.add_argument(
        "--merge", action="store_true",
        help="Merge into existing models.toml (default: replace).",
    )

    p_align = model_sub.add_parser(
        "align",
        help="Align model fields with OpenCode's catalog cache (all models, "
             "or one).",
    )
    p_align.add_argument(
        "name", nargs="?", default=None,
        help="Model to align; omit to align every model in models.toml.",
    )
    p_align.add_argument(
        "--catalog-provider", default=None,
        help="Pin the OpenCode-catalog provider entry (single model only).",
    )

    # status
    p_status = sub.add_parser("status", help="Show current state + effective agent config.")
    p_status.add_argument("--driver", default=None, dest="driver_name")
    p_status.add_argument("--all-drivers", action="store_true", dest="all_drivers")

    # _complete — hidden plumbing for the shell completion scripts
    # (completions/). No `help=` on purpose: argparse only lists subparsers
    # that carry help text, so this stays out of `--help` output.
    p_complete = sub.add_parser("_complete")
    p_complete.add_argument(
        "what", choices=["models", "drivers"],
        help="Which candidates to print, one per line.",
    )

    return parser


# ---- dispatch ---------------------------------------------------------------

def _do_init() -> None:
    d = paths.config_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not paths.models_file().exists():
        save_models(paths.models_file(), Registry())
    if not paths.state_file().exists():
        save_state(paths.state_file(), State())
    print(f"Initialized model-switch config at {d}")


def _do_model_add(args: argparse.Namespace) -> None:
    """Add (or replace) a model definition.

    A wizard when stdin is a TTY: base URL and API key are pasted, then the
    upstream id and every derivable field come from a numbered picker over
    OpenCode's catalog cache. Any flag pre-answers its prompt, so a fully
    flagged invocation stays script-safe — nothing is asked or confirmed.
    Fields the cache can supply (context window, reasoning, variant tiers,
    modalities) are derived from it; `--no-catalog` opts out,
    `--catalog-provider` pins the provider entry when several match.

    The provider group is asked about only when an existing model on the
    same base_url + api_key already declares one — see `_resolve_provider`.
    """
    reg = load_models(paths.models_file())

    base_url = args.base_url or _prompt("Upstream API base URL")
    api_key = args.api_key or _prompt_secret("API key")
    provider = _resolve_provider(args, reg, base_url, api_key)

    # An explicit `--model-name` / `--catalog-provider` means the model is
    # already determined: keep the pre-wizard derivation path untouched.
    picked = None
    if (not args.no_catalog and args.model_name is None
            and args.catalog_provider is None):
        picked = _pick_catalog_model(base_url)
    model_name, derived = _choose_upstream(args, base_url, picked)
    name, replacing = _choose_local_name(args, reg, picked, model_name)
    if provider is None:
        _note_declined_group(reg, base_url, api_key, name)
    context_window, description = _collect_optional_fields(args, derived)

    # Build the entry before asking: the summary then *is* what gets written,
    # not a second assembly of the same fields that could drift from it.
    entry = ModelEntry(
        model_id=name,
        name=model_name,
        base_url=base_url,
        api_key=api_key,
        context_window=context_window,
        description=description,
        extra=_build_extra(derived, provider),
    )

    if _interactive(args):
        _print_add_summary(entry, replacing)
        if not ui.confirm("Proceed?", default=True):
            ui.abort("Aborted — nothing written.")

    _save_and_report(reg, entry, replacing)


def _choose_upstream(args: argparse.Namespace, base_url: str,
                     picked: Optional[catalog.Row]):
    """Resolve ``(model_name, derived_fields)`` from the pick or from flags."""
    if picked is not None:
        return picked.model, catalog.derive(picked.entry)
    model_name = args.model_name or _prompt(
        "Model identifier (bare id, no context suffix)", default=args.name,
    )
    return model_name, _derive_or_report(model_name, base_url,
                                         args.catalog_provider, args.no_catalog)


def _choose_local_name(args: argparse.Namespace, reg: Registry,
                       picked: Optional[catalog.Row], model_name: str):
    """Prompt for the local name when it was not given, then gate overwrites.

    Returns ``(name, replacing)``.
    """
    name = args.name
    if name is None:
        name = _prompt(
            "Local name",
            default=picked.model if picked is not None else model_name,
        )
    return _resolve_add_name(name, reg, args.yes)


def _collect_optional_fields(args: argparse.Namespace, derived: Dict[str, Any]):
    """Prompt for the optional context window and description.

    Returns ``(context_window, description)``; both may be None.
    """
    if args.context_window is not None:
        context_window = args.context_window
    else:
        context_window = _prompt(
            "Context window in tokens (press Enter to skip)",
            default=derived.get("context_window"), optional=True, type_=int,
        )
    description = args.description
    if not description:
        description = _prompt("Description", optional=True)
    return context_window, description


# Typed at the provider prompt (or passed to --provider) to mean "no
# declaration". It is not a legal `_PROVIDER_NAME_RE` name, so intercepting it
# is what makes *dropping* an inherited group reachable.
_NO_DECLARATION = "-"


def _matching_provider(reg: Registry, base_url: str, api_key: Optional[str],
                       exclude: Optional[str] = None) -> Optional[str]:
    """The declared provider of an existing model on the same upstream.

    Adding an undeclared model to an upstream that already declares a group
    would put it in a *second* block named after the host with a ``-2``
    suffix — same upstream, same key, two provider blocks. Inheriting the
    group's name is what keeps them together.

    ``exclude`` skips one model_id: a replacing `model add` must not mistake
    the entry it is about to overwrite for a group the new model could join.

    The rule itself lives in `store.provider_group_key` so this query and the
    drivers that render the blocks cannot drift apart. The inherited name is
    the alphabetically first one, so a registry where several names somehow
    share one upstream still answers the same way every run.
    """
    want = (base_url, api_key or "")
    names = []
    for m in reg.models.values():
        if m.model_id == exclude:
            continue
        # Check the upstream first: `provider_group_key` validates the
        # declaration, and an unrelated malformed entry must not fail an add
        # that has nothing to do with it.
        if upstream_key(m) != want:
            continue
        name = provider_group_key(m)[0]
        if name is not None:
            names.append(name)
    return min(names) if names else None


def _matching_provider_or_die(reg: Registry, base_url: str,
                              api_key: Optional[str],
                              exclude: Optional[str] = None) -> Optional[str]:
    """`_matching_provider`, with its validation error surfaced cleanly."""
    try:
        return _matching_provider(reg, base_url, api_key, exclude)
    except ValueError as e:
        _die(e)


def _resolve_provider(args: argparse.Namespace, reg: Registry, base_url: str,
                      api_key: Optional[str]) -> Optional[str]:
    """Resolve the provider group name for the model being added.

    ``--provider`` pre-answers the prompt. Otherwise we only ask when an
    existing group is joinable: with no same-upstream model to group with
    there is nothing to decide, and staying quiet keeps the wizard's prompt
    sequence stable for scripts and piped input. Pressing Enter takes the
    inherited name; ``-`` declines it, which is the only way to *drop* a
    declaration the entry already had. Declining is noted separately, once
    the local name is known — see `_note_declined_group`.
    """
    if args.provider is not None and args.provider != _NO_DECLARATION:
        return args.provider
    group = _matching_provider_or_die(reg, base_url, api_key)
    if args.provider is None and group is not None:
        value = _prompt(
            f"Provider group (joins {group!r}; "
            f"{_NO_DECLARATION!r} = no declaration)",
            default=group, optional=True,
        )
        if value != _NO_DECLARATION:
            return value
    return None


def _note_declined_group(reg: Registry, base_url: str, api_key: Optional[str],
                         name: str) -> None:
    """Warn that an undeclared model lands in its own provider block.

    Runs *after* the local name is resolved so the entry this add replaces is
    excluded: when replacing a model that declared the group itself, that
    declaration disappears with it and there is nothing to warn about.
    """
    group = _matching_provider_or_die(reg, base_url, api_key, exclude=name)
    if group is None:
        return
    print(f"  note: this upstream still has a declared group {group!r} — "
          f"left undeclared, this model renders as a separate yzr-<host> "
          f"provider block")


def _save_and_report(reg: Registry, entry: ModelEntry, replacing: bool) -> None:
    """Persist the entry, mirror the catalog and report what happened."""
    reg.models[entry.model_id] = entry
    save_models(paths.models_file(), reg)
    # Mirror the catalog so the new model is immediately available in agents
    # that hold one (OpenCode's picker). Single-slot agents (claude-code) are
    # untouched until the next `model use`.
    _sync_catalog(reg)
    print(f"{'Replaced' if replacing else 'Added'} model {entry.model_id!r}.")
    if replacing and load_state(paths.state_file()).active_main == entry.model_id:
        print(f"  note: {entry.model_id!r} is the active model — run "
              f"`model-switch model use {entry.model_id}` to re-apply it to "
              f"your agents.")


def _build_extra(derived: Dict[str, Any], provider: Optional[str]) -> dict:
    """Assemble the passthrough fields the drivers render from `derived`."""
    extra = {}
    if provider:
        extra["provider"] = provider
    if derived.get("reasoning"):
        extra["reasoning"] = True
    if derived.get("variants"):
        extra["variants"] = derived["variants"]
    if derived.get("modalities"):
        extra["modalities"] = derived["modalities"]
    return extra


def _resolve_add_name(name: str, reg: Registry, assume_yes: bool):
    """Resolve the local name against existing entries: ``(name, replacing)``.

    An existing entry is never overwritten silently — a TTY gets an explicit
    question (declining re-asks for another name; the pasted URL/key are
    kept), a non-TTY script must pass ``--yes``.
    """
    while True:
        if name not in reg.models:
            return name, False
        if assume_yes:
            return name, True
        if not sys.stdin.isatty():
            _die(f"model {name!r} already exists (use --yes to overwrite).")
        old = reg.models[name]
        print(f"model {name!r} already exists "
              f"(upstream id {old.name}, {old.base_url}).")
        if ui.confirm("Overwrite it?", default=False):
            return name, True
        name = _prompt("Local name")


# Reserved first tokens at the search prompt. Both are matched on the first
# token only, so `skip-connections` or `allam-2-7b` still search normally.
_SEARCH_SKIP = "skip"
_SEARCH_ALL = "all"


def _split_search(raw: str) -> Tuple[str, str]:
    """Split a search line into ``(first token lowercased, the rest)``.

    The first token may be a reserved word (`skip`, `all`), and it is matched
    here only — so `skip-connections` or `allam-2-7b` still search normally.
    """
    parts = raw.split(None, 1)
    head = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""
    return head, rest


def _catalog_row_key(row: catalog.Row) -> Tuple[str, str]:
    """What identifies a catalog row: ``(provider, model)``.

    `host_keys` and every trust check go through this, so the notion of row
    identity has one definition.
    """
    return (row.provider, row.model)


def _print_no_catalog_rows(host: str, raw: str, query: str, wide: bool) -> None:
    """Explain an empty result and how to widen or leave the search."""
    if wide:
        print(f"  no catalog entry matches {query!r} on any provider — try "
              f"again or {_SEARCH_SKIP!r}")
    elif raw == "":
        print(f"  no catalog entry on {host} — search every provider with "
              f"'{_SEARCH_ALL} <term>', or {_SEARCH_SKIP!r}")
    else:
        print(f"  no catalog entry on {host} matches {raw!r} — try again, "
              f"'{_SEARCH_ALL} <term>' or {_SEARCH_SKIP!r}")


def _rank_host_first(rows: List[catalog.Row],
                     host_keys: set) -> List[catalog.Row]:
    """Host-matching rows first, then the rest — each kept in search order.

    `ui.MENU_MAX` caps the menu at 20 rows, so an alphabetical catalog-wide
    result would spend the whole menu on whichever provider sorts first and
    hide the upstream actually being configured.
    """
    return sorted(rows, key=lambda r: (_catalog_row_key(r) not in host_keys,
                                       r.provider, r.model))


def _catalog_row_renderer(host_keys: set) -> Callable[[catalog.Row], str]:
    """Build the `ui.pick_one` render fn, tagging foreign-provider rows.

    Only foreign rows are marked: within the default host scope every row
    matches, so leaving those untouched keeps the familiar menu byte-equal.
    """
    def render(row: catalog.Row) -> str:
        line = _render_catalog_row(row)
        if _catalog_row_key(row) not in host_keys:
            line += "  [other host]"
        return line
    return render


def _pick_catalog_model(base_url: str) -> Optional[catalog.Row]:
    """Pick the upstream model from the catalog cache (TTY only).

    Returns the picked `catalog.Row`, or None to fall back to typing the id
    by hand: no cache, no host in the base URL, or 'skip'.

    Searches are scoped to the pasted base_url's host. That scope is what
    makes the derived fields trustworthy: they are written into an entry that
    talks to *that* upstream, so another provider's declarations can be wrong
    for it (a `modalities` claim the upstream rejects turns OpenCode's silent
    fallback into a hard request error). `all <term>` widens one search to
    the whole catalog for a deliberate look-up — those rows rank after the
    host matches, are tagged `[other host]`, and print a note when picked.
    """
    if not sys.stdin.isatty():
        return None
    data, desc = catalog.load_cache()
    if data is None:
        print(f"catalog: {desc} — skipping auto-fill")
        return None
    host = catalog.host_of(base_url)
    if not host:
        # Without a host there is no scope at all: `catalog.search` would
        # treat "" as "no filter" and offer the whole catalog as if it were
        # the user's upstream, with nothing tagged foreign. Refuse instead —
        # a base URL without a host is broken and must be fixed anyway.
        print(f"catalog: {base_url!r} has no host — cannot tell which "
              f"upstream it is; skipping auto-fill")
        return None
    # Empty query = list everything on this host, so this scan doubles as the
    # header count and the host-match index.
    host_rows = catalog.search(data, "", host=host)
    host_keys = {_catalog_row_key(r) for r in host_rows}
    print(f"catalog: {desc} — {len(host_rows)} model(s) on {host}")
    while True:
        raw = ui.ask(f"Search models (Enter = list, '{_SEARCH_ALL} <term>' = "
                     f"every provider, '{_SEARCH_SKIP}' = type the id by "
                     f"hand): ").strip()
        head, rest = _split_search(raw)
        if head == _SEARCH_SKIP:
            return None
        wide = head == _SEARCH_ALL
        query = rest if wide else raw
        if wide and not query:
            print(f"  '{_SEARCH_ALL}' needs a search term — the full catalog "
                  f"is too long to list (e.g. '{_SEARCH_ALL} qwen')")
            continue
        if raw == "":
            rows = host_rows
        else:
            rows = _rank_host_first(
                catalog.search(data, query, host=None if wide else host),
                host_keys)
        if not rows:
            _print_no_catalog_rows(host, raw, query, wide)
            continue
        title = f"  {len(rows)} match(es):"
        if wide:
            title += f"  (host {host} first, then every provider)"
        idx = ui.pick_one(title, rows, _catalog_row_renderer(host_keys),
                          default=0, allow_back=True)
        if idx is None:
            continue  # 'b' — refine the search
        row = rows[idx]
        if _catalog_row_key(row) not in host_keys:
            print(f"  note: fields come from {row.provider}'s catalog entry, "
                  f"not {host}'s — verify the context window and modalities "
                  f"against your upstream")
        return row


def _render_catalog_row(row: catalog.Row) -> str:
    """One compact menu line: provider/model, display name, ctx, tiers."""
    entry = row.entry
    bits = [f"{row.provider}/{row.model}"]
    display = str(entry.get("name") or "")
    if display and display != row.model:
        bits.append(display)
    derived = catalog.derive(entry)
    if derived["context_window"]:
        bits.append("ctx " + _format_context(derived["context_window"]))
    if derived["variants"]:
        bits.append("tiers[" + ",".join(derived["variants"]) + "]")
    elif derived["reasoning"]:
        bits.append("reasoning")
    if derived["modalities"]:
        bits.append("+".join(derived["modalities"]["input"]))
    return "  ".join(bits)


def _print_add_summary(entry: ModelEntry, replacing: bool) -> None:
    """Show exactly what is about to be written before asking to proceed.

    Reads from the ``ModelEntry`` itself — the printed fields cannot drift
    from what gets saved.
    """
    print("")
    print(f"About to add {entry.model_id!r}"
          f"{' (replaces existing)' if replacing else ''}:")
    print(f"  upstream id     {entry.name}")
    print(f"  base URL        {entry.base_url}")
    if entry.context_window:
        print(f"  context window  {_format_context(entry.context_window)}")
    if entry.extra.get("reasoning"):
        print("  reasoning       yes")
    if entry.extra.get("variants"):
        print("  variants        " + ", ".join(entry.extra["variants"]))
    if entry.extra.get("modalities"):
        print("  modalities      " + "+".join(entry.extra["modalities"]["input"]))
    if entry.extra.get("provider"):
        print(f"  provider group  {entry.extra['provider']}")


def _derive_or_report(model_name: str, base_url: str,
                      pin: Optional[str], no_catalog: bool) -> Dict[str, Any]:
    """Catalog-derive fields for one model, reporting what happened.

    Never fails the caller: an absent cache, an unknown model name or an
    unresolved ambiguity print a short explanation (with the candidates to
    pin) and return ``{}``, leaving manual values in charge.
    """
    if no_catalog:
        return {}
    data, desc = catalog.load_cache()
    if data is None:
        print(f"catalog: {desc} — skipping auto-fill")
        return {}
    picked = catalog.pick(catalog.candidates(data, model_name, base_url), pin)
    if picked.candidate is None:
        print(f"catalog: {picked.reason} — skipping auto-fill")
        for c in (picked.alternatives or [])[:5]:
            print(f"  {c.provider}  api={c.api or '-'}")
        if picked.alternatives:
            print("  pin one with --catalog-provider <id>")
        return {}
    fields = catalog.derive(picked.candidate.entry)
    print("catalog: {} ({}) — filled {}".format(
        picked.candidate.provider, desc, _describe_fields(fields)))
    if catalog.budget_only(picked.candidate.entry):
        print("  note: only budget_tokens declared — no tiers derived; "
              "write them by hand if needed")
    return fields


def _describe_fields(fields: Dict[str, Any]) -> str:
    """One-line summary of the fields `catalog.derive` produced."""
    bits = []
    if fields.get("context_window"):
        bits.append("context_window={}".format(fields["context_window"]))
    if fields.get("reasoning"):
        bits.append("reasoning")
    if fields.get("variants"):
        bits.append("variants[{}]".format(",".join(fields["variants"])))
    if fields.get("modalities"):
        bits.append("modalities[{}]".format(
            ",".join(fields["modalities"]["input"])))
    return ", ".join(bits) or "nothing derivable"


def _do_model_align(args: argparse.Namespace) -> int:
    """Reconcile models.toml with OpenCode's catalog cache.

    Aligns one model, or every model when no name is given. Scalar fields
    (context_window, reasoning, modalities) are updated in place; variant
    tiers are replaced only when declared inline — a model backed by a shared
    `variants_preset` is reported as `skip` instead, because rewriting that
    preset could silently change every model referencing it. Returns a
    nonzero exit code when any model stayed unresolved, so scripts notice.
    """
    reg = load_models(paths.models_file())
    if args.name is not None and args.name not in reg.models:
        _die(f"model {args.name!r} not found.")
    targets = [args.name] if args.name is not None else list(reg.models)
    if not targets:
        _die("models.toml declares no models.")
    if args.catalog_provider is not None and len(targets) != 1:
        _die("--catalog-provider needs a single model name.")

    data, desc = catalog.load_cache()
    if data is None:
        _die(f"{desc}; cannot align without it.")

    width = max(len(m) for m in targets)
    changed = 0
    skipped = 0
    for model_id in targets:
        model = reg.models[model_id]
        picked = catalog.pick(
            catalog.candidates(data, model.name, model.base_url),
            args.catalog_provider,
        )
        if picked.candidate is None:
            skipped += 1
            detail = picked.reason
            names = ", ".join(c.provider for c in (picked.alternatives or [])[:5])
            if names:
                detail += " (candidates: {})".format(names)
            print("{:<{w}}  skip     -  {}".format(model_id, detail, w=width))
            continue

        fields = catalog.derive(picked.candidate.entry)
        changes: List[str] = []
        notes: List[str] = []
        if fields["context_window"] and model.context_window != fields["context_window"]:
            changes.append("context_window {}→{}".format(
                model.context_window, fields["context_window"]))
            model.context_window = fields["context_window"]
        if fields["reasoning"] and model.extra.get("reasoning") is not True:
            changes.append("+reasoning")
            model.extra["reasoning"] = True
        if fields["modalities"] and model.extra.get("modalities") != fields["modalities"]:
            changes.append("modalities→[{}]".format(
                ",".join(fields["modalities"]["input"])))
            model.extra["modalities"] = fields["modalities"]
        if fields["variants"]:
            if PRESET_REF_KEY in model.extra:
                skipped += 1
                notes.append("variants from preset {!r} left alone".format(
                    model.extra[PRESET_REF_KEY]))
            elif model.extra.get(VARIANTS_KEY) != fields["variants"]:
                changes.append("variants[{}]".format(",".join(fields["variants"])))
                model.extra[VARIANTS_KEY] = fields["variants"]
        elif catalog.budget_only(picked.candidate.entry):
            notes.append("only budget_tokens declared — no tiers derived")

        if changes:
            changed += 1
        print("{:<{w}}  {:<7}  {}  {}".format(
            model_id, "aligned" if changes else "ok",
            picked.candidate.provider,
            "; ".join(changes + notes) or "no change",
            w=width,
        ))

    if changed:
        save_models(paths.models_file(), reg)
        _sync_catalog(reg)
    print("align: {} updated, {} skipped (of {}) via {}".format(
        changed, skipped, len(targets), desc))
    if skipped:
        print("align: pin the skipped model(s) with --catalog-provider and re-run")
    return 1 if skipped else 0


def _format_context(n) -> str:
    """Render a context window in human units: 200000 -> '200K', None -> '-(none)-'."""
    if n is None:
        return "-(none)-"
    if n >= 1_000_000 and n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n >= 1_000 and n % 1_000 == 0:
        return f"{n // 1_000}K"
    return str(n)


def _truncate(s, width) -> str:
    """Truncate `s` to `width` chars, ending with '…' if shortened."""
    if len(s) <= width:
        return s
    if width <= 1:
        return "…"
    return s[: width - 1] + "…"


def _do_model_list() -> None:
    reg = load_models(paths.models_file())
    state = load_state(paths.state_file())
    if not reg.models:
        print("(no models configured — run `model-switch model add` to add one)")
        return

    rows = []
    for n, m in reg.models.items():
        rows.append((
            n,
            m.name,
            _format_context(m.context_window),
            _truncate(m.base_url, 50),
            n == state.active_main,
        ))

    names = [r[0] for r in rows]
    models_col = [r[1] for r in rows]
    contexts = [r[2] for r in rows]
    urls = [r[3] for r in rows]

    name_w = max(max(len(s) for s in names), len("NAME"))
    model_w = max(max(len(s) for s in models_col), len("MODEL"))
    context_w = max(max(len(s) for s in contexts), len("CONTEXT"))
    url_w = max(max(len(s) for s in urls), len("BASE_URL"))

    print(
        "  "
        + "NAME".ljust(name_w)
        + "  "
        + "MODEL".ljust(model_w)
        + "  "
        + "CONTEXT".ljust(context_w)
        + "  "
        + "BASE_URL".ljust(url_w)
    )
    for n, model, ctx, url, is_active in rows:
        prefix = "→ " if is_active else "  "
        print(
            prefix
            + n.ljust(name_w)
            + "  "
            + model.ljust(model_w)
            + "  "
            + ctx.ljust(context_w)
            + "  "
            + url
        )


def _pick_configured_model(reg: Registry) -> str:
    """Numbered picker over the configured models (TTY only)."""
    if not reg.models:
        _die("no models configured — run `model-switch model add` first.")
    state = load_state(paths.state_file())

    def render(n):
        m = reg.models[n]
        marker = "→" if n == state.active_main else " "
        return "{} {}  {}  {}  {}".format(
            marker, n, m.name, _format_context(m.context_window),
            _truncate(m.base_url, 50))

    names = list(reg.models)
    return names[ui.pick_one("Configured models:", names, render)]


def _resolve_model_arg(name: Optional[str], reg: Registry) -> str:
    """`name`, or the interactive picker when omitted (never blocks non-TTY)."""
    if name is not None:
        return name
    if not sys.stdin.isatty():
        _die("model name is required (no TTY for the picker) — pass it as an "
             "argument.")
    return _pick_configured_model(reg)


def _do_model_show(args: argparse.Namespace) -> None:
    reg = load_models(paths.models_file())
    name = _resolve_model_arg(args.name, reg)
    if name not in reg.models:
        _die(f"model {name!r} not found.")
    m = reg.models[name]
    # Resolve the variant declaration up front: a broken one should fail
    # before any of the model's fields are printed.
    ref = m.extra.get(PRESET_REF_KEY)
    variants = _expand_or_die(reg, only=m)[0].extra.get(VARIANTS_KEY)

    print(f"name:           {name}")
    print(f"base_url:       {m.base_url}")
    print(f"api_key:        {'<set>' if m.api_key else '<missing>'}")
    print(f"model_name:     {m.name}")
    if isinstance(m.extra.get("provider"), str):
        print(f"provider:       {m.extra['provider']}")
    if m.context_window is not None:
        print(f"context_window: {m.context_window}")
    if m.description:
        print(f"description:    {m.description}")
    # What OpenCode will render for the variant cycle: the reasoning flag,
    # the declared preset (if any) and the tier names it expands to.
    if m.extra.get("reasoning") is True:
        print("reasoning:      true")
    if isinstance(variants, dict) and variants:
        # OpenCode drops tiers marked `disabled` (that's how a model mutes a
        # preset tier or a built-in one), so report what the cycle will
        # actually offer and name the muted tiers separately.
        enabled = [
            t for t, body in variants.items()
            if not (isinstance(body, dict) and body.get("disabled"))
        ]
        muted = [t for t in variants if t not in enabled]
        source = "preset {!r}".format(ref) if ref is not None else "(inline)"
        line = "variants:       {} -> {}".format(source, ", ".join(enabled) or "<none>")
        if muted:
            line += " (disabled: {})".format(", ".join(muted))
        print(line)


def _do_model_remove(args: argparse.Namespace) -> None:
    reg = load_models(paths.models_file())
    name = _resolve_model_arg(args.name, reg)
    if name not in reg.models:
        _die(f"model {name!r} not found.")
    if _interactive(args):
        m = reg.models[name]
        if not ui.confirm(f"Remove model {name!r} (upstream id {m.name})?",
                          default=False):
            ui.abort("Aborted — nothing removed.")
    del reg.models[name]
    save_models(paths.models_file(), reg)
    # Reconcile the catalog (removed model's provider + key vanish from
    # OpenCode) and clear the single-slot agent if the removed model was active.
    _sync_catalog(reg)
    _clear_active_if_orphaned(reg)
    print(f"Removed model {name!r}.")


def _do_model_use(args: argparse.Namespace) -> None:
    reg = load_models(paths.models_file())
    name = _resolve_model_arg(args.name, reg)
    if name not in reg.models:
        _die(f"model {name!r} not found.")

    # Variant presets are materialized here (in memory) so every driver sees
    # plain `variants` dicts; models.toml keeps the preset + reference form.
    expanded = {m.model_id: m for m in _expand_or_die(reg)}
    main_model = expanded[name]

    # Validate the active model has a key before touching any driver config.
    _resolve_api_key(main_model)

    applied = []
    try:
        for driver in _resolve_drivers(args):
            driver.apply(models=list(expanded.values()), active=main_model)
            applied.append(driver)
    except ValueError as e:
        _die(e)

    state = load_state(paths.state_file())
    state.active_main = name
    state.last_updated = _now_iso()
    save_state(paths.state_file(), state)

    print(f"Switched to {name!r}.")
    for d in applied:
        print(f"  Wrote {d.settings_path} ({d.name})")
    print("  Restart your agent (Claude Code: Ctrl+D, then `claude`; OpenCode: restart the CLI) to take effect.")


def _do_model_import(args: argparse.Namespace) -> None:
    """Import model definitions from an llmw-format TOML file.

    Conversion rules (see `model_switch.importer`):
    - `api_key` is persisted verbatim into models.toml (treated as a local-only
      config file, same trust model as llmw's workspace_models.toml).
    - `context_window` is read only if present as an int field. We do NOT
      reverse-engineer it from a `[1m]` suffix in `name`.
    - Unknown top-level keys and per-model keys (e.g. `is_default`,
      `schema_version`) flow into `extra` buckets and round-trip untouched.
    """
    from model_switch.importer import ImportError_ as _ImportError, import_from_path

    src_path = Path(args.path)
    if not src_path.exists():
        _die(f"{src_path} does not exist.")

    try:
        result = import_from_path(src_path)
    except _ImportError as e:
        _die(f"importing {src_path}: {e}")

    incoming = result.registry

    # Merge or replace.
    if args.merge:
        existing = load_models(paths.models_file())
        for k, v in incoming.models.items():
            existing.models[k] = v
        # Top-level extras: incoming wins, keeps backward-compat keys.
        for k, v in incoming.extra_top.items():
            existing.extra_top[k] = v
        save_models(paths.models_file(), existing)
        result_reg = existing
    else:
        save_models(paths.models_file(), incoming)
        result_reg = incoming

    # Mirror the catalog (a replace can wipe models, so reconcile also reclaims
    # providers for models that vanished) and clear single-slot agents if the
    # active model was dropped.
    _sync_catalog(result_reg)
    _clear_active_if_orphaned(result_reg)

    print(f"Imported {len(incoming.models)} model(s) from {src_path}.")


def _do_complete_models() -> None:
    """Print configured model names, one per line (completion plumbing)."""
    reg = load_models(paths.models_file())
    for name in reg.models:
        print(name)


def _do_complete_drivers() -> None:
    """Print registered driver names, one per line (completion plumbing)."""
    _ensure_default_registered()
    for name in registry.list():
        print(name)


def _do_status(args: argparse.Namespace) -> None:
    state = load_state(paths.state_file())
    reg = load_models(paths.models_file())

    print("model-switch status")
    print("----------------------")
    if not state.active_main:
        print("active main:  (none)")
    else:
        print(f"active main:  {state.active_main} "
              f"(model_name: {reg.models[state.active_main].name})")

    if args.all_drivers:
        _ensure_default_registered()
        drivers = [_resolve_driver(n) for n in registry.list()]
    else:
        drivers = [_resolve_driver(args.driver_name)]
    for driver in drivers:
        print("")
        print(f"Agent ({driver.name}) effective config in {driver.settings_path}:")
        current = driver.current()
        if not current:
            print("  (empty)")
        else:
            for k in sorted(current.keys()):
                print(f"  {k} = {current[k]}")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return _dispatch(args, parser)
    except KeyboardInterrupt:
        # A wizard interrupted mid-question must not print a traceback and,
        # more importantly, must not have written anything yet.
        ui.abort("Aborted.", code=130)


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.cmd == "init":
        _do_init()
        return 0
    if args.cmd == "model":
        if args.model_action == "add":
            _do_model_add(args)
        elif args.model_action == "list":
            _do_model_list()
        elif args.model_action == "show":
            _do_model_show(args)
        elif args.model_action == "remove":
            _do_model_remove(args)
        elif args.model_action == "use":
            _do_model_use(args)
        elif args.model_action == "import":
            _do_model_import(args)
        elif args.model_action == "align":
            return _do_model_align(args)
        return 0
    if args.cmd == "status":
        _do_status(args)
        return 0
    if args.cmd == "_complete":
        if args.what == "models":
            _do_complete_models()
        else:
            _do_complete_drivers()
        return 0

    # argparse with required=True subparsers should never let us reach here.
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
