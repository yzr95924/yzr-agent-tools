"""CLI test runner for opencode_plugins — mirrors tests/_mcp_cli_runner.py.

Calls `opencode_plugins.cli.main(args)` with captured stdout/stderr and
returns SimpleNamespace(exit_code, stdout, stderr) (stderr merged into
stdout so error-substring assertions match either stream).
"""
import io
import sys
from types import SimpleNamespace


def invoke_cli(args, input=None):
    from opencode_plugins.cli import main as cli_main

    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
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
        sys.stdout, sys.stderr = saved_stdout, saved_stderr
    return SimpleNamespace(exit_code=rc, stdout=out + err, stderr=err)
