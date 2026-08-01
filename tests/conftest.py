"""Project-wide pytest fixtures.

The autouse fixtures below enforce the basic principle:
    TESTS MUST NEVER WRITE TO THE USER'S REAL CONFIG FILES.

Any test that would touch `~/.claude/settings.json`, model-switch's own
~/.config/model-switch/, html-mcp's ~/.config/html-mcp/, etc., would
wedge the current Claude Code session. So:

  1. Every test runs with HOME pointed at a tmp dir.
  2. model-switch's path functions are redirected to tmp.
  3. html-mcp's path functions are redirected to tmp.
  4. The claude-code driver singleton in the registry is replaced with
     one that points at a tmp settings file.
  5. Before the test exits, the real `~/.claude/settings.json` (and
     any other tracked real configs) is verified to be untouched
     (mtime + content hash match pre-test snapshot).

Tests that intentionally need to exercise real paths (e.g. a smoke
e2e) should skip these fixtures explicitly with
`@pytest.mark.no_isolation` — but that's not implemented yet because
no such test exists.
"""
import hashlib
import os
from pathlib import Path

import pytest

from model_switch import paths
from model_switch.drivers.base import registry
from model_switch.drivers.claude_code import ClaudeCodeDriver
from model_switch.drivers.opencode import OpenCodeDriver


# Real paths we MUST NOT touch during tests. Tracked for integrity checks.
REAL_CLAUDE_SETTINGS = Path(os.path.expanduser("~")) / ".claude" / "settings.json"
REAL_YZR_CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    / "model-switch"
)
REAL_HTML_MCP_CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    / "html-mcp"
)
# OpenCode's real global config (may hold the user's live custom providers).
_REAL_CFG_BASE = Path(
    os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
)
REAL_OPENCODE_CONFIG = _REAL_CFG_BASE / "opencode" / "opencode.json"


def _sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _isolate_yzr_state(tmp_path: Path, monkeypatch, request):
    """Hard isolation for every test. NEVER touch real user configs.

    Opt out with `@pytest.mark.no_isolation` for tests that intentionally
    exercise the real path-resolution behavior (e.g. test_paths.py).
    """
    if "no_isolation" in request.keywords:
        yield None
        return

    # Snapshot real configs so we can verify they were not modified.
    snapshot = {}
    for label, p in (("claude_settings", REAL_CLAUDE_SETTINGS),
                     ("yzr_config_dir", REAL_YZR_CONFIG_DIR),
                     ("html_mcp_config_dir", REAL_HTML_MCP_CONFIG_DIR),
                     ("opencode_config", REAL_OPENCODE_CONFIG)):
        snapshot[label] = {
            "exists": p.exists(),
            "mtime": p.stat().st_mtime if p.exists() else None,
            "sha256": _sha256(p) if p.exists() and p.is_file() else None,
        }

    # Redirect model-switch's own paths into tmp.
    cfg_dir = tmp_path / "model-switch-cfg"
    cfg_dir.mkdir()
    models_p = cfg_dir / "models.toml"
    state_p = cfg_dir / "state.toml"
    settings_p = tmp_path / ".claude" / "settings.json"
    opencode_p = tmp_path / ".config" / "opencode" / "opencode.json"

    monkeypatch.setattr(paths, "config_dir", lambda: cfg_dir)
    monkeypatch.setattr(paths, "models_file", lambda: models_p)
    monkeypatch.setattr(paths, "state_file", lambda: state_p)
    monkeypatch.setattr(paths, "opencode_config_file", lambda: opencode_p)

    # Replace any pre-existing claude-code driver in the registry with
    # one pointing at the tmp settings path. (Earlier auto-registration
    # would have created one pointed at the real ~/.claude/settings.json.)
    registry._drivers["claude-code"] = ClaudeCodeDriver(settings_path=settings_p)
    # Same for opencode: its default path now resolves to the real
    # ~/.config/opencode/opencode.json, so lazy registration MUST be
    # pre-empted with a tmp-path driver.
    registry._drivers["opencode"] = OpenCodeDriver(settings_path=opencode_p)

    # Redirect html-mcp's own paths into tmp. Import lazily so importing
    # this conftest does not pull in html_mcp when only model_switch is
    # being exercised (e.g. in environments that haven't installed the
    # tool yet).
    from html_mcp import paths as html_mcp_paths

    html_cfg_dir = tmp_path / "html-mcp-cfg"
    html_cfg_dir.mkdir()
    html_cfg_p = html_cfg_dir / "config.toml"
    html_nginx_p = html_cfg_dir / "nginx.conf.example"
    monkeypatch.setattr(html_mcp_paths, "config_dir", lambda: html_cfg_dir)
    monkeypatch.setattr(html_mcp_paths, "config_file", lambda: html_cfg_p)
    monkeypatch.setattr(html_mcp_paths, "nginx_example_file", lambda: html_nginx_p)

    paths_dict = {
        "config_dir": cfg_dir,
        "models": models_p,
        "state": state_p,
        "settings": settings_p,
        "opencode": opencode_p,
        "html_mcp_config_dir": html_cfg_dir,
        "html_mcp_config_file": html_cfg_p,
        "html_mcp_nginx_example": html_nginx_p,
    }
    yield paths_dict

    # Integrity check: real configs must be byte-identical to the snapshot.
    for label, p in (("claude_settings", REAL_CLAUDE_SETTINGS),
                     ("yzr_config_dir", REAL_YZR_CONFIG_DIR),
                     ("html_mcp_config_dir", REAL_HTML_MCP_CONFIG_DIR),
                     ("opencode_config", REAL_OPENCODE_CONFIG)):
        snap = snapshot[label]
        if snap["exists"]:
            assert p.exists(), (
                f"Test deleted real config at {p}!"
            )
            # If the snapshot is a file (not a directory), check mtime +
            # sha256. Directory snapshots don't snapshot content — only
            # existence — since `models.toml` is the per-test write target.
            if snap["sha256"] is not None:
                assert p.stat().st_mtime == snap["mtime"], (
                    f"Test modified mtime of real config {p}"
                )
                assert _sha256(p) == snap["sha256"], (
                    f"Test modified content of real config {p} — "
                    f"this would have wedged the user's Claude Code session!"
                )