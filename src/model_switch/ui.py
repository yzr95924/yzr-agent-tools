"""Interactive prompts for the model-switch CLI.

Plain line-based `input()` prompts — no termios, no curses. Prompts never
block a script: they fail fast on a non-TTY stdin, so callers must pass the
equivalent argument instead.
"""
import sys
from typing import Any, NoReturn, Sequence


def abort(message: str, code: int = 1) -> NoReturn:
    """Print ``message`` to stderr and exit — the single abort path."""
    print(message, file=sys.stderr)
    sys.exit(code)


def fail(message) -> NoReturn:
    """``Error: <message>`` to stderr + exit 1 — the CLI's failure channel."""
    abort("Error: {}".format(message))


def ask(prompt: str) -> str:
    """Read one free-form line; EOF aborts cleanly (exit 1)."""
    try:
        return input(prompt)
    except EOFError:
        fail("input exhausted — aborted, nothing written.")


def pick_one(title: str, items: Sequence[Any]) -> int:
    """Show a numbered menu and return the 0-based index picked."""
    if not sys.stdin.isatty():
        fail("the interactive picker needs a TTY — pass the value as an "
             "argument instead.")
    if not items:
        fail("nothing to pick from.")
    if title:
        print(title)
    for i, item in enumerate(items, 1):
        print("  {}) {}".format(i, item))
    while True:
        raw = ask("Pick a number: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return int(raw) - 1
        print("  Enter a number between 1 and {}.".format(len(items)))


def confirm(question: str, *, default: bool = True) -> bool:
    """Ask a yes/no question; Enter takes ``default``."""
    if not sys.stdin.isatty():
        fail("a confirmation needs a TTY — pass --yes to answer it in "
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
