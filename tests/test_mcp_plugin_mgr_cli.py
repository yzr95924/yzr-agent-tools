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
    assert oc["mcp"]["outline"] == {
        "type": "remote", "url": "https://my/mcp", "enabled": True,
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
    assert oc["mcp"]["memos"] == {
        "type": "remote", "url": "https://memos.example.com/mcp", "enabled": True,
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
    assert oc["mcp"]["mystd"]["command"] == ["uvx", "--from", "X", "run"]


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


def test_complete_presets():
    r = run(["_complete", "presets"])
    assert r.exit_code == 0
    assert "outline" in r.stdout.split()
