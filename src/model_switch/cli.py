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
  1 = user error (bad flag, missing model, missing env var)
  2 = argparse error (unknown command / flag)
"""
import argparse
import datetime
import os
import sys
from pathlib import Path
from typing import List, Optional

from model_switch import paths
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


def _resolve_driver(name: Optional[str]):
    """Return the named driver, or the default if name is None/empty."""
    _ensure_default_registered()
    if name:
        try:
            return registry.get(name)
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    driver = registry.default()
    if driver is None:
        print("Error: no agent driver registered.", file=sys.stderr)
        sys.exit(1)
    return driver


def _resolve_drivers(args) -> list:
    """Resolve which driver(s) to apply to.

    Precedence:
      1. `--all-drivers` → every registered driver.
      2. `--driver NAME` → that single driver.
      3. Interactive TTY prompt → comma-separated names (default: `claude-code`).
      4. Non-TTY / no prompt → default driver (`claude-code`).
    """
    _ensure_default_registered()
    available = registry.list()
    if args.all_drivers:
        return [_resolve_driver(n) for n in available]
    if args.driver_name:
        return [_resolve_driver(args.driver_name)]
    if sys.stdin.isatty() and available:
        # Interactive prompt — defaults to claude-code if user just hits Enter.
        default = "claude-code" if "claude-code" in available else available[0]
        print(f"Available drivers: {', '.join(available)}")
        raw = input(
            f"Apply to which driver(s)? (comma-separated, default: {default}): "
        ).strip()
        if not raw:
            return [_resolve_driver(default)]
        names = [n.strip() for n in raw.split(",") if n.strip()]
        for n in names:
            if n not in available:
                print(f"Error: unknown driver {n!r}. Available: {available}",
                      file=sys.stderr)
                sys.exit(1)
        return [_resolve_driver(n) for n in names]
    return [_resolve_driver(None)]  # default


def _resolve_api_key(model) -> str:
    """Resolve the API key for `model`.

    Priority: env var named by `model.api_key_env` → `model.api_key`.
    Fail with a clear message if neither is set.
    """
    env_val = os.environ.get(model.api_key_env)
    if env_val:
        return env_val
    if model.api_key:
        return model.api_key
    print(
        f"Error: API key for model {model.model_id!r} is not available.\n"
        f"  Either set the env var:  export {model.api_key_env}=<your-key>\n"
        f"  Or store the key in models.toml under {model.api_key_env!r}/api_key.",
        file=sys.stderr,
    )
    sys.exit(1)


def _now_iso() -> str:
    # Python 3.12+ deprecated `datetime.utcnow()`. Use timezone-aware UTC
    # and emit "Z" suffix to match the on-disk format.
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
    except AttributeError:
        # Python 3.7 compat: `timezone.utc` exists but `utcnow()` is fine.
        return datetime.datetime.utcnow().isoformat() + "Z"
    return now.isoformat().replace("+00:00", "Z")


def _prompt(label: str, default=None, *, type_=str, optional: bool = False):
    """Read one line from stdin (interactive only).

    Mirrors `typer.prompt` behavior: only prompts when stdin is a TTY. In
    non-interactive contexts (piped input, CI, tests), if the option is
    missing AND required, we exit with a clear error. If optional, return
    `None` (or `default`).

    Do NOT pass secrets — input is echoed to the terminal. We only prompt
    for env var names, model identifiers, and descriptions, never the
    API key itself.
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
        print(
            f"Error: {label!r} is required (no TTY for interactive prompt). "
            f"Pass it as a flag.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        line = input(f"{label}{suffix}: ")
    except EOFError:
        # Stream ran out (e.g. test piped fewer answers than prompts).
        # Match typer's behavior: fall back to the default if there's one.
        if default is not None:
            return default
        if optional:
            return None
        print(
            f"Error: {label!r} is required (input exhausted). "
            f"Pass it as a flag.",
            file=sys.stderr,
        )
        sys.exit(1)
    if line == "":
        if default is not None:
            return default
        if optional:
            return None
        print("Error: value is required.", file=sys.stderr)
        sys.exit(1)
    return type_(line)


# ---- parser construction ----------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model-switch",
        description="Switch Anthropic-compatible models for Claude Code and OpenCode.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    # init
    p_init = sub.add_parser("init", help="Initialize the model-switch config directory.")

    # model
    p_model = sub.add_parser("model", help="Manage model definitions.")
    model_sub = p_model.add_subparsers(dest="model_action", required=True, metavar="ACTION")

    p_add = model_sub.add_parser("add", help="Add a new model definition.")
    p_add.add_argument("name", help="Local nickname for this model.")
    p_add.add_argument("--base-url", default=None, help="Upstream API base URL.")
    p_add.add_argument(
        "--api-key-env", default=None,
        help="Name of the env var holding the API key.",
    )
    p_add.add_argument(
        "--model-name", default=None,
        help="Model identifier expected by upstream (bare id, no context suffix).",
    )
    p_add.add_argument("--description", default=None, help="Free-text description.")
    p_add.add_argument(
        "--context-window", type=int, default=None,
        help="Max input tokens (e.g. 200000 or 1000000 for 1M-context variants).",
    )

    p_list = model_sub.add_parser("list", help="List all configured models.")

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

    # status
    p_status = sub.add_parser("status", help="Show current state + effective agent config.")
    p_status.add_argument("--driver", default=None, dest="driver_name")
    p_status.add_argument("--all-drivers", action="store_true", dest="all_drivers")

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
    """
    base_url = args.base_url or _prompt("Upstream API base URL")
    api_key_env = args.api_key_env or _prompt("Env var holding the API key")
    model_name = args.model_name or _prompt(
        "Model identifier (bare id, no context suffix)"
    )
    if args.context_window is None:
        context_window = _prompt(
            "Context window in tokens (press Enter for default 200000)",
            default=200000, type_=int,
        )
    else:
        context_window = args.context_window
    description = args.description
    if not description:
        description = _prompt("Description", optional=True)

    reg = load_models(paths.models_file())
    if args.name in reg.models:
        print(f"Error: model {args.name!r} already exists.", file=sys.stderr)
        sys.exit(1)
    reg.models[args.name] = ModelEntry(
        model_id=args.name,
        name=model_name,
        base_url=base_url,
        api_key_env=api_key_env,
        context_window=context_window,
        description=description,
    )
    save_models(paths.models_file(), reg)
    print(f"Added model {args.name!r}.")


def _do_model_list() -> None:
    reg = load_models(paths.models_file())
    state = load_state(paths.state_file())
    if not reg.models:
        print("(no models configured — run `model-switch model add` to add one)")
        return
    name_w = max(len(n) for n in reg.models)
    for n, m in reg.models.items():
        markers = []
        if state.active_main == n:
            markers.append("active")
        marker = " [" + ",".join(markers) + "]" if markers else ""
        print(f"  {n.ljust(name_w)}  {m.name}{marker}")


def _do_model_show(name: str) -> None:
    reg = load_models(paths.models_file())
    if name not in reg.models:
        print(f"Error: model {name!r} not found.", file=sys.stderr)
        sys.exit(1)
    m = reg.models[name]
    print(f"name:           {name}")
    print(f"base_url:       {m.base_url}")
    print(f"api_key_env:    {m.api_key_env}")
    print(f"model_name:     {m.name}")
    if m.context_window is not None:
        print(f"context_window: {m.context_window}")
    if m.description:
        print(f"description:    {m.description}")


def _do_model_remove(name: str) -> None:
    reg = load_models(paths.models_file())
    if name not in reg.models:
        print(f"Error: model {name!r} not found.", file=sys.stderr)
        sys.exit(1)
    del reg.models[name]
    save_models(paths.models_file(), reg)
    print(f"Removed model {name!r}.")


def _do_model_use(args: argparse.Namespace) -> None:
    reg = load_models(paths.models_file())
    if args.name not in reg.models:
        print(f"Error: model {args.name!r} not found.", file=sys.stderr)
        sys.exit(1)

    main_model = reg.models[args.name]

    api_key = _resolve_api_key(main_model)

    for driver in _resolve_drivers(args):
        driver.apply(model=main_model, api_key=api_key)

    state = load_state(paths.state_file())
    state.active_main = args.name
    state.last_updated = _now_iso()
    save_state(paths.state_file(), state)

    print(f"Switched to {args.name!r}.")
    print(f"  Wrote {driver.settings_path}")
    print("  Restart your agent (Claude Code: Ctrl+D, then `claude`; OpenCode: restart the CLI) to take effect.")


def _do_model_import(args: argparse.Namespace) -> None:
    """Import model definitions from an llmw-format TOML file.

    Conversion rules (see `model_switch.importer`):
    - `api_key` (raw credential) is NEVER written to disk by model-switch.
      We derive a stable env var name from `model_id` and require the user
      to export the raw key in their shell.
    - `context_window` is read only if present as an int field. We do NOT
      reverse-engineer it from a `[1m]` suffix in `name`.
    - Unknown top-level keys and per-model keys (e.g. `is_default`,
      `schema_version`) flow into `extra` buckets and round-trip untouched.
    """
    from model_switch.importer import ImportError_ as _ImportError, import_from_path

    src_path = Path(args.path)
    if not src_path.exists():
        print(f"Error: {src_path} does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        result = import_from_path(src_path)
    except _ImportError as e:
        print(f"Error importing {src_path}: {e}", file=sys.stderr)
        sys.exit(1)

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
    else:
        save_models(paths.models_file(), incoming)

    print(f"Imported {len(incoming.models)} model(s) from {src_path}.")
    if result.env_vars_needed:
        print("")
        print("Override keys via env vars if you prefer (otherwise models.toml is the source):")
        for model_id, env_var in result.env_vars_needed:
            print(f"  export {env_var}=<your-key>   # optional override for '{model_id}'")


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
        if driver is None:
            continue
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
        return 0
    if args.cmd == "status":
        _do_status(args)
        return 0

    # argparse with required=True subparsers should never let us reach here.
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
