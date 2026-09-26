"""End-to-end CLI tests for mcp_plugin_mgr (add / list / remove / presets / status).

The autouse isolation fixture redirects paths.* to tmp and pre-registers
tmp-path drivers, so these tests drive the real CLI without ever touching the
live ~/.claude.json (which holds this session's own MCP servers).
"""
import json

import pytest

from mcp_plugin_mgr import paths
from mcp_plugin_mgr.store import load_servers

from _mcp_cli_runner import invoke_cli as run


# ---- add: preset -----------------------------------------------------------

def test_add_outline_preset_applies_to_all_drivers():
    r = run(["add", "outline", "--url", "https://my/mcp", "--token", "tok", "--all-drivers"])
    assert r.exit_code == 0, r.stdout

    reg = load_servers(paths.servers_file())
    assert reg.servers["outline"].headers == {"Authorization": "Bearer tok"}

    cj = json.loads(paths.claude_json_file().read_text())
    assert cj["mcpServers"]["outline"] == {
        "type": "http", "url": "https://my/mcp",
        "headers": {"Authorization": "Bearer tok"},
    }

    oc = json.loads(paths.opencode_config_file().read_text())
    assert oc["mcp"]["servers"]["outline"] == {
        "type": "remote", "url": "https://my/mcp", "disabled": False,
        "headers": {"Authorization": "Bearer tok"},
    }

    # qodercli is the third default driver — --all-drivers fans out to it too,
    # rendering http with type: http (same key name `mcpServers` as Claude Code
    # but a different file: ~/.qoder/settings.json).
    qd = json.loads(paths.qoder_settings_file().read_text())
    assert qd["mcpServers"]["outline"] == {
        "url": "https://my/mcp", "type": "http",
        "headers": {"Authorization": "Bearer tok"},
    }


def test_add_outline_interactive_prompts_url_and_token():
    # --all-drivers skips the driver-selection prompt; only url+token are prompted.
    r = run(["add", "outline", "--all-drivers"], input="https://my/mcp\ntok\n")
    assert r.exit_code == 0, r.stdout
    cj = json.loads(paths.claude_json_file().read_text())
    assert cj["mcpServers"]["outline"]["headers"] == {"Authorization": "Bearer tok"}


def test_add_memos_preset_applies_to_all_drivers():
    # Memos is the same Streamable-HTTP + bearer shape as Outline.
    r = run([
        "add", "memos", "--url", "https://memos.example.com/mcp",
        "--token", "memos_tok", "--all-drivers",
    ])
    assert r.exit_code == 0, r.stdout

    cj = json.loads(paths.claude_json_file().read_text())
    assert cj["mcpServers"]["memos"] == {
        "type": "http", "url": "https://memos.example.com/mcp",
        "headers": {"Authorization": "Bearer memos_tok"},
    }
    oc = json.loads(paths.opencode_config_file().read_text())
    assert oc["mcp"]["servers"]["memos"] == {
        "type": "remote", "url": "https://memos.example.com/mcp", "disabled": False,
        "headers": {"Authorization": "Bearer memos_tok"},
    }


# ---- add: manual -----------------------------------------------------------

def test_add_manual_http_with_header():
    r = run([
        "add", "myhttp", "--url", "https://srv/mcp",
        "--header", "Authorization=Bearer xyz", "--all-drivers",
    ])
    assert r.exit_code == 0, r.stdout
    cj = json.loads(paths.claude_json_file().read_text())
    assert cj["mcpServers"]["myhttp"] == {
        "type": "http", "url": "https://srv/mcp",
        "headers": {"Authorization": "Bearer xyz"},
    }


def test_add_manual_stdio_with_command_string():
    # --command takes the full command line; shlex-split into executable + args.
    r = run([
        "add", "mystd", "--stdio", "--command", "uvx --from X run",
        "--all-drivers",
    ])
    assert r.exit_code == 0, r.stdout
    cj = json.loads(paths.claude_json_file().read_text())
    assert cj["mcpServers"]["mystd"] == {
        "type": "stdio", "command": "uvx",
        "args": ["--from", "X", "run"], "env": {},
    }
    oc = json.loads(paths.opencode_config_file().read_text())
    # OpenCode combines executable + args into one command array.
    assert oc["mcp"]["servers"]["mystd"]["command"] == ["uvx", "--from", "X", "run"]


def test_add_manual_stdio_missing_command_errors():
    r = run(["add", "mystd", "--stdio", "--all-drivers"])
    assert r.exit_code == 1
    assert "requires --command" in r.stdout


def test_add_non_preset_without_transport_errors():
    r = run(["add", "orphan", "--all-drivers"])
    assert r.exit_code == 1
    assert "could not determine transport" in r.stdout


# ---- add: scoping / overwrite ----------------------------------------------

def test_add_driver_opencode_only_skips_claude():
    r = run(["add", "outline", "--url", "https://x", "--token", "t", "--driver", "opencode"])
    assert r.exit_code == 0, r.stdout
    assert paths.opencode_config_file().exists()
    # claude-code config was never written.
    assert not paths.claude_json_file().exists()


def test_add_unknown_driver_errors():
    r = run(["add", "outline", "--url", "https://x", "--token", "t", "--driver", "nope"])
    assert r.exit_code == 1
    assert "Unknown agent driver" in r.stdout


def test_add_no_apply_registers_but_skips_agent_configs():
    r = run(["add", "outline", "--url", "https://x", "--token", "t", "--no-apply"])
    assert r.exit_code == 0, r.stdout
    assert "outline" in load_servers(paths.servers_file()).servers
    assert not paths.claude_json_file().exists()
    assert not paths.opencode_config_file().exists()


def test_add_duplicate_without_force_errors():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--all-drivers"])
    r = run(["add", "outline", "--url", "https://y", "--token", "u", "--all-drivers"])
    assert r.exit_code == 1
    assert "already exists" in r.stdout


def test_add_force_overwrites():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--all-drivers"])
    r = run([
        "add", "outline", "--url", "https://y", "--token", "u",
        "--force", "--all-drivers",
    ])
    assert r.exit_code == 0, r.stdout
    cj = json.loads(paths.claude_json_file().read_text())
    assert cj["mcpServers"]["outline"]["url"] == "https://y"


def test_add_force_warns_on_drift_before_overwriting():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--driver", "claude-code"])
    cj = paths.claude_json_file()
    data = json.loads(cj.read_text())
    data["mcpServers"]["outline"]["timeout"] = 30000
    cj.write_text(json.dumps(data, indent=2) + "\n")

    r = run(["add", "outline", "--url", "https://y", "--token", "u",
             "--force", "--driver", "claude-code"])
    assert r.exit_code == 0, r.stdout
    assert "drift" in r.stdout
    assert "timeout" in r.stdout
    assert "timeout" not in json.loads(cj.read_text())["mcpServers"]["outline"]


# ---- list / remove / presets / status --------------------------------------

def test_list_empty_prints_hint():
    r = run(["list"])
    assert r.exit_code == 0
    assert "no servers configured" in r.stdout


def test_list_shows_servers_and_agent_presence():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--driver", "claude-code"])
    r = run(["list"])
    assert r.exit_code == 0
    assert "outline" in r.stdout
    assert "http" in r.stdout


def test_remove_deletes_from_registry_and_agents():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--all-drivers"])
    r = run(["remove", "outline", "--all-drivers"])
    assert r.exit_code == 0, r.stdout
    assert "outline" not in load_servers(paths.servers_file()).servers
    cj = json.loads(paths.claude_json_file().read_text())
    assert "outline" not in cj.get("mcpServers", {})


def test_remove_unknown_errors():
    r = run(["remove", "ghost", "--all-drivers"])
    assert r.exit_code == 1
    assert "not found" in r.stdout


def test_presets_lists_outline_and_memos():
    r = run(["presets"])
    assert r.exit_code == 0
    assert "outline" in r.stdout
    assert "memos" in r.stdout


def test_status_runs():
    r = run(["status", "--all-drivers"])
    assert r.exit_code == 0
    assert "mcp-plugin-mgr status" in r.stdout


# ---- disable / enable -------------------------------------------------------

def _snapshot(*paths_):
    return {str(p): p.read_bytes() for p in paths_ if p.exists()}


def test_disable_then_enable_roundtrips_without_reconfig():
    run(["add", "memos", "--url", "https://memos.example.com/mcp",
         "--token", "memos_tok", "--all-drivers"])
    cj, oc, qd = (paths.claude_json_file(), paths.opencode_config_file(),
                  paths.qoder_settings_file())
    before = _snapshot(cj, oc, qd)
    assert before  # sanity: all three agents were written

    r = run(["disable", "memos", "--all-drivers"])
    assert r.exit_code == 0, r.stdout
    assert load_servers(paths.servers_file()).servers["memos"].enabled is False
    # Per-agent result is named in the output (opencode and qodercli share
    # the `disabled` vocabulary).
    assert "opencode: disabled=true" in r.stdout
    assert "qodercli: disabled=true" in r.stdout

    # opencode: native flag, entry and its other keys stay in place.
    assert json.loads(oc.read_text())["mcp"]["servers"]["memos"]["disabled"] is True
    assert json.loads(oc.read_text())["mcp"]["servers"]["memos"]["url"] == "https://memos.example.com/mcp"
    # claude-code / qodercli: no native global flag (claude) or disabled marker.
    assert "memos" not in json.loads(cj.read_text()).get("mcpServers", {})
    assert json.loads(qd.read_text())["mcpServers"]["memos"]["disabled"] is True

    # Re-enable from the registry alone — no --url/--token needed.
    r = run(["enable", "memos", "--all-drivers"])
    assert r.exit_code == 0, r.stdout
    assert _snapshot(cj, oc, qd) == before
    assert "enabled" not in paths.servers_file().read_text()


def test_disable_unknown_server_errors():
    r = run(["disable", "ghost", "--all-drivers"])
    assert r.exit_code == 1
    assert "not found" in r.stdout


def test_enable_unknown_server_errors():
    r = run(["enable", "ghost", "--all-drivers"])
    assert r.exit_code == 1
    assert "not found" in r.stdout


def test_disable_no_apply_only_touches_registry():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--all-drivers"])
    before = _snapshot(paths.claude_json_file())
    r = run(["disable", "outline", "--no-apply"])
    assert r.exit_code == 0, r.stdout
    assert load_servers(paths.servers_file()).servers["outline"].enabled is False
    assert _snapshot(paths.claude_json_file()) == before


def test_disable_without_tty_writes_only_default_driver():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--all-drivers"])
    r = run(["disable", "outline"])  # no --driver/--all-drivers, no TTY
    assert r.exit_code == 0, r.stdout
    cj = json.loads(paths.claude_json_file().read_text())
    assert "outline" not in cj.get("mcpServers", {})
    # Other drivers untouched: still enabled.
    oc = json.loads(paths.opencode_config_file().read_text())
    assert oc["mcp"]["servers"]["outline"]["disabled"] is False


def test_disable_warns_on_drift_but_continues():
    run(["add", "memos", "--url", "https://memos.example.com/mcp",
         "--token", "t", "--all-drivers"])
    cj = paths.claude_json_file()
    data = json.loads(cj.read_text())
    # Simulate a hand edit that only exists in the agent config.
    data["mcpServers"]["memos"]["timeout"] = 60000
    cj.write_text(json.dumps(data, indent=2) + "\n")

    r = run(["disable", "memos", "--all-drivers"])
    assert r.exit_code == 0, r.stdout
    assert "drift" in r.stdout
    assert "timeout" in r.stdout
    # Warning is not a blocker: the disable still happened everywhere.
    assert "memos" not in json.loads(cj.read_text()).get("mcpServers", {})
    assert json.loads(paths.opencode_config_file().read_text())["mcp"]["servers"]["memos"]["disabled"] is True


def test_enable_warns_on_drift_then_overwrites():
    run(["add", "memos", "--url", "https://memos.example.com/mcp",
         "--token", "t", "--all-drivers"])
    cj = paths.claude_json_file()
    data = json.loads(cj.read_text())
    data["mcpServers"]["memos"]["timeout"] = 60000
    cj.write_text(json.dumps(data, indent=2) + "\n")

    r = run(["enable", "memos", "--all-drivers"])  # registry says enabled already
    assert r.exit_code == 0, r.stdout
    assert "drift" in r.stdout
    # Warning came first, then the entry was re-rendered without the extra key.
    assert "timeout" not in json.loads(cj.read_text())["mcpServers"]["memos"]


def test_disable_does_not_warn_for_foreign_keys_on_flag_flip_drivers():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--driver", "opencode"])
    oc = paths.opencode_config_file()
    data = json.loads(oc.read_text())
    data["mcp"]["servers"]["outline"]["timeout"] = 30000
    oc.write_text(json.dumps(data, indent=2) + "\n")

    r = run(["disable", "outline", "--driver", "opencode"])
    assert r.exit_code == 0, r.stdout
    assert "drift" not in r.stdout
    # In-place flag flip keeps the hand-added key.
    assert json.loads(oc.read_text())["mcp"]["servers"]["outline"]["timeout"] == 30000


def test_list_shows_disabled_state():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--all-drivers"])
    run(["disable", "outline", "--all-drivers"])
    r = run(["list"])
    assert r.exit_code == 0
    assert "outline" in r.stdout
    assert "DISABLED" in r.stdout


def test_status_counts_enabled_and_disabled():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--no-apply"])
    run(["disable", "outline", "--no-apply"])
    r = run(["status", "--all-drivers"])
    assert r.exit_code == 0
    assert "1 disabled" in r.stdout


# ---- test: disabled-server note (offline via probe stub) --------------------

def test_test_notes_disabled_server(monkeypatch):
    from types import SimpleNamespace

    from mcp_plugin_mgr import probe

    monkeypatch.setattr(probe, "probe_stdio", lambda *a, **k: SimpleNamespace(
        ok=True, summary="stdio ok", server_info=None, detail="", remediation=""))
    run(["add", "bogus", "--stdio", "--command", "bogus-cmd", "--no-apply"])

    r = run(["test", "bogus"])  # enabled: no note
    assert r.exit_code == 0, r.stdout
    assert "DISABLED" not in r.stdout

    run(["disable", "bogus", "--no-apply"])
    r = run(["test", "bogus"])
    assert r.exit_code == 0, r.stdout
    assert "DISABLED" in r.stdout
    assert "mcp-plugin-mgr enable bogus" in r.stdout


# ---- _complete plumbing ----------------------------------------------------

def test_complete_servers():
    run(["add", "outline", "--url", "https://x", "--token", "t", "--no-apply"])
    r = run(["_complete", "servers"])
    assert r.exit_code == 0
    assert "outline" in r.stdout.split()


def test_complete_drivers():
    r = run(["_complete", "drivers"])
    assert r.exit_code == 0
    names = r.stdout.split()
    assert "claude-code" in names
    assert "opencode" in names
    assert "qodercli" in names


def test_complete_presets():
    r = run(["_complete", "presets"])
    assert r.exit_code == 0
    assert "outline" in r.stdout.split()


def test_add_eof_at_driver_prompt_applies_all():
    """A stream that ran out (or Ctrl-D) at the driver prompt behaves like
    Enter — every driver — instead of raising EOFError."""
    r = run(["add", "outline", "--url", "https://my/mcp", "--token", "tok"],
            input="")
    assert r.exit_code == 0, r.stdout
    assert "Traceback" not in r.stdout
    for p in (paths.claude_json_file(), paths.opencode_config_file(),
              paths.qoder_settings_file()):
        assert "outline" in p.read_text()
