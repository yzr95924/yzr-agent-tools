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
from typing import Any, Dict, List, NoReturn, Optional

from model_switch import catalog, paths
from model_switch.drivers.base import registry
from model_switch.store import (
    ModelEntry,
    Registry,
    State,
    load_models,
    load_state,
    save_models,
    save_state,
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
    codes); ``message`` may be an exception or a plain string.
    """
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


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
        raw = input(
            "Apply to which driver(s)? "
            "(comma-separated, 'all' or Enter for all): "
        ).strip()
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
    try:
        line = input(f"{label}{suffix}: ")
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
    return type_(line)


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
    p_add.add_argument("name", help="Local nickname for this model.")
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
             "share base_url and api_key.",
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

    model_sub.add_parser("list", help="List all configured models.")

    p_show = model_sub.add_parser("show", help="Show details of one model.")
    p_show.add_argument("name")

    p_rm = model_sub.add_parser("remove", help="Remove a model definition.")
    p_rm.add_argument("name")

    p_use = model_sub.add_parser("use", help="Activate a model.")
    p_use.add_argument("name", help="Model name to activate.")
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
    """Add a new model definition.

    Any required option omitted from the CLI is prompted for interactively,
    so you can run `model-switch model add mymodel` and answer the prompts.
    Fields OpenCode's catalog cache can supply (context window, reasoning,
    variant tiers, modalities) are derived from it; `--no-catalog` opts out,
    `--catalog-provider` pins the provider entry when several match.
    """
    base_url = args.base_url or _prompt("Upstream API base URL")
    api_key = args.api_key or _prompt_secret("API key")
    model_name = args.model_name or _prompt(
        "Model identifier (bare id, no context suffix)", default=args.name,
    )
    derived = _derive_or_report(model_name, base_url,
                                args.catalog_provider, args.no_catalog)
    if args.context_window is not None:
        context_window = args.context_window
    elif derived.get("context_window"):
        context_window = derived["context_window"]
    else:
        context_window = _prompt(
            "Context window in tokens (press Enter to skip)",
            optional=True, type_=int,
        )
    description = args.description
    if not description:
        description = _prompt("Description", optional=True)

    reg = load_models(paths.models_file())
    if args.name in reg.models:
        _die(f"model {args.name!r} already exists.")
    extra = {}
    if args.provider:
        extra["provider"] = args.provider
    if derived.get("reasoning"):
        extra["reasoning"] = True
    if derived.get("variants"):
        extra["variants"] = derived["variants"]
    if derived.get("modalities"):
        extra["modalities"] = derived["modalities"]
    reg.models[args.name] = ModelEntry(
        model_id=args.name,
        name=model_name,
        base_url=base_url,
        api_key=api_key,
        context_window=context_window,
        description=description,
        extra=extra,
    )
    save_models(paths.models_file(), reg)
    # Mirror the catalog so the new model is immediately available in agents
    # that hold one (OpenCode's picker). Single-slot agents (claude-code) are
    # untouched until the next `model use`.
    _sync_catalog(reg)
    print(f"Added model {args.name!r}.")


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


def _do_model_show(name: str) -> None:
    reg = load_models(paths.models_file())
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


def _do_model_remove(name: str) -> None:
    reg = load_models(paths.models_file())
    if name not in reg.models:
        _die(f"model {name!r} not found.")
    del reg.models[name]
    save_models(paths.models_file(), reg)
    # Reconcile the catalog (removed model's provider + key vanish from
    # OpenCode) and clear the single-slot agent if the removed model was active.
    _sync_catalog(reg)
    _clear_active_if_orphaned(reg)
    print(f"Removed model {name!r}.")


def _do_model_use(args: argparse.Namespace) -> None:
    reg = load_models(paths.models_file())
    if args.name not in reg.models:
        _die(f"model {args.name!r} not found.")

    # Variant presets are materialized here (in memory) so every driver sees
    # plain `variants` dicts; models.toml keeps the preset + reference form.
    expanded = {m.model_id: m for m in _expand_or_die(reg)}
    main_model = expanded[args.name]

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
    state.active_main = args.name
    state.last_updated = _now_iso()
    save_state(paths.state_file(), state)

    print(f"Switched to {args.name!r}.")
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

    if args.cmd == "init":
        _do_init()
        return 0
    if args.cmd == "model":
        if args.model_action == "add":
            _do_model_add(args)
        elif args.model_action == "list":
            _do_model_list()
        elif args.model_action == "show":
            _do_model_show(args.name)
        elif args.model_action == "remove":
            _do_model_remove(args.name)
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
