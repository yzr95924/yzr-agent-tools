"""Tests for verify --deep: heartbeat judgment + live-check plumbing.

`deep.judge` is a pure decision table covered directly; the CLI path is
exercised with monkeypatched subprocess helpers (never a real `opencode`)
and a tmp heartbeat file (conftest redirects deep.heartbeat_file).
"""
import json
import os
import time

from opencode_plugins import deep, paths, registry

from _op_cli_runner import invoke_cli as run


def _bundle(name: str = "at-import") -> None:
    d = paths.bundled_plugins_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.ts").write_text("// src\n", encoding="utf-8")


def _write_heartbeat(**over) -> None:
    record = {
        "ts": int(time.time() * 1000),
        "opencodeVersion": "2.0.15",
        "location": "/somewhere",
        "injected": ["/somewhere/MEMORY/MEMORY.md"],
        "error": None,
    }
    record.update(over)
    p = deep.heartbeat_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record) + "\n", encoding="utf-8")
    # heartbeat mtime must reflect "fired just now" for the fresh-case tests
    now = time.time()
    os.utime(p, (now, now))


# ---- judge: pure decision table ---------------------------------------------

def _facts(**over):
    facts = {
        "plugin_mtime": 1000.0,
        "heartbeat": {"opencodeVersion": "2.0.15", "error": None},
        "heartbeat_exists": True,
        "heartbeat_mtime": 2000.0,
        "opencode_version": "2.0.15",
        "listed": True,
    }
    facts.update(over)
    return facts


def test_judge_healthy():
    assert deep.judge(_facts()) == []


def test_judge_missing_heartbeat():
    problems = deep.judge(_facts(heartbeat=None, heartbeat_exists=False, heartbeat_mtime=None))
    assert len(problems) == 1 and "never fired" in problems[0]


def test_judge_corrupt_heartbeat():
    problems = deep.judge(_facts(heartbeat=None))
    assert len(problems) == 1 and "corrupt" in problems[0]


def test_judge_recorded_error():
    problems = deep.judge(_facts(heartbeat={"opencodeVersion": "2.0.15", "error": "boom"}))
    assert any("recorded an error: boom" in p for p in problems)


def test_judge_version_drift():
    problems = deep.judge(_facts(opencode_version="2.1.0"))
    assert any("upgrade drift" in p for p in problems)


def test_judge_version_unknown_skips_drift_check():
    assert deep.judge(_facts(opencode_version=None)) == []


def test_judge_stale_heartbeat_vs_plugin():
    problems = deep.judge(_facts(heartbeat_mtime=500.0))
    assert any("not yet proven" in p for p in problems)


def test_judge_not_listed():
    problems = deep.judge(_facts(listed=False))
    assert any("load failed" in p for p in problems)


def test_judge_list_unknown_skips():
    assert deep.judge(_facts(listed=None)) == []


# ---- CLI: verify --deep with faked externals ---------------------------------

def test_verify_deep_healthy(monkeypatch):
    _bundle()
    run(["install"])
    _write_heartbeat()
    monkeypatch.setattr(deep, "current_opencode_version", lambda: "2.0.15")
    monkeypatch.setattr(deep, "plugin_list_contains", lambda _id: True)
    r = run(["verify", "--deep"])
    assert r.exit_code == 0, r.stdout
    assert "OK (deep)" in r.stdout


def test_verify_deep_unproven_after_sync(monkeypatch):
    _bundle()
    run(["install"])
    # heartbeat written, then the installed plugin file is touched afterwards
    _write_heartbeat()
    target = paths.plugins_target_dir() / "at-import" / "index.ts"
    future = time.time() + 60
    os.utime(target, (future, future))
    monkeypatch.setattr(deep, "current_opencode_version", lambda: "2.0.15")
    monkeypatch.setattr(deep, "plugin_list_contains", lambda _id: True)
    r = run(["verify", "--deep"])
    assert r.exit_code == 1
    assert "not yet proven" in r.stdout


def test_verify_deep_no_opencode_skips_live_checks(monkeypatch):
    _bundle()
    run(["install"])
    _write_heartbeat()
    monkeypatch.setattr(deep, "current_opencode_version", lambda: None)
    monkeypatch.setattr(deep, "plugin_list_contains", lambda _id: None)
    r = run(["verify", "--deep"])
    assert r.exit_code == 0, r.stdout
    assert "opencode not on PATH" in r.stdout


def test_verify_deep_not_listed(monkeypatch):
    _bundle()
    run(["install"])
    _write_heartbeat()
    monkeypatch.setattr(deep, "current_opencode_version", lambda: "2.0.15")
    monkeypatch.setattr(deep, "plugin_list_contains", lambda _id: False)
    r = run(["verify", "--deep"])
    assert r.exit_code == 1
    assert "load failed" in r.stdout


def test_verify_shallow_never_calls_externals(monkeypatch):
    _bundle()
    run(["install"])

    def _boom(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("shallow verify must not shell out")

    monkeypatch.setattr(deep, "current_opencode_version", _boom)
    monkeypatch.setattr(deep, "plugin_list_contains", _boom)
    r = run(["verify"])
    assert r.exit_code == 0 and "OK" in r.stdout
