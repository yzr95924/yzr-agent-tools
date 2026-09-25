"""Bundled plugin sources + derived install status + install operations.

State is derived entirely from the filesystem and the `plugins` array of
OpenCode's global config — there is no registry file to drift.

`plugins` entries OpenCode accepts for a directory: a plain string path
(or a {package, options} object; a leading `-` means remove). We register
bundled plugins as the relative form `./plugins/<name>`, which OpenCode
resolves against the directory of the config file that declares it — i.e.
exactly `plugins_target_dir()/<name>`.
"""
import hashlib
import shutil
from pathlib import Path
from typing import Dict, List

from opencode_plugins import jsonutil, paths


class RegistryError(Exception):
    """User-facing registry failure (unknown plugin name, bad config...)."""


SCHEMA_URL = "https://opencode.ai/config.json"


def bundled_names() -> List[str]:
    """Plugin names shipped with this tool (subdirs holding an index.ts)."""
    base = paths.bundled_plugins_dir()
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir() and (d / "index.ts").is_file())


def source_dir(name: str) -> Path:
    return paths.bundled_plugins_dir() / name


def target_dir(name: str) -> Path:
    return paths.plugins_target_dir() / name


def entry_for(name: str) -> str:
    """The config entry the installer registers for `name`."""
    return "./plugins/" + name


def _file_hashes(root: Path) -> Dict[str, str]:
    out = {}  # type: Dict[str, str]
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def status(name: str) -> str:
    """Install state of one bundled plugin.

    missing    — not installed
    drift      — installed but differs from the bundled source (needs sync)
    installed  — installed and byte-identical to the bundled source
    """
    dst = target_dir(name)
    if not dst.exists():
        return "missing"
    return "installed" if _file_hashes(source_dir(name)) == _file_hashes(dst) else "drift"


def orphan_names() -> List[str]:
    """Installed target dirs that no longer have a bundled source — leftovers
    of plugins removed from this repo. Reported by `list`, removed by
    `uninstall <name>`."""
    base = paths.plugins_target_dir()
    if not base.is_dir():
        return []
    bundled = set(bundled_names())
    return sorted(d.name for d in base.iterdir() if d.is_dir() and d.name not in bundled)


def configured_entries() -> List:
    config = jsonutil.read_json(paths.opencode_config_file())
    plugins = config.get("plugins")
    return plugins if isinstance(plugins, list) else []


def _entry_target(entry) -> str:
    """The package/path string of a `plugins` entry (string or object form)."""
    if isinstance(entry, dict):
        pkg = entry.get("package")
        return pkg if isinstance(pkg, str) else ""
    return entry if isinstance(entry, str) else ""


def is_registered(name: str) -> bool:
    """True when a `plugins` entry points at this tool's install target."""
    return any(_entry_matches(e, name) for e in configured_entries())


def _entry_matches(entry, name: str) -> bool:
    text = _entry_target(entry)
    if not text:
        return False
    dst = str(target_dir(name))
    return text == entry_for(name) or text.rstrip("/") == dst or text.endswith("://" + dst)


def _set_registered(name: str, want: bool) -> bool:
    """Ensure the config's `plugins` array contains (or lacks) our entry.

    Returns True when a write happened. Only `plugins` is mutated; every
    other key (providers, mcp, model, ...) round-trips untouched.
    """
    config_path = paths.opencode_config_file()
    config = jsonutil.read_json(config_path)
    raw = config.get("plugins")
    entries = raw if isinstance(raw, list) else []

    if want:
        if any(_entry_matches(e, name) for e in entries):
            return False
        entries = entries + [entry_for(name)]
    else:
        kept = [e for e in entries if not _entry_matches(e, name)]
        if len(kept) == len(entries):
            return False
        entries = kept

    config["plugins"] = entries
    if want and "$schema" not in config and not config_path.exists():
        config["$schema"] = SCHEMA_URL
    jsonutil.atomic_write_json(config_path, config)
    return True


def install(name: str) -> str:
    """Copy the bundled source over the install target and register it.

    Returns one of: "installed", "updated".
    """
    if name not in bundled_names():
        raise RegistryError("Unknown plugin (not bundled): {0}".format(name))
    was = status(name)
    dst = target_dir(name)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir(name), dst)
    _set_registered(name, True)
    return "updated" if was in ("drift", "installed") else "installed"


def uninstall(name: str) -> str:
    """Deregister and remove the installed target dir."""
    dst = target_dir(name)
    removed_config = _set_registered(name, False)
    removed_dir = False
    if dst.is_dir():
        shutil.rmtree(dst)
        removed_dir = True
    if not removed_config and not removed_dir:
        return "absent"
    return "removed"


def sync(name: str) -> str:
    """Re-copy the bundled source when it drifted; refresh registration."""
    if name not in bundled_names():
        raise RegistryError("Unknown plugin (not bundled): {0}".format(name))
    if status(name) == "installed":
        _set_registered(name, True)
        return "up-to-date"
    return install(name)
