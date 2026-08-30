"""Path resolution for cc-connect-mgr.

Every interesting path is env-overridable so tests (and exotic layouts)
never touch the real ~/.cc-connect, /etc/systemd, or journald-backed
verification targets. Resolution happens at call time — no import-time
freezing, matching the repo's test-isolation invariants.
"""
import os
from pathlib import Path

# Test seams: set these env vars to redirect every write below.
HOME_OVERRIDE = "CC_CONNECT_MGR_HOME"
SYSTEMD_DIR_OVERRIDE = "CC_CONNECT_MGR_SYSTEMD_DIR"
UNIT_OVERRIDE = "CC_CONNECT_MGR_UNIT"
LOG_OVERRIDE = "CC_CONNECT_MGR_LOG"

NPM_PACKAGE = "@yzr95924/llmw-connect"


def data_dir() -> Path:
    """cc-connect's config/data dir: $CC_CONNECT_MGR_HOME else ~/.cc-connect."""
    v = os.environ.get(HOME_OVERRIDE)
    return Path(v) if v else Path.home() / ".cc-connect"


def env_file() -> Path:
    return data_dir() / "env"


def config_file() -> Path:
    return data_dir() / "config.toml"


def systemd_dir() -> Path:
    v = os.environ.get(SYSTEMD_DIR_OVERRIDE)
    return Path(v) if v else Path("/etc/systemd/system")


def unit_path() -> Path:
    v = os.environ.get(UNIT_OVERRIDE)
    return Path(v) if v else systemd_dir() / "cc-connect.service"


def daemon_log() -> Path:
    """Where a manually-started (non-systemd) daemon logs."""
    v = os.environ.get(LOG_OVERRIDE)
    return Path(v) if v else Path("/tmp/cc-connect-daemon.log")


def templates_dir() -> Path:
    return Path(__file__).parent / "templates"


def template(name: str) -> Path:
    p = templates_dir() / name
    if not p.exists():  # pragma: no cover - packaging error
        raise FileNotFoundError("template not found: {}".format(p))
    return p
