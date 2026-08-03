"""Tests for allow.py + the --auto-allow flag on add/remove.

allow.py merges tool names into Claude Code permissions.allow, preserving every
other key (env/model owned by model-switch). The CLI tests verify the
end-to-end flag (outline's 15 tools; memos wildcard; remove cleans up) through
the conftest-redirected settings path — never the real ~/.claude/settings.json.
"""
import json

from mcp_plugin_mgr import allow, paths
from mcp_plugin_mgr.presets import Preset, get_preset

from _mcp_cli_runner import invoke_cli as run


# --- allow_entries_for -------------------------------------------------------

def test_entries_use_preset_allow_tools_when_present():
    p = get_preset("outline")
    entries = allow.allow_entries_for("outline", p)
    assert len(entries) == 15
    assert entries[0] == "mcp__outline__create_attachment"
    assert all(e.startswith("mcp__outline__") for e in entries)


def test_entries_use_agent_html_drop_six_tools():
    # upload_html writes large HTML -> preset enumerates all 6 tools (no wildcard).
    entries = allow.allow_entries_for("agent-html-drop", get_preset("agent-html-drop"))
    assert len(entries) == 6
    assert all(e.startswith("mcp__agent-html-drop__") for e in entries)
    assert "mcp__agent-html-drop__upload_html" in entries


def test_entries_fall_back_to_server_wildcard():
    # memos preset has no allow_tools -> mcp__memos wildcard.
    assert allow.allow_entries_for("memos", get_preset("memos")) == ["mcp__memos"]
    # no preset at all -> wildcard too.
    assert allow.allow_entries_for("mysrv", None) == ["mcp__mysrv"]
    # preset object without allow_tools.
    bare = Preset(name="x", transport="http", allow_tools=[])
    assert allow.allow_entries_for("x", bare) == ["mcp__x"]


# --- add_allowed_tools -------------------------------------------------------

def test_add_creates_permissions_allow_when_missing(tmp_path):
    p = tmp_path / "settings.json"
    added = allow.add_allowed_tools(p, ["mcp__outline__fetch", "mcp__outline__create_document"])
    assert sorted(added) == ["mcp__outline__create_document", "mcp__outline__fetch"]
    data = json.loads(p.read_text())
    assert set(data["permissions"]["allow"]) == {"mcp__outline__fetch", "mcp__outline__create_document"}


def test_add_merges_and_dedups(tmp_path):
    p = tmp_path / "settings.json"
    allow.add_allowed_tools(p, ["mcp__outline__fetch"])
    # second add: one new, one dup
    added = allow.add_allowed_tools(p, ["mcp__outline__fetch", "mcp__outline__update_document"])
    assert added == ["mcp__outline__update_document"]
    data = json.loads(p.read_text())
    assert set(data["permissions"]["allow"]) == {"mcp__outline__fetch", "mcp__outline__update_document"}


def test_add_preserves_other_keys_owned_by_model_switch(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "env": {"ANTHROPIC_MODEL": "glm-5.2"},
        "model": "glm-5.2",
        "theme": "dark",
    }))
    allow.add_allowed_tools(p, ["mcp__outline__fetch"])
    data = json.loads(p.read_text())
    # model-switch's keys untouched.
    assert data["env"] == {"ANTHROPIC_MODEL": "glm-5.2"}
    assert data["model"] == "glm-5.2"
    assert data["theme"] == "dark"
    # our key added.
    assert data["permissions"]["allow"] == ["mcp__outline__fetch"]


def test_add_empty_entries_is_noop(tmp_path):
    p = tmp_path / "settings.json"
    assert allow.add_allowed_tools(p, []) == []
    assert not p.exists()


# --- remove_allowed_tools ----------------------------------------------------

def test_remove_strips_listed_preserves_others(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "env": {"X": "y"},
        "permissions": {"allow": ["mcp__outline__fetch", "mcp__outline__update_document", "mcp__other"]},
    }))
    removed = allow.remove_allowed_tools(p, ["mcp__outline__fetch", "mcp__outline__update_document"])
    assert sorted(removed) == ["mcp__outline__fetch", "mcp__outline__update_document"]
    data = json.loads(p.read_text())
    assert data["permissions"]["allow"] == ["mcp__other"]
    assert data["env"] == {"X": "y"}  # preserved


def test_remove_when_absent_is_noop(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"permissions": {"allow": ["mcp__other"]}}))
    assert allow.remove_allowed_tools(p, ["mcp__outline__fetch"]) == []
    assert json.loads(p.read_text())["permissions"]["allow"] == ["mcp__other"]


# --- CLI --auto-allow --------------------------------------------------------

def test_cli_add_outline_auto_allow_writes_15_rules_and_preserves_model_switch_keys():
    # Pre-seed the (redirected) settings with model-switch-owned keys.
    paths.claude_settings_file().parent.mkdir(parents=True, exist_ok=True)
    paths.claude_settings_file().write_text(json.dumps({"env": {"ANTHROPIC_MODEL": "glm"}, "model": "glm"}))

    r = run(["add", "outline", "--url", "https://x/mcp", "--token", "t",
             "--all-drivers", "--auto-allow"])
    assert r.exit_code == 0, r.stdout
    assert "Pre-approved 15 tool" in r.stdout

    data = json.loads(paths.claude_settings_file().read_text())
    allow_list = data["permissions"]["allow"]
    assert len(allow_list) == 15
    assert "mcp__outline__update_document" in allow_list
    # model-switch keys preserved.
    assert data["env"] == {"ANTHROPIC_MODEL": "glm"}
    assert data["model"] == "glm"


def test_cli_add_memos_auto_allow_uses_wildcard():
    r = run(["add", "memos", "--url", "https://m/mcp", "--token", "t",
             "--all-drivers", "--auto-allow"])
    assert r.exit_code == 0, r.stdout
    data = json.loads(paths.claude_settings_file().read_text())
    assert data["permissions"]["allow"] == ["mcp__memos"]


def test_cli_add_agent_html_drop_auto_allow_writes_six_rules():
    r = run(["add", "agent-html-drop", "--url", "https://notes/mcp", "--token", "t",
             "--all-drivers", "--auto-allow"])
    assert r.exit_code == 0, r.stdout
    assert "Pre-approved 6 tool" in r.stdout
    allow_list = json.loads(paths.claude_settings_file().read_text())["permissions"]["allow"]
    assert len(allow_list) == 6
    assert "mcp__agent-html-drop__upload_html" in allow_list


def test_cli_add_without_auto_allow_does_not_touch_settings():
    r = run(["add", "outline", "--url", "https://x/mcp", "--token", "t", "--all-drivers"])
    assert r.exit_code == 0, r.stdout
    # settings.json was never created.
    assert not paths.claude_settings_file().exists()


def test_cli_add_auto_allow_idempotent_second_run_no_new():
    run(["add", "outline", "--url", "https://x/mcp", "--token", "t", "--all-drivers", "--auto-allow"])
    r = run(["add", "outline", "--url", "https://x/mcp", "--token", "t",
             "--all-drivers", "--auto-allow", "--force"])
    assert r.exit_code == 0, r.stdout
    assert "already had these tools" in r.stdout
    # still exactly 15, not 30.
    assert len(json.loads(paths.claude_settings_file().read_text())["permissions"]["allow"]) == 15


def test_cli_remove_auto_allow_cleans_up():
    run(["add", "outline", "--url", "https://x/mcp", "--token", "t", "--all-drivers", "--auto-allow"])
    r = run(["remove", "outline", "--all-drivers", "--auto-allow"])
    assert r.exit_code == 0, r.stdout
    assert "Removed 15 tool" in r.stdout
    allow_list = json.loads(paths.claude_settings_file().read_text())["permissions"]["allow"]
    assert allow_list == []


def test_cli_add_no_apply_skips_auto_allow():
    r = run(["add", "outline", "--url", "https://x/mcp", "--token", "t",
             "--no-apply", "--auto-allow"])
    assert r.exit_code == 0, r.stdout
    # --no-apply means don't touch anything outside the registry, incl. permissions.
    assert not paths.claude_settings_file().exists()
