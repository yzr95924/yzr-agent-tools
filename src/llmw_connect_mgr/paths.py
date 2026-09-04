"""Path resolution for llmw-connect-mgr.

Every interesting path is env-overridable so tests (and exotic layouts)
never touch the real ~/.cc-connect, /etc/systemd, or journald-backed
verification targets. Resolution happens at call time — no import-time
freezing, matching the repo's test-isolation invariants.
"""
import os
from pathlib import Path

# Test seams: set these env vars to redirect every write below.
HOME_OVERRIDE = "LLMW_CONNECT_MGR_HOME"
SYSTEMD_DIR_OVERRIDE = "LLMW_CONNECT_MGR_SYSTEMD_DIR"
UNIT_OVERRIDE = "LLMW_CONNECT_MGR_UNIT"
LOG_OVERRIDE = "LLMW_CONNECT_MGR_LOG"

NPM_PACKAGE = "@yzr95924/llmw-connect"

# Fork binary since v1.5.0-llmw.4; only the fork npm package installs a
# bin by this name, so which() alone proves provenance.
BINARY_NAME = "llmw-connect"
# Fork builds <=llmw.3 installed `cc-connect` — a name the upstream npm
# package also uses, so it keeps the `--version` llmw-marker check.
LEGACY_BINARY_NAME = "cc-connect"

UNIT_NAME = "llmw-connect"
LEGACY_UNIT_NAME = "cc-connect"


def data_dir() -> Path:
    """llmw-connect's config/data dir: $LLMW_CONNECT_MGR_HOME else ~/.cc-connect
    (the daemon's own discovery path is unchanged by the fork's bin rename)."""
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
    return Path(v) if v else systemd_dir() / (UNIT_NAME + ".service")


def legacy_unit_path() -> Path:
    """Pre-rename unit (cc-connect.service); migrated away on install."""
    return systemd_dir() / (LEGACY_UNIT_NAME + ".service")


def daemon_log() -> Path:
    """Where a manually-started (non-systemd) daemon logs."""
    v = os.environ.get(LOG_OVERRIDE)
    return Path(v) if v else Path("/tmp/llmw-connect-daemon.log")


def templates_dir() -> Path:
    return Path(__file__).parent / "templates"


def template(name: str) -> Path:
    p = templates_dir() / name
    if not p.exists():  # pragma: no cover - packaging error
        raise FileNotFoundError("template not found: {}".format(p))
    return p
