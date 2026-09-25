"""argparse-based CLI for opencode-plugins.

Manages the personal OpenCode plugins bundled in this repo (source of truth:
src/opencode_plugins/plugins/). Install copies them into OpenCode's global
plugins dir and registers a `./plugins/<name>` entry in the global
opencode.json; uninstall reverses both. Status is derived — no state file.

Commands:
  list                 bundled plugins + install/registration status
  install [names...]   copy source -> global target + register (idempotent)
  uninstall [names...] deregister + remove target dir
  sync [names...]      re-copy after editing the bundled source
  verify [names...]    integrity check (hashes + registration + config JSON)
  _complete <what>     hidden plumbing for shell completions

Exit codes: 0 = success; 1 = user error / verify failure; 2 = argparse error.
"""
import argparse
import sys
from typing import List, Optional

from opencode_plugins import jsonutil, paths, registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opencode-plugins",
        description=(
            "Maintain personal OpenCode plugins: install/update/uninstall "
            "the plugins bundled in this repo into OpenCode's global plugin "
            "location and register them in its opencode.json."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    sub.add_parser("list", help="Show bundled plugins and their status.")

    for verb, help_text in (
        ("install", "Copy plugin sources into OpenCode and register them."),
        ("uninstall", "Deregister and remove installed plugins."),
        ("sync", "Re-copy plugin sources after editing them."),
        ("verify", "Check install integrity (hash + registration)."),
    ):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument(
            "names",
            nargs="*",
            metavar="NAME",
            help="Plugin name(s); default: all bundled plugins.",
        )
        if verb == "verify":
            p.add_argument(
                "--deep",
                action="store_true",
                help=(
                    "Also check live health: plugin listed by `opencode plugin list` "
                    "and the runtime heartbeat (hook actually fired under the current "
                    "opencode version). May start the background service."
                ),
            )

    p_complete = sub.add_parser("_complete", help=argparse.SUPPRESS)
    p_complete.add_argument("what", choices=["plugins"])
    return parser


def _resolve_names(args_names: List[str]) -> List[str]:
    """Names for install/sync/verify: must be bundled (default: all)."""
    if args_names:
        known = registry.bundled_names()
        for n in args_names:
            if n not in known:
                raise registry.RegistryError(
                    "Unknown plugin {0!r}. Bundled: {1}".format(n, ", ".join(known) or "(none)")
                )
        return list(args_names)
    return registry.bundled_names()


def _do_list() -> int:
    # JSONC coexistence: OpenCode accepts both files; this tool manages plain
    # opencode.json only. A real config living in .jsonc would silently split
    # registration, so surface it instead of guessing.
    sibling = paths.opencode_config_file().with_suffix(".jsonc")
    if sibling.exists():
        print(
            "note: {0} exists alongside {1}; this tool only manages the latter".format(
                sibling, paths.opencode_config_file()
            ),
            file=sys.stderr,
        )
    names = registry.bundled_names()
    orphans = registry.orphan_names()
    if not names and not orphans:
        print("no bundled plugins")
        return 0
    width = max([len(n) for n in names + orphans] or [1])
    for name in names:
        st = registry.status(name)
        reg = "registered" if registry.is_registered(name) else "NOT-REGISTERED"
        print("{0:<{1}}  {2:<10}  {3}".format(name, width, st, reg))
    for name in orphans:
        print("{0:<{1}}  {2:<10}".format(name, width, "orphan"))
    return 0


# Explicit map, not getattr dispatch.
_ACTIONS = {
    "install": registry.install,
    "uninstall": registry.uninstall,
    "sync": registry.sync,
}


def _apply(action: str, names: List[str]) -> int:
    fn = _ACTIONS[action]
    for name in names:
        print("{0}: {1}".format(name, fn(name)))
    return 0


def _do_verify(names: List[str], deep: bool = False) -> int:
    from opencode_plugins import deep as deep_mod

    rc = 0
    for name in names:
        problems = []  # type: List[str]
        st = registry.status(name)
        if st != "installed":
            problems.append("install state: {0}".format(st))
        if not registry.is_registered(name):
            problems.append("not registered in {0}".format(paths.opencode_config_file()))
        notes = []  # type: List[str]
        if deep and not problems:
            version = deep_mod.current_opencode_version()
            if version is None:
                notes.append("opencode not on PATH — live checks skipped")
            hb_path = deep_mod.heartbeat_file()
            problems.extend(
                deep_mod.judge({
                    "plugin_mtime": _mtime(registry.target_dir(name) / "index.ts"),
                    "heartbeat": deep_mod.read_heartbeat(),
                    "heartbeat_exists": hb_path.exists(),
                    "heartbeat_mtime": _mtime(hb_path),
                    "opencode_version": version,
                    "listed": deep_mod.plugin_list_contains(name) if version else None,
                })
            )
        for note in notes:
            print("{0}: note: {1}".format(name, note))
        if problems:
            rc = 1
            print("{0}: FAIL ({1})".format(name, "; ".join(problems)))
        else:
            print("{0}: OK{1}".format(name, " (deep)" if deep else ""))
    return rc


def _mtime(path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "list":
            return _do_list()
        if args.cmd in ("install", "sync", "verify"):
            names = _resolve_names(args.names)
            if args.cmd == "verify":
                return _do_verify(names, deep=getattr(args, "deep", False))
            return _apply(args.cmd, names)
        if args.cmd == "uninstall":
            # Uninstall also accepts orphan names (installed dirs no longer
            # backed by a bundled source).
            names = args.names or registry.bundled_names()
            return _apply("uninstall", names)
        if args.cmd == "_complete":
            for name in registry.bundled_names():
                print(name)
            return 0
    except (registry.RegistryError, jsonutil.JsonError) as e:
        print("Error: {0}".format(e), file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
