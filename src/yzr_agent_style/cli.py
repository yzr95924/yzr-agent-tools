"""argparse-based CLI for yzr-agent-style.

Installs / removes the tool's marker block (containing the bundled template)
in each agent's global instruction file. Two commands only:

  install   ensure every target file carries the template (create / append /
            update its marker block)
  uninstall remove the marker block from every target file (deleting the file
            if nothing remains)

Exit codes: 0 = success; 1 = user error (missing template); 2 = argparse
error (unknown command).
"""
import argparse
import sys
from typing import List, Optional

from yzr_agent_style import markers, paths

# (agent, display path, resolver). Resolvers are lambdas that look up the
# accessor ON THE MODULE at call time — capturing the function object here
# would freeze it at import time and defeat test monkeypatching.
TARGETS = (
    ("claude-code", "~/.claude/CLAUDE.md", lambda: paths.claude_md_file()),
    ("opencode", "~/.config/opencode/AGENTS.md", lambda: paths.opencode_agents_file()),
    ("qoder-cli", "~/.qoder/AGENTS.md", lambda: paths.qoder_agents_file()),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yzr-agent-style",
        description=(
            "Install/remove a global instruction template in each agent's "
            "rules file (Claude Code / OpenCode / Qoder CLI)."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")
    sub.add_parser("install", help="Write the template into every target file.")
    sub.add_parser("uninstall", help="Remove the template block from every target file.")
    return parser


def _read_template() -> str:
    template = paths.template_file()
    if not template.exists():
        print("Error: template not found: {0}".format(template), file=sys.stderr)
        sys.exit(1)
    return template.read_text(encoding="utf-8")


def _do_install() -> None:
    template = _read_template()
    for name, display, resolver in TARGETS:
        path = resolver()
        if not path.parent.exists():
            print("skip {0}: {1} parent dir missing ({2})".format(name, display, path.parent))
            continue
        status = markers.install_block(path, template)
        print("{0} [{1}]: {2}".format(name, status, path))


def _do_uninstall() -> None:
    for name, display, resolver in TARGETS:
        path = resolver()
        status = markers.remove_block(path)
        print("{0} [{1}]: {2}".format(name, status, path))


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "install":
        _do_install()
        return 0
    if args.cmd == "uninstall":
        _do_uninstall()
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())