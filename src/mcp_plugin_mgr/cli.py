"""argparse-based CLI for mcp-plugin-mgr.

The CLI manages a canonical registry of MCP servers
(~/.config/mcp-plugin-mgr/servers.toml) and applies them — translated into each
agent's vocabulary — to the registered agent drivers (Claude Code's
~/.claude.json `mcpServers`, OpenCode's opencode.json `mcp`). V1 surface is
intentionally minimal: add / list / remove, plus `presets` and `status`.

Output goes to stdout; errors to stderr. Exit codes:
  0 = success
  1 = user error (bad flag, missing field, unknown server/driver)
  2 = argparse error (unknown command / flag)
"""
import argparse
import sys
from typing import List, Optional

from mcp_plugin_mgr import paths
from mcp_plugin_mgr.drivers.base import registry
from mcp_plugin_mgr.presets import PRESETS, PresetError, get_preset
from mcp_plugin_mgr.store import (
    ServerEntry,
    ServerRegistry,
    load_servers,
    save_servers,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
)


# ---- shared helpers ---------------------------------------------------------

def _ensure_default_registered() -> None:
    """Register the built-in drivers lazily on first use.

    Lazy registration avoids import-time side effects that would create a
    driver pointed at the real ~/.claude.json (a test-isolation hazard — that
    file holds the running session's own MCP servers). Tests populate the
    registry with tmp-path drivers BEFORE the first CLI invocation.
    """
    from mcp_plugin_mgr.drivers.claude_code import ClaudeCodeMcpDriver
    from mcp_plugin_mgr.drivers.opencode import OpenCodeMcpDriver

    if "claude-code" not in registry.list():
        registry.register(ClaudeCodeMcpDriver())
    if "opencode" not in registry.list():
        registry.register(OpenCodeMcpDriver())


def _resolve_driver(name: Optional[str]):
    """Return the named driver, or the default if name is None/empty."""
    _ensure_default_registered()
    if name:
        try:
            return registry.get(name)
        except KeyError as e:
            print("Error: {}".format(e), file=sys.stderr)
            sys.exit(1)
    driver = registry.default()
    if driver is None:
        print("Error: no agent driver registered.", file=sys.stderr)
        sys.exit(1)
    return driver


def _resolve_drivers(args) -> list:
    """Resolve which driver(s) to apply to.

    Precedence:
      1. `--all-drivers` -> every registered driver.
      2. `--driver NAME` -> that single driver.
      3. Interactive TTY prompt -> comma-separated names (Enter = all).
      4. Non-TTY / no prompt -> default driver (`claude-code`).
    """
    _ensure_default_registered()
    available = registry.list()
    if args.all_drivers:
        return [_resolve_driver(n) for n in available]
    if args.driver_name:
        return [_resolve_driver(args.driver_name)]
    if sys.stdin.isatty() and available:
        print("Available drivers: {}".format(", ".join(available)))
        raw = input(
            "Apply to which driver(s)? "
            "(comma-separated, 'all' or Enter for all): "
        ).strip()
        if not raw or raw.lower() == "all":
            return [_resolve_driver(n) for n in available]
        names = [n.strip() for n in raw.split(",") if n.strip()]
        for n in names:
            if n not in available:
                print(
                    "Error: unknown driver {!r}. Available: {}".format(n, available),
                    file=sys.stderr,
                )
                sys.exit(1)
        return [_resolve_driver(n) for n in names]
    # Non-interactive (no TTY): single-driver default so CI scripts don't
    # unexpectedly write multiple agent configs.
    return [_resolve_driver(None)]


def _prompt(label: str, default=None, *, optional: bool = False):
    """Read one line from stdin (interactive only). See model_switch.cli._prompt."""
    suffix = ""
    if default is not None:
        suffix = " [{}]".format(default)
    elif optional:
        suffix = " (optional)"
    if not sys.stdin.isatty():
        if default is not None:
            return default
        if optional:
            return None
        print(
            "Error: {!r} is required (no TTY for interactive prompt). "
            "Pass it as a flag.".format(label),
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        line = input("{}{}: ".format(label, suffix))
    except EOFError:
        if default is not None:
            return default
        if optional:
            return None
        print(
            "Error: {!r} is required (input exhausted). Pass it as a flag.".format(label),
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
    return line


def _prompt_secret(label: str) -> str:
    """Read a secret from stdin WITHOUT echoing (getpass)."""
    import getpass

    if not sys.stdin.isatty():
        print(
            "Error: {} is required (no TTY for secure prompt). Pass it via --token.".format(
                label
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        value = getpass.getpass("{}: ".format(label))
    except EOFError:
        print(
            "Error: {} is required (input exhausted). Pass it via --token.".format(label),
            file=sys.stderr,
        )
        sys.exit(1)
    if value == "":
        print("Error: value is required.", file=sys.stderr)
        sys.exit(1)
    return value


def _parse_kv(items: Optional[List[str]], label: str) -> dict:
    """Parse a list of 'KEY=VALUE' strings into a dict."""
    out = {}
    for item in items or []:
        if "=" not in item:
            print(
                "Error: {} {!r} must be KEY=VALUE".format(label, item),
                file=sys.stderr,
            )
            sys.exit(1)
        k, v = item.split("=", 1)
        k = k.strip()
        if not k:
            print(
                "Error: {} has empty key in {!r}".format(label, item),
                file=sys.stderr,
            )
            sys.exit(1)
        out[k] = v
    return out


def _truncate(s, width) -> str:
    if len(s) <= width:
        return s
    if width <= 1:
        return "…"
    return s[: width - 1] + "…"


def _apply_auto_allow(name, add):
    """Pre-approve (add=True) or revoke (add=False) a server's tools in
    Claude Code permissions.allow. No-op if the list is already in the wanted
    state. Only touches the `permissions` key, preserving env/model etc.
    """
    from mcp_plugin_mgr import allow as allow_mod

    preset = get_preset(name)
    entries = allow_mod.allow_entries_for(name, preset)
    settings_path = paths.claude_settings_file()
    if add:
        added = allow_mod.add_allowed_tools(settings_path, entries)
        if added:
            print("  Pre-approved {} tool(s) in {} (Claude Code permissions.allow)".format(
                len(added), settings_path))
        else:
            print("  (permissions.allow already had these tools)")
    else:
        removed = allow_mod.remove_allowed_tools(settings_path, entries)
        if removed:
            print("  Removed {} tool(s) from {} (permissions.allow)".format(
                len(removed), settings_path))


# ---- parser construction ----------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-plugin-mgr",
        description="Manage MCP servers (e.g. Outline wiki) for Claude Code and OpenCode.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    # init
    sub.add_parser("init", help="Initialize the mcp-plugin-mgr config directory.")

    # add
    p_add = sub.add_parser("add", help="Add an MCP server (preset name or explicit flags).")
    p_add.add_argument("name", help="Server name. If it matches a preset (e.g. 'outline'), preset defaults apply.")
    p_add.add_argument("--url", default=None, help="HTTP transport: server URL.")
    p_add.add_argument(
        "--token", default=None,
        help="HTTP transport: bearer token fed into the preset's auth header. Prompted securely if omitted.",
    )
    p_add.add_argument(
        "--header", dest="headers", action="append", default=None,
        metavar="KEY=VALUE",
        help="HTTP transport: extra/raw header (repeatable). Overrides preset header keys.",
    )
    p_add.add_argument(
        "--stdio", dest="stdio", action="store_true",
        help="Declare stdio transport (for a non-preset server).",
    )
    p_add.add_argument(
        "--command", default=None,
        help="stdio transport: full command line to run, e.g. "
             "'uvx --from git+https://... some-mcp' (shlex-split into executable + args).",
    )
    p_add.add_argument(
        "--env", dest="env", action="append", default=None,
        metavar="KEY=VALUE",
        help="stdio transport: environment variable (repeatable).",
    )
    p_add.add_argument("--description", default=None, help="Free-text description.")
    p_add.add_argument("--driver", default=None, dest="driver_name",
                       help="Target agent driver (e.g. 'claude-code' or 'opencode').")
    p_add.add_argument("--all-drivers", action="store_true", dest="all_drivers",
                       help="Apply to every registered driver (skips interactive prompt).")
    p_add.add_argument("--no-apply", action="store_true", dest="no_apply",
                       help="Register in servers.toml only; don't write to agent configs yet.")
    p_add.add_argument(
        "--auto-allow", action="store_true", dest="auto_allow",
        help="Also pre-approve the server's tools in Claude Code permissions.allow "
             "(avoids the auto-mode classifier blocking large writes).",
    )
    p_add.add_argument("--force", action="store_true",
                       help="Overwrite if the name already exists in servers.toml.")

    # list
    sub.add_parser("list", help="List servers in the registry (with per-agent presence).")

    # remove
    p_rm = sub.add_parser("remove", help="Remove a server from the registry and agent configs.")
    p_rm.add_argument("name", help="Server name to remove.")
    p_rm.add_argument("--driver", default=None, dest="driver_name")
    p_rm.add_argument("--all-drivers", action="store_true", dest="all_drivers")
    p_rm.add_argument(
        "--auto-allow", action="store_true", dest="auto_allow",
        help="Also remove the server's pre-approved tools from Claude Code permissions.allow.",
    )

    # presets
    p_pre = sub.add_parser("presets", help="List built-in presets.")
    p_pre.add_argument("action", nargs="?", default="list", choices=["list"])

    # status
    p_status = sub.add_parser("status", help="Show config paths and counts.")
    p_status.add_argument("--driver", default=None, dest="driver_name")
    p_status.add_argument("--all-drivers", action="store_true", dest="all_drivers")

    # test
    p_test = sub.add_parser(
        "test",
        help="Test whether an MCP server actually responds (diagnoses connectivity / ddnsto middlebox).",
    )
    p_test.add_argument(
        "name", nargs="?", default=None,
        help="Registered server name to test (uses its transport from servers.toml).",
    )
    p_test.add_argument("--url", default=None, help="Ad-hoc: test this HTTP URL instead of a registered server.")
    p_test.add_argument(
        "--token", default=None,
        help="Ad-hoc http: bearer token (renders Authorization: Bearer <token>).",
    )
    p_test.add_argument(
        "--header", dest="headers", action="append", default=None,
        metavar="KEY=VALUE", help="Ad-hoc http: extra header (repeatable).",
    )
    p_test.add_argument("--timeout", type=int, default=10, help="Per-request timeout seconds (default 10).")

    # _complete — hidden plumbing for shell completion (no help= on purpose).
    p_complete = sub.add_parser("_complete")
    p_complete.add_argument("what", choices=["servers", "drivers", "presets"])

    return parser


# ---- dispatch ---------------------------------------------------------------

def _do_init() -> None:
    d = paths.config_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not paths.servers_file().exists():
        save_servers(paths.servers_file(), ServerRegistry())
    print("Initialized mcp-plugin-mgr config at {}".format(d))


def _build_entry(args) -> ServerEntry:
    """Resolve flags (+ optional preset) into a validated ServerEntry."""
    extra_headers = _parse_kv(args.headers, "--header")
    env = _parse_kv(args.env, "--env")
    preset = get_preset(args.name)

    if preset is not None:
        # Preset-driven. Resolve holes the preset leaves open, prompting if TTY.
        url = args.url
        if preset.transport == TRANSPORT_HTTP and preset.needs_url and not url:
            url = _prompt("{} URL".format(preset.name))
        token = args.token
        if preset.transport == TRANSPORT_HTTP and preset.needs_token and not token:
            token = _prompt_secret("{} API token".format(preset.name))
        try:
            return preset.to_entry(
                url=url, token=token,
                extra_headers=extra_headers or None,
                description=args.description,
            )
        except PresetError as e:
            print("Error: {}".format(e), file=sys.stderr)
            sys.exit(1)

    # Manual (non-preset). Determine transport from flags.
    if args.stdio or args.command:
        if not args.command:
            print("Error: stdio server requires --command", file=sys.stderr)
            sys.exit(1)
        import shlex
        try:
            parts = shlex.split(args.command)
        except ValueError as e:
            print("Error: --command {!r} is not a valid command line: {}".format(
                args.command, e), file=sys.stderr)
            sys.exit(1)
        if not parts:
            print("Error: --command is empty.", file=sys.stderr)
            sys.exit(1)
        entry = ServerEntry(
            name=args.name, transport=TRANSPORT_STDIO,
            command=parts[0], args=parts[1:],
            env=env, description=args.description,
        )
    elif args.url:
        entry = ServerEntry(
            name=args.name, transport=TRANSPORT_HTTP,
            url=args.url, headers=extra_headers, description=args.description,
        )
    else:
        print(
            "Error: could not determine transport for {!r}. Use a preset name, "
            "or pass --url (http) / --stdio --command (stdio).".format(args.name),
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        entry.validate()
    except Exception as e:  # validation error -> user error
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)
    return entry


def _do_add(args: argparse.Namespace) -> None:
    entry = _build_entry(args)

    reg = load_servers(paths.servers_file())
    if args.name in reg.servers and not args.force:
        print(
            "Error: server {!r} already exists in {}. Use --force to overwrite.".format(
                args.name, paths.servers_file()
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    reg.servers[args.name] = entry
    save_servers(paths.servers_file(), reg)

    print("Added server {!r} [{}] to registry.".format(args.name, entry.transport))
    print("  {}".format(paths.servers_file()))

    if args.no_apply:
        print("  (--no-apply: not written to agent configs)")
        return

    applied = []
    for driver in _resolve_drivers(args):
        driver.add_server(args.name, entry)
        applied.append(driver)
    for d in applied:
        print("  Wrote {} ({})".format(d.config_path, d.name))
    if args.auto_allow:
        _apply_auto_allow(args.name, add=True)
    print(
        "  Restart your agent to load the new MCP server "
        "(Claude Code: Ctrl+D then `claude`; OpenCode: restart the CLI)."
    )


def _do_list() -> None:
    _ensure_default_registered()
    reg = load_servers(paths.servers_file())
    drivers = [_resolve_driver(n) for n in registry.list()]
    if not reg.servers:
        print("(no servers configured — run `mcp-plugin-mgr add <name>` to add one)")
        return

    rows = []
    for n, e in reg.servers.items():
        present = [d.name for d in drivers if d.has_server(n)]
        rows.append((n, e.transport, _truncate(e.detail(), 48), ",".join(present) or "-"))

    names = [r[0] for r in rows]
    transports = [r[1] for r in rows]
    details = [r[2] for r in rows]
    agents = [r[3] for r in rows]
    name_w = max(max(len(s) for s in names), len("NAME"))
    trans_w = max(max(len(s) for s in transports), len("TRANSPORT"))
    detail_w = max(max(len(s) for s in details), len("DETAIL"))
    agents_w = max(max(len(s) for s in agents), len("AGENTS"))

    print(
        "  "
        + "NAME".ljust(name_w) + "  "
        + "TRANSPORT".ljust(trans_w) + "  "
        + "DETAIL".ljust(detail_w) + "  "
        + "AGENTS".ljust(agents_w)
    )
    for n, t, detail, agent in rows:
        print(
            "  "
            + n.ljust(name_w) + "  "
            + t.ljust(trans_w) + "  "
            + detail.ljust(detail_w) + "  "
            + agent
        )


def _do_remove(args: argparse.Namespace) -> None:
    reg = load_servers(paths.servers_file())
    if args.name not in reg.servers:
        print(
            "Error: server {!r} not found in {}.".format(args.name, paths.servers_file()),
            file=sys.stderr,
        )
        sys.exit(1)
    del reg.servers[args.name]
    save_servers(paths.servers_file(), reg)
    print("Removed server {!r} from registry.".format(args.name))

    removed = []
    for driver in _resolve_drivers(args):
        if driver.remove_server(args.name):
            removed.append(driver)
    for d in removed:
        print("  Removed from {} ({})".format(d.config_path, d.name))
    if not removed:
        print("  (was not present in any selected agent config)")
    if args.auto_allow:
        _apply_auto_allow(args.name, add=False)


def _do_presets() -> None:
    if not PRESETS:
        print("(no built-in presets)")
        return
    print("Built-in presets:")
    for name, p in PRESETS.items():
        needs = []
        if p.transport == TRANSPORT_HTTP:
            if p.needs_url:
                needs.append("--url")
            if p.needs_token:
                needs.append("--token")
        elif not p.command:
            needs.append("--command")
        need_s = "  needs: {}".format(", ".join(needs)) if needs else ""
        print("  {}  [{}]{}".format(name, p.transport, need_s))
        if p.description:
            print("      {}".format(p.description))


def _do_status(args: argparse.Namespace) -> None:
    _ensure_default_registered()
    reg = load_servers(paths.servers_file())
    print("mcp-plugin-mgr status")
    print("----------------------")
    print("registry: {}  ({} server(s))".format(paths.servers_file(), len(reg.servers)))
    if args.all_drivers:
        drivers = [_resolve_driver(n) for n in registry.list()]
    else:
        drivers = [_resolve_driver(args.driver_name)]
    for d in drivers:
        try:
            count = len(d.list_servers())
        except Exception:
            count = "?"
        print("Agent ({}) config: {} ({} server(s))".format(d.name, d.config_path, count))


def _do_test(args: argparse.Namespace) -> int:
    """Probe an MCP server and print a diagnosis. Returns exit code (0 ok / 1 fail)."""
    from mcp_plugin_mgr import probe

    if not args.name and not args.url:
        print(
            "Error: give a registered server name, or --url for an ad-hoc HTTP test.",
            file=sys.stderr,
        )
        return 1

    timeout = args.timeout or 10
    if args.url:
        headers = _parse_kv(args.headers, "--header")
        if args.token:
            headers.setdefault("Authorization", "Bearer " + args.token)
        print("Testing HTTP endpoint: {}".format(args.url))
        result = probe.probe_http(args.url, headers, timeout=timeout)
    else:
        reg = load_servers(paths.servers_file())
        if args.name not in reg.servers:
            print(
                "Error: server {!r} not in registry ({}).".format(
                    args.name, paths.servers_file()
                ),
                file=sys.stderr,
            )
            return 1
        entry = reg.servers[args.name]
        if entry.transport == TRANSPORT_HTTP:
            print("Testing {} (http): {}".format(args.name, entry.url))
            result = probe.probe_http(entry.url, dict(entry.headers), timeout=timeout)
        else:
            print("Testing {} (stdio): {} {}".format(
                args.name, entry.command, " ".join(entry.args)))
            result = probe.probe_stdio(
                [entry.command] + list(entry.args), dict(entry.env),
                timeout=max(timeout, 15),
            )

    # Per-plugin diagnostic overlay: the generic probe classifies by transport;
    # a preset may refine root cause / remediation for the specific service
    # (outline -> Settings→AI; memos -> Access Tokens / v0.27+). Only applies
    # when testing a registered server whose name matches a known preset.
    preset = get_preset(args.name) if args.name else None
    if preset is not None and preset.diagnose is not None:
        result = preset.diagnose(result)

    _render_probe_result(result)
    return 0 if result.ok else 1


def _render_probe_result(result) -> None:
    mark = "✓" if result.ok else "✗"
    print("{} {}".format(mark, result.summary))
    if result.server_info:
        print("  server: {}".format(result.server_info))
    if result.detail:
        for line in result.detail.splitlines():
            print("  " + line)
    if result.remediation:
        print("  fix: {}".format(result.remediation))


def _do_complete_servers() -> None:
    reg = load_servers(paths.servers_file())
    for name in reg.servers:
        print(name)


def _do_complete_drivers() -> None:
    _ensure_default_registered()
    for name in registry.list():
        print(name)


def _do_complete_presets() -> None:
    for name in PRESETS:
        print(name)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "init":
        _do_init()
        return 0
    if args.cmd == "add":
        _do_add(args)
        return 0
    if args.cmd == "list":
        _do_list()
        return 0
    if args.cmd == "remove":
        _do_remove(args)
        return 0
    if args.cmd == "presets":
        _do_presets()
        return 0
    if args.cmd == "status":
        _do_status(args)
        return 0
    if args.cmd == "test":
        return _do_test(args)
    if args.cmd == "_complete":
        if args.what == "servers":
            _do_complete_servers()
        elif args.what == "drivers":
            _do_complete_drivers()
        else:
            _do_complete_presets()
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
