"""Tests for the OpenCode MCP driver (opencode.json mcp.servers, V2 native shape)."""
import json

import pytest

from mcp_plugin_mgr.drivers.opencode import OpenCodeMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP, TRANSPORT_STDIO


@pytest.fixture
def driver(tmp_path):
    return OpenCodeMcpDriver(
        config_path=tmp_path / ".config" / "opencode" / "opencode.json"
    )


def _http():
    return ServerEntry(
        name="outline",
        transport=TRANSPORT_HTTP,
        url="https://x/mcp",
        headers={"Authorization": "Bearer t"},
    )


def _read(driver):
    return json.loads(driver.config_path.read_text())


def _write(driver, data):
    cp = driver.config_path
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data))
    return cp


# --- render (vocabulary translation) ----------------------------------------

def test_render_http_uses_remote_vocab_with_disabled(driver):
    assert driver.render(_http()) == {
        "type": "remote",
        "url": "https://x/mcp",
        "disabled": False,
        "headers": {"Authorization": "Bearer t"},
    }


def test_render_http_without_headers_omits_key(driver):
    e = ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x")
    assert driver.render(e) == {"type": "remote", "url": "https://x", "disabled": False}


def test_render_stdio_combines_command_into_array_and_uses_environment(driver):
    e = ServerEntry(
        name="g", transport=TRANSPORT_STDIO, command="uvx",
        args=["--from", "X", "run"], env={"K": "V"},
    )
    assert driver.render(e) == {
        "type": "local",
        "command": ["uvx", "--from", "X", "run"],
        "disabled": False,
        "environment": {"K": "V"},
    }


def test_render_stdio_without_env_omits_environment(driver):
    e = ServerEntry(name="g", transport=TRANSPORT_STDIO, command="uvx", args=["X"])
    out = driver.render(e)
    assert out == {"type": "local", "command": ["uvx", "X"], "disabled": False}
    assert "environment" not in out


def test_render_respects_disabled_entry(driver):
    e = _http()
    e.enabled = False
    assert driver.render(e)["disabled"] is True


# --- add / remove + preservation --------------------------------------------

def test_add_nests_under_servers_and_preserves_foreign_keys(driver):
    _write(driver, {
        "$schema": "https://opencode.ai/config.json",
        "model": "yzr-zai/glm",
        "providers": {"yzr-zai": {"package": "@opencode/ai/providers/anthropic"}},
        "mcp": {"existing": {"type": "remote", "url": "https://old", "enabled": True}},
    })
    driver.add_server("outline", _http())
    data = _read(driver)
    # Disjoint keys owned by model-switch are untouched.
    assert data["$schema"] == "https://opencode.ai/config.json"
    assert data["model"] == "yzr-zai/glm"
    assert data["providers"]["yzr-zai"]["package"] == "@opencode/ai/providers/anthropic"
    # A foreign V1 entry under mcp (not the name we operate on) is left alone.
    assert data["mcp"]["existing"]["url"] == "https://old"
    assert data["mcp"]["servers"]["outline"] == {
        "type": "remote", "url": "https://x/mcp", "disabled": False,
        "headers": {"Authorization": "Bearer t"},
    }


def test_add_reclaims_legacy_entry_of_same_name(driver):
    _write(driver, {"mcp": {"outline": {"type": "remote", "url": "https://old", "enabled": True}}})
    driver.add_server("outline", _http())
    data = _read(driver)
    assert "outline" not in data["mcp"]
    assert data["mcp"]["servers"]["outline"]["url"] == "https://x/mcp"


def test_remove_is_idempotent(driver):
    driver.add_server("outline", _http())
    assert driver.remove_server("outline") is True
    assert driver.remove_server("outline") is False


def test_remove_clears_legacy_only_entry(driver):
    _write(driver, {"mcp": {"outline": {"type": "remote", "url": "https://old", "enabled": True}}})
    assert driver.remove_server("outline") is True
    assert "outline" not in _read(driver)["mcp"]
    assert "outline" not in _read(driver)["mcp"].get("servers", {})


# --- set_enabled (native flag, in place) -------------------------------------

def _v1_entry():
    # V1 shape the old driver wrote: enabled flag + a foreign key added by
    # hand that must survive migration and flag flips.
    return {
        "type": "remote", "url": "https://x/mcp", "enabled": True,
        "headers": {"Authorization": "Bearer t"},
        "timeout": 30000,
    }


def test_set_enabled_false_flips_flag_in_place_and_preserves_foreign_keys(driver):
    _write(driver, {
        "model": "yzr-zai/glm",
        "mcp": {
            "servers": {
                "outline": {
                    "type": "remote", "url": "https://x/mcp", "disabled": False,
                    "headers": {"Authorization": "Bearer t"},
                    "timeout": 30000,
                },
                "other": {"type": "remote", "url": "https://other", "disabled": False},
            },
        },
    })
    action = driver.set_enabled("outline", _http(), False)
    data = _read(driver)

    assert action == "flagged"
    entry = data["mcp"]["servers"]["outline"]
    assert entry["disabled"] is True
    assert entry["timeout"] == 30000
    assert entry["headers"] == {"Authorization": "Bearer t"}
    # Sibling servers + unrelated top-level keys untouched.
    assert data["mcp"]["servers"]["other"]["disabled"] is False
    assert data["model"] == "yzr-zai/glm"


def test_set_enabled_true_flips_flag_back_in_place(driver):
    _write(driver, {"mcp": {"servers": {"outline": {
        "type": "remote", "url": "https://x/mcp", "disabled": True,
        "headers": {"Authorization": "Bearer t"}, "timeout": 30000,
    }}}})
    action = driver.set_enabled("outline", _http(), True)
    entry = _read(driver)["mcp"]["servers"]["outline"]
    assert action == "flagged"
    assert entry["disabled"] is False
    assert entry["timeout"] == 30000


def test_disable_migrates_legacy_entry_and_keeps_its_extra_keys(driver):
    # Upgrade path: the entry on disk is still the V1 shape (enabled=true);
    # disabling must move it under mcp.servers as disabled=true, not deny it
    # as "absent".
    _write(driver, {"model": "yzr-zai/glm", "mcp": {"outline": _v1_entry()}})
    action = driver.set_enabled("outline", _http(), False)
    data = _read(driver)

    assert action == "flagged"
    assert "outline" not in data["mcp"]
    entry = data["mcp"]["servers"]["outline"]
    assert entry["disabled"] is True
    assert "enabled" not in entry
    assert entry["timeout"] == 30000
    assert entry["url"] == "https://x/mcp"
    assert data["model"] == "yzr-zai/glm"


def test_native_entry_wins_when_legacy_sibling_exists(driver):
    # V2 precedence: when both shapes name the same server, native rules.
    # Migration must not let the stale V1 copy overwrite the native entry.
    _write(driver, {"mcp": {
        "outline": {"type": "remote", "url": "https://stale", "enabled": True},
        "servers": {"outline": {"type": "remote", "url": "https://live", "disabled": True}},
    }})
    driver.set_enabled("outline", _http(), False)
    data = _read(driver)
    assert "outline" not in data["mcp"]
    assert data["mcp"]["servers"]["outline"]["url"] == "https://live"
    assert data["mcp"]["servers"]["outline"]["disabled"] is True


def test_set_enabled_false_on_absent_server_is_noop(driver):
    cp = _write(driver, {"mcp": {"servers": {"outline": {
        "type": "remote", "url": "https://x/mcp", "disabled": False}}}})
    before = cp.read_text()
    assert driver.set_enabled("ghost", _http(), False) == "absent"
    assert cp.read_text() == before


def test_set_enabled_true_on_absent_server_renders_entry(driver):
    assert driver.set_enabled("outline", _http(), True) == "written"
    data = _read(driver)
    assert data["mcp"]["servers"]["outline"] == {
        "type": "remote", "url": "https://x/mcp", "disabled": False,
        "headers": {"Authorization": "Bearer t"},
    }


def test_set_enabled_true_adds_missing_flag_on_hand_written_entry(driver):
    _write(driver, {
        "mcp": {"servers": {"outline": {"type": "remote", "url": "https://x/mcp"}}},
    })  # no disabled key
    assert driver.set_enabled("outline", _http(), True) == "flagged"
    assert _read(driver)["mcp"]["servers"]["outline"]["disabled"] is False


# --- V1 entries stay visible to list / has ------------------------------------

def test_list_servers_merges_legacy_v1_entries(driver):
    _write(driver, {"mcp": {
        "servers": {"new": {"type": "remote", "url": "https://new", "disabled": False}},
        "old": {"type": "remote", "url": "https://old", "enabled": False},
    }})
    servers = driver.list_servers()
    assert sorted(servers) == ["new", "old"]
    # The V1 entry reads back in V2 vocabulary.
    assert servers["old"]["disabled"] is True
    assert "enabled" not in servers["old"]
    assert driver.has_server("old") is True


def test_list_servers_native_entry_wins_over_legacy_same_name(driver):
    _write(driver, {"mcp": {
        "old": {"type": "remote", "url": "https://stale", "enabled": True},
        "servers": {"old": {"type": "remote", "url": "https://live", "disabled": True}},
    }})
    assert driver.list_servers()["old"]["url"] == "https://live"


# --- degenerate names ----------------------------------------------------------

def test_server_named_servers_does_not_eat_the_container(driver):
    _write(driver, {"mcp": {"servers": {"keep": {"type": "remote", "url": "https://k"}}}})
    e = ServerEntry(name="servers", transport=TRANSPORT_HTTP, url="https://mine")
    driver.add_server("servers", e)
    data = _read(driver)
    assert data["mcp"]["servers"]["keep"]["url"] == "https://k"
    assert data["mcp"]["servers"]["servers"]["url"] == "https://mine"
    # The container is only ever read as the map itself — its `servers`
    # member is a real server here, not a stray V1 entry.
    assert sorted(driver.list_servers()) == ["keep", "servers"]


def test_native_disable_flag(driver):
    assert driver.native_disable is True


def test_driver_name(driver):
    assert driver.name == "opencode"


def test_flag_state_uses_disabled_vocabulary(driver):
    assert driver.flag_state(True) == "disabled=false"
    assert driver.flag_state(False) == "disabled=true"
