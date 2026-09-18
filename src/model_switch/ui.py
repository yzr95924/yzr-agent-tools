"""Numbered menus and confirmations for the interactive CLI.

Plain line-based `input()` prompts — no termios, no curses — mirroring
mcp-plugin-mgr's interaction style: usable over ssh, inside pipes and under
test. Menus and confirmations never block a script: they fail fast on a
non-TTY stdin, so the caller must pass the equivalent argument instead.

Selections abort on EOF (a piped session ran out of answers) before anything
is written, so a half-answered wizard can never leave a partial config.
"""
import sys
from typing import Any, Callable, List, NoReturn, Optional, Sequence

# More rows than this and a menu stops being readable; the caller is expected
# to offer a narrower search instead (the hidden count is printed).
MENU_MAX = 20


def abort(message: str, code: int = 1) -> NoReturn:
    """Print ``message`` to stderr and exit — the single abort path.

    Every user-facing stop (bad input, a stream that ran out, a declined
    confirmation) goes through here, so exit codes and message shape stay
    uniform across the CLI and this module.
    """
    print(message, file=sys.stderr)
    sys.exit(code)


def _fail(message) -> NoReturn:
    abort("Error: {}".format(message))


def ask(prompt: str) -> str:
    """Read one free-form line; EOF aborts cleanly (exit 1)."""
    try:
        return input(prompt)
    except EOFError:
        _fail("input exhausted — aborted, nothing written.")


def pick_one(title: str, items: Sequence[Any], render: Callable[[Any], str],
             *, default: Optional[int] = None,
             allow_back: bool = False) -> Optional[int]:
    """Show a numbered menu and return the 0-based index picked.

    Enter takes ``default`` (print the 1-based number in the prompt); ``b``
    returns ``None`` when ``allow_back`` — the caller re-prompts (e.g. to
    refine a search). Anything else re-asks. More than `MENU_MAX` items are
    truncated with a hint to narrow the list.
    """
    if not sys.stdin.isatty():
        _fail("the interactive picker needs a TTY — pass the value as an "
              "argument instead.")
    if not items:
        _fail("nothing to pick from.")
    shown: List[Any] = list(items)[:MENU_MAX]
    if default is not None and not 0 <= default < len(shown):
        _fail("default index {} is out of range (menu shows {} row(s))".format(
            default, len(shown)))
    if title:
        print(title)
    width = len(str(len(shown)))
    for i, item in enumerate(shown, 1):
        print("  {:>{w}}) {}".format(i, render(item), w=width))
    hidden = len(items) - len(shown)
    if hidden:
        print("  … and {} more — narrow the search to see them.".format(hidden))
    suffix = " [{}]".format(default + 1) if default is not None else ""
    if allow_back:
        suffix += " ('b' = back)"
    while True:
        raw = ask("Pick a number{}: ".format(suffix)).strip()
        if raw == "" and default is not None:
            return default
        if allow_back and raw.lower() in ("b", "back"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(shown):
            return int(raw) - 1
        extras = " or 'b'" if allow_back else ""
        if hidden:
            extras += " — {} hidden row(s), narrow the search".format(hidden)
        print("  Enter a number between 1 and {}{}.".format(len(shown), extras))


def confirm(question: str, *, default: bool = True) -> bool:
    """Ask a yes/no question; Enter takes ``default``.

    TTY-only: callers decide *whether* to ask (the CLI gates on its ``--yes``
    flag and non-interactive discipline) — a confirmation must never be
    answered silently on someone's behalf.
    """
    if not sys.stdin.isatty():
        _fail("a confirmation needs a TTY — pass --yes to answer it in "
              "advance.")
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        raw = ask("{}{}".format(question, suffix)).strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer 'y' or 'n'.")
