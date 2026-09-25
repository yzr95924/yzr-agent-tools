"""Deep health checks for `verify --deep`: load state + runtime heartbeat.

The heartbeat file is written by the plugin itself on every context-hook
firing (single last-write-wins record, see plugins/at-import/index.ts).
Session-side plugin failures are silent (fail-open), so the heartbeat is what
turns "hook stopped firing after an OpenCode upgrade" into a deterministic
check instead of a silent absence.
"""
import json
import os
import subprocess
from pathlib import Path
from typing import List, Optional


def _data_base() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else Path.home() / ".local" / "share"


def heartbeat_file() -> Path:
    return _data_base() / "opencode-plugins" / "at-import-heartbeat.json"


def read_heartbeat() -> Optional[dict]:
    """Parsed heartbeat record; None when missing or not valid JSON.

    Callers distinguish the two via `heartbeat_file().exists()`.
    """
    p = heartbeat_file()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def current_opencode_version() -> Optional[str]:
    """`opencode --version` parsed to a bare version string; None if unavailable."""
    try:
        out = subprocess.run(
            ["opencode", "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    text = out.stdout.strip()
    if not text:
        return None
    return text.split()[-1].lstrip("v") or None


def plugin_list_contains(plugin_id: str) -> Optional[bool]:
    """Whether `opencode plugin list` shows the plugin as loaded.

    None = opencode unavailable (check skipped); False = reachable but the
    plugin is absent from the list, i.e. it failed to load. Note: this may
    start the background service if none is running.
    """
    try:
        out = subprocess.run(
            ["opencode", "plugin", "list"], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        cols = line.split()
        # First column is the plugin id; for bundled plugins it equals the
        # directory name (id === name by our convention).
        if cols and cols[0] == plugin_id:
            return True
    return False


def judge(facts: dict) -> List[str]:
    """Decision table over collected facts; empty list = healthy.

    facts keys:
      plugin_mtime      float epoch seconds of the installed index.ts (or None)
      heartbeat         parsed record dict (or None)
      heartbeat_exists  bool — file present (distinguishes corrupt vs missing)
      heartbeat_mtime   float epoch seconds (or None)
      opencode_version  current `opencode --version` (or None = unknown)
      listed            bool — in `opencode plugin list` (or None = skipped)
    """
    problems = []  # type: List[str]
    hb = facts.get("heartbeat")
    if hb is None:
        if facts.get("heartbeat_exists"):
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
        current = facts.get("opencode_version")
        hb_version = hb.get("opencodeVersion")
        if current and hb_version and hb_version != current:
            problems.append(
                "heartbeat is from opencode {0}, current is {1} — upgrade drift; "
                "run any opencode command once and re-verify".format(hb_version, current)
            )
        plugin_mtime = facts.get("plugin_mtime")
        heartbeat_mtime = facts.get("heartbeat_mtime")
        if plugin_mtime is not None and heartbeat_mtime is not None and heartbeat_mtime < plugin_mtime:
            problems.append(
                "plugin file changed after the last heartbeat — new build not yet "
                "proven; run any opencode command once and re-verify"
            )
    listed = facts.get("listed")
    if listed is False:
        problems.append("plugin not in `opencode plugin list` — load failed")
    return problems
