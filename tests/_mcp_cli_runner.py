"""CLI test runner for mcp_plugin_mgr — mirrors tests/_cli_runner.py.

Calls `mcp_plugin_mgr.cli.main(args)` with captured stdin/stdout/stderr and
returns a SimpleNamespace with `exit_code`, `stdout`, `stderr` (stderr is also
merged into stdout so assertions on error substrings match either stream).
"""
import io
import sys
from types import SimpleNamespace


def invoke_cli(args, input=None):
    """Drive `mcp_plugin_mgr.cli.main`.

    `args` is a list of CLI args (e.g. `["list"]`).
    `input` is a string piped to stdin (one prompt per line).
    """
    from mcp_plugin_mgr.cli import main as cli_main

    saved_stdin = sys.stdin
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    sys.stdin = io.StringIO(input if input is not None else "")
    # When the test pipes scripted input via `input=`, pretend it's a TTY so
    # `_prompt` / `_prompt_secret` actually fire.
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
