"""CLI test runner — the test-side replacement for typer's CliRunner.

Calls `model_switch.cli.main(args)` with captured stdin/stdout/stderr and
returns a SimpleNamespace with `exit_code`, `stdout`, `stderr` (the
legacy `CliRunner` merged stderr into stdout; we do the same so existing
assertions on error substrings still match).
"""
import io
import sys
from types import SimpleNamespace


def invoke_cli(args, input=None):
    """Drive `model_switch.cli.main` the way typer's CliRunner used to.

    `args` is a list of CLI args (e.g. `["model", "list"]`).
    `input` is a string piped to stdin (one prompt per line).
    """
    # Imported lazily so the autouse fixture's per-test setup runs first.
    from model_switch.cli import main as cli_main

    saved_stdin = sys.stdin
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    sys.stdin = io.StringIO(input if input is not None else "")
    # When the test pipes scripted input via `input=`, pretend it's a TTY
    # so `_prompt` actually fires (matches typer's CliRunner semantics).
    sys.stdin.isatty = lambda: input is not None  # type: ignore[attr-defined]
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    rc = 1
    try:
        try:
            rc = cli_main(args)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    finally:
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
        sys.stdin, sys.stdout, sys.stderr = saved_stdin, saved_stdout, saved_stderr
    return SimpleNamespace(exit_code=rc, stdout=out + err, stderr=err)
