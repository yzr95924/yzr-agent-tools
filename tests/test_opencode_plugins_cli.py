"""Tests for opencode_plugins (bundled-plugin manager).

The autouse isolation fixture redirects paths.opencode_config_file /
plugins_target_dir / bundled_plugins_dir to tmp, so these tests drive the
real CLI and registry against fake sources without touching the live
~/.config/opencode (opencode.json integrity is asserted by conftest).
"""
import json

import pytest

from opencode_plugins import jsonutil, paths, registry

from _op_cli_runner import invoke_cli as run


# ---- fixtures helpers -------------------------------------------------------

def _bundle(name: str, content: str = "// plugin source v1\n") -> None:
    """Create one fake bundled plugin (dir with index.ts) under tmp."""
    d = paths.bundled_plugins_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.ts").write_text(content, encoding="utf-8")


def _config() -> dict:
    p = paths.opencode_config_file()
    if not p.exists():
        return {}
    return json.loads(p.read_text())


# ---- list -------------------------------------------------------------------

def test_list_empty():
    r = run(["list"])
    assert r.exit_code == 0
    assert "no bundled plugins" in r.stdout


def test_list_shows_missing_then_installed_then_drift():
    _bundle("demo")
    r = run(["list"])
    assert "demo" in r.stdout and "missing" in r.stdout and "NOT-REGISTERED" in r.stdout

    run(["install", "demo"])
    out = run(["list"]).stdout
    assert "installed" in out and "registered" in out

    (paths.bundled_plugins_dir() / "demo" / "index.ts").write_text("// v2\n")
    assert "drift" in run(["list"]).stdout


def test_list_reports_orphans():
    # installed dir without a bundled source (plugin removed from the repo)
    target = paths.plugins_target_dir() / "gone"
    target.mkdir(parents=True)
    (target / "index.ts").write_text("x\n")
    out = run(["list"]).stdout
    assert "gone" in out and "orphan" in out


# ---- install ----------------------------------------------------------------

def test_install_unknown_name_errors():
    r = run(["install", "nope"])
    assert r.exit_code == 1
    assert "Unknown plugin" in r.stdout


def test_install_copies_and_registers_and_bootstraps_schema():
    _bundle("demo")
    r = run(["install", "demo"])
    assert r.exit_code == 0, r.stdout

    assert (paths.plugins_target_dir() / "demo" / "index.ts").is_file()
    cfg = _config()
    assert cfg["plugins"] == ["./plugins/demo"]
    assert cfg["$schema"] == "https://opencode.ai/config.json"


def test_install_is_idempotent_no_duplicate_entry():
    _bundle("demo")
    run(["install", "demo"])
    run(["install", "demo"])
    assert _config()["plugins"] == ["./plugins/demo"]


def test_install_preserves_unrelated_config_and_other_plugin_entries():
    paths.opencode_config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.opencode_config_file().write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "model": "yzr/x",
        "providers": {"a": {"package": "p"}},
        "plugins": ["opencode-someone-else", "-removed-me", {"package": "obj-form"}],
    }))
    _bundle("demo")
    r = run(["install", "demo"])
    assert r.exit_code == 0, r.stdout

    cfg = _config()
    assert cfg["model"] == "yzr/x"
    assert cfg["providers"] == {"a": {"package": "p"}}
    assert cfg["plugins"] == ["opencode-someone-else", "-removed-me", {"package": "obj-form"}, "./plugins/demo"]


def test_install_recognizes_absolute_entry_as_registered():
    _bundle("demo")
    paths.opencode_config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.opencode_config_file().write_text(json.dumps(
        {"plugins": [str(paths.plugins_target_dir() / "demo")]}
    ))
    assert registry.is_registered("demo")


# ---- sync -------------------------------------------------------------------

def test_sync_recopies_drifted_source():
    _bundle("demo")
    run(["install", "demo"])
    (paths.bundled_plugins_dir() / "demo" / "index.ts").write_text("// v2\n")
    r = run(["sync", "demo"])
    assert r.exit_code == 0
    assert "updated" in r.stdout
    assert (paths.plugins_target_dir() / "demo" / "index.ts").read_text() == "// v2\n"
    assert run(["sync", "demo"]).stdout.count("up-to-date") == 1


# ---- uninstall --------------------------------------------------------------

def test_uninstall_removes_dir_and_deregisters_preserving_others():
    _bundle("demo")
    paths.plugins_target_dir().mkdir(parents=True, exist_ok=True)
    cfg = {"plugins": ["someone-else", "./plugins/demo"]}
    paths.opencode_config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.opencode_config_file().write_text(json.dumps(cfg))
    (paths.plugins_target_dir() / "demo").mkdir()

    r = run(["uninstall", "demo"])
    assert r.exit_code == 0, r.stdout
    assert not (paths.plugins_target_dir() / "demo").exists()
    assert _config()["plugins"] == ["someone-else"]


def test_uninstall_absent():
    r = run(["uninstall", "demo"])
    assert r.exit_code == 0
    assert "absent" in r.stdout


def test_uninstall_orphan_by_name():
    target = paths.plugins_target_dir() / "gone"
    target.mkdir(parents=True)
    (target / "index.ts").write_text("x\n")
    r = run(["uninstall", "gone"])
    assert r.exit_code == 0
    assert not target.exists()


# ---- verify -----------------------------------------------------------------

def test_verify_ok_then_fail_on_drift():
    _bundle("demo")
    run(["install", "demo"])
    r = run(["verify", "demo"])
    assert r.exit_code == 0 and "OK" in r.stdout

    (paths.plugins_target_dir() / "demo" / "index.ts").write_text("tampered\n")
    r = run(["verify", "demo"])
    assert r.exit_code == 1
    assert "FAIL" in r.stdout and "drift" in r.stdout


def test_verify_fails_on_missing_registration():
    _bundle("demo")
    run(["install", "demo"])
    paths.opencode_config_file().write_text(json.dumps({"plugins": []}))
    r = run(["verify", "demo"])
    assert r.exit_code == 1
    assert "not registered" in r.stdout


# ---- json config robustness (#1) -------------------------------------------

def test_read_json_rejects_jsonc_comments():
    import pytest
    from opencode_plugins.jsonutil import JsonError

    p = paths.opencode_config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{\n  // JSONC comment\n  "plugins": []\n}', encoding="utf-8")
    with pytest.raises(JsonError) as e:
        jsonutil.read_json(p)
    assert "not plain JSON" in str(e.value)


def test_cli_bad_config_fails_cleanly_no_traceback():
    _bundle("demo")
    p = paths.opencode_config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{oops", encoding="utf-8")
    r = run(["install", "demo"])
    assert r.exit_code == 1
    assert "Error:" in r.stdout and "not plain JSON" in r.stdout
    assert "Traceback" not in r.stdout


def test_cli_list_notes_jsonc_coexistence():
    _bundle("demo")
    p = paths.opencode_config_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.with_suffix(".jsonc").write_text("{}", encoding="utf-8")
    r = run(["list"])
    assert r.exit_code == 0
    assert "opencode.jsonc exists alongside" in r.stdout
    assert "demo" in r.stdout


# ---- _complete --------------------------------------------------------------

def test_complete_lists_bundled():
    _bundle("at-import")
    _bundle("zzz")
    r = run(["_complete", "plugins"])
    assert r.stdout.split() == ["at-import", "zzz"]


# ---- real bundled sources ---------------------------------------------------

def test_bundled_at_import_source_present():
    """The shipped at-import plugin must exist with an index.ts (the tmp
    bundle redirect hides it, so consult the real package dir)."""
    import pathlib
    real = pathlib.Path(registry.__file__).parent / "plugins" / "at-import" / "index.ts"
    assert real.is_file()
    text = real.read_text(encoding="utf-8")
    # dependency-free: the loader accepts a plain default export (probed on
    # OpenCode 2.0.15); importing the authoring package would need
    # node_modules resolution from the plugin dir.
    assert 'from "@opencode/plugin"' not in text
    assert 'from "@opencode-ai/plugin"' not in text
    assert "context" in text
