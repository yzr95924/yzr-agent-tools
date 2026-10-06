"""Deep health checks for `verify --deep`: load state + runtime heartbeat.

The heartbeat file is written by each plugin itself on every context-hook
firing (single last-write-wins record, see plugins/at-import/index.ts). The
path is derived from the plugin id, so checking one plugin never weighs
another plugin's record.

Session-side plugin failures are silent (fail-open), so the heartbeat is what
turns "hook stopped firing after an OpenCode upgrade" into a deterministic
check instead of a silent absence.
"""
import json
import os
import subprocess
from pathlib import Path
from typing import List, NamedTuple, Optional

from opencode_plugins import registry


class Facts(NamedTuple):
    plugin_mtime: Optional[float]  # installed index.ts
    heartbeat: Optional[dict]  # parsed record; None = missing or corrupt
    heartbeat_exists: bool  # separates "corrupt" from "never fired"
    heartbeat_mtime: Optional[float]
    opencode_version: Optional[str]  # None = opencode not on PATH
    listed: Optional[bool]  # None = live check skipped


def _data_base() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else Path.home() / ".local" / "share"


def heartbeat_file(plugin_id: str) -> Path:
    return _data_base() / "opencode-plugins" / (plugin_id + "-heartbeat.json")


def read_heartbeat(plugin_id: str) -> Optional[dict]:
    """Parsed heartbeat record; None when missing or not valid JSON.

    Callers distinguish the two via `heartbeat_file(plugin_id).exists()`.
    """
    p = heartbeat_file(plugin_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _run_opencode(args: List[str], timeout: int) -> Optional[str]:
    """stdout of `opencode <args...>`; None when unavailable or failed."""
    try:
        out = subprocess.run(
            ["opencode"] + args, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def current_opencode_version() -> Optional[str]:
    """`opencode --version` parsed to a bare version string; None if unavailable."""
    out = _run_opencode(["--version"], 30)
    if out is None:
        return None
    text = out.strip()
    if not text:
        return None
    return text.split()[-1].lstrip("v") or None


def plugin_list_contains(plugin_id: str) -> Optional[bool]:
    """Whether `opencode plugin list` shows the plugin as loaded.

    None = opencode unavailable (check skipped); False = reachable but the
    plugin is absent from the list, i.e. it failed to load. Note: this may
    start the background service if none is running.
    """
    out = _run_opencode(["plugin", "list"], 120)
    if out is None:
        return None
    for line in out.splitlines():
        cols = line.split()
        # First column is the plugin id; for bundled plugins it equals the
        # directory name (id === name by our convention).
        if cols and cols[0] == plugin_id:
            return True
    return False


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def collect_facts(plugin_id: str) -> Facts:
    """Gather everything judge() weighs for one installed plugin."""
    hb_path = heartbeat_file(plugin_id)
    version = current_opencode_version()
    return Facts(
        plugin_mtime=_mtime(registry.target_dir(plugin_id) / "index.ts"),
        heartbeat=read_heartbeat(plugin_id),
        heartbeat_exists=hb_path.exists(),
        heartbeat_mtime=_mtime(hb_path),
        opencode_version=version,
        listed=plugin_list_contains(plugin_id) if version else None,
    )


def judge(facts: Facts) -> List[str]:
    """Decision table over collected facts; empty list = healthy."""
    problems = []  # type: List[str]
    hb = facts.heartbeat
    if hb is None:
        if facts.heartbeat_exists:
            problems.append("heartbeat file exists but is corrupt")
        else:
            problems.append(
                "no heartbeat — context hook has never fired (plugin broken, "
                "or freshly deployed and not yet exercised)"
            )
    else:
        err = hb.get("error")
        if err:
            problems.append("last hook firing recorded an error: {0}".format(err))
        current = facts.opencode_version
        hb_version = hb.get("opencodeVersion")
        if current and hb_version and hb_version != current:
            problems.append(
                "heartbeat is from opencode {0}, current is {1} — upgrade drift; "
                "run any opencode command once and re-verify".format(hb_version, current)
            )
        plugin_mtime = facts.plugin_mtime
        heartbeat_mtime = facts.heartbeat_mtime
        if plugin_mtime is not None and heartbeat_mtime is not None and heartbeat_mtime < plugin_mtime:
            problems.append(
                "plugin file changed after the last heartbeat — new build not yet "
                "proven; run any opencode command once and re-verify"
            )
    if facts.listed is False:
        problems.append("plugin not in `opencode plugin list` — load failed")
    return problems
